"""Deterministic pressure tests: no paid providers or external services."""
import asyncio
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import select

from app.concurrency import ConcurrencyLimit, ClosingStreamingResponse
from app.config import Settings
from app.main import ChatInput
from app.models import Call, User
from test_api import client, login, companion


def test_pressure_and_cancel_release_slots():
    async def scenario():
        entered = 0
        peak = 0
        release = asyncio.Event()

        async def endpoint(scope, receive, send):
            nonlocal entered, peak
            entered += 1
            peak = max(peak, entered)
            try:
                await release.wait()
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'ok'})
            finally:
                entered -= 1

        app = ConcurrencyLimit(endpoint, 4)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            running = [asyncio.create_task(client.get('/work')) for _ in range(4)]
            for _ in range(100):
                if entered == 4:
                    break
                await asyncio.sleep(0)
            assert entered == 4
            responses = await asyncio.gather(*(client.get('/work') for _ in range(200)))
            assert all(r.status_code == 503 and r.headers['Retry-After'] == '1' for r in responses)
            running[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await running[0]
            assert app.active == 3
            release.set()
            await asyncio.gather(*running[1:])
            assert (await client.get('/work')).status_code == 200
            assert app.active == 0 and peak == 4
    asyncio.run(scenario())


def test_disconnect_during_send_closes_producer():
    async def scenario():
        closed = []

        async def producer():
            try:
                yield 'partial'
                await asyncio.sleep(60)
            finally:
                closed.append(True)

        async def send(message):
            if message['type'] == 'http.response.body':
                raise OSError('disconnected')

        with pytest.raises(OSError):
            await ClosingStreamingResponse(producer()).stream_response(send)
        assert closed == [True]
    asyncio.run(scenario())


@pytest.mark.parametrize('cancel', [False, True])
def test_stream_deadline_and_cancellation_preserve_budget(client, cancel):
    login(client)
    cid = companion(client)
    closed = []

    class SlowProvider:
        async def astream(self, messages):
            try:
                yield 'partial'
                await asyncio.sleep(60)
            finally:
                closed.append(True)

    client.app.state.provider = SlowProvider()
    # The route captures the settings object used to construct the application.
    settings = client.app.state.settings
    object.__setattr__(settings, 'stream_timeout', 0.03)
    with client.app.state.db() as db:
        owner = db.scalar(select(User.id))
    route = next(r for r in client.app.routes if r.path == '/v1/companions/{cid}/messages' and 'POST' in r.methods)
    response = route.endpoint(cid, ChatInput(content='hello', request_id='deadline-test'), stream=True, owner=owner)

    async def consume():
        iterator = response.body_iterator
        if cancel:
            import anyio
            # Model the cancellation scope used by StreamingResponse on disconnect.
            with anyio.CancelScope() as scope:
                assert 'partial' in await anext(iterator)
                scope.cancel()
                await anext(iterator)
        else:
            assert 'partial' in await anext(iterator)
            assert '"type": "error"' in await anext(iterator)
        await iterator.aclose()

    asyncio.run(consume())
    assert closed == [True]
    with client.app.state.db() as db:
        assert db.scalar(select(Call)).status == 'uncertain'
        assert db.scalar(select(User)).reserved > 0


@pytest.mark.parametrize('kwargs', [{'max_concurrent_requests': 0}, {'stream_timeout': float('inf')}, {'provider_timeout': -1}])
def test_invalid_limits(kwargs):
    with pytest.raises(RuntimeError):
        replace(Settings(), **kwargs).validate()

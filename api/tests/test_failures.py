import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_api import client, login, companion, send
from app.failures import NotStarted, provider_client
from app.providers import Provider
from app.models import Call, User, SiteBudget, Operation
from app.billing import metered, close_failure


@pytest.mark.parametrize('status,safe', [(401, True), (403, True), (404, True), (429, True), (400, False), (500, False)])
def test_provider_rejection_classification(status, safe):
    request = httpx.Request('POST', 'https://example.invalid')
    response = httpx.Response(status, request=request)
    with pytest.raises(NotStarted if safe else httpx.HTTPStatusError):
        with provider_client(1):
            response.raise_for_status()


@pytest.mark.parametrize('error,safe', [(httpx.ConnectTimeout, True), (httpx.ReadTimeout, False), (httpx.WriteError, False)])
def test_transport_failure_classification(error, safe):
    with pytest.raises(NotStarted if safe else error):
        with provider_client(1):
            raise error('private data')


@pytest.mark.parametrize('stream', [False, True])
def test_rejected_chat_releases_once_and_next_chat_works(client, stream, caplog):
    login(client)
    cid = companion(client)
    class Rejected:
        def complete(self, messages):
            raise NotStarted('Model authentication failed.')
        def stream(self, messages):
            raise NotStarted('Model authentication failed.')
            yield
    client.app.state.provider = Rejected()
    response = client.post(f'/v1/companions/{cid}/messages?stream={str(stream).lower()}',
        json={'content': 'hello', 'request_id': 'rejected-0001'})
    assert response.status_code == (200 if stream else 503)
    if stream:
        assert '"safe_to_retry": true' in response.text
    assert client.get('/v1/me').json()['reserved'] == 0
    with client.app.state.db() as db:
        call = db.scalar(select(Call))
        assert call.status == 'failed'
        assert db.get(SiteBudget, 1).reserved == 0
        record_id = call.id
    close_failure(client.app.state.db, Call, record_id, safe=True)
    assert 'reference=' + record_id in caplog.text
    client.app.state.provider = Provider(client.app.state.settings)
    assert send(client, cid, key='recovered-0002').status_code == 200


def test_rejected_embedding_can_retry_same_job(client):
    login(client)
    cid = companion(client)
    factory = client.app.state.db
    with factory() as db:
        owner = db.scalar(select(User.id))
    def reject():
        raise NotStarted('Model unavailable.')
    args = (factory, client.app.state.settings, owner, cid, 'embedding', 'retry-job', 100)
    with pytest.raises(HTTPException) as error:
        metered(*args, reject)
    assert error.value.status_code == 503
    assert client.get('/v1/me').json()['reserved'] == 0
    assert metered(*args, lambda: ([1.0], 3)) == [1.0]
    with factory() as db:
        assert db.scalar(select(Operation)).status == 'complete'
        assert db.get(SiteBudget, 1).used == 3


def test_partial_stream_stays_uncertain(client, caplog):
    login(client)
    cid = companion(client)
    class Interrupted:
        def stream(self, messages):
            yield 'partial'
            raise httpx.ReadTimeout('SECRET must not appear')
    client.app.state.provider = Interrupted()
    response = client.post(f'/v1/companions/{cid}/messages?stream=true',
        json={'content': 'hello', 'request_id': 'interrupted-0001'})
    assert '"type": "error"' in response.text
    assert '"safe_to_retry": true' not in response.text
    assert client.get('/v1/me').json()['reserved'] > 0
    assert 'SECRET' not in response.text + caplog.text


def test_search_outage_stream_warns_and_completes(client, monkeypatch):
    from app.search import Search
    login(client)
    cid = companion(client)
    object.__setattr__(client.app.state.settings, 'es_url', 'http://search.invalid')
    def broken(*args):
        raise httpx.ConnectError('private endpoint')
    monkeypatch.setattr(Search, 'retrieve', broken)
    response = client.post(f'/v1/companions/{cid}/messages?stream=true',
        json={'content': 'hello', 'request_id': 'degraded-0001'})
    assert '"type": "warning"' in response.text
    assert '"type": "done"' in response.text
    assert client.get('/v1/me').json()['reserved'] == 0


def test_outbox_pauses_after_ten_failures(client, caplog):
    import time
    from app.models import Outbox
    from app.worker import process_outbox
    from sqlalchemy import update
    login(client)
    cid = companion(client)
    send(client, cid)
    mid = client.get(f'/v1/companions/{cid}/messages').json()[0]['id']
    client.post(f'/v1/companions/{cid}/memories', json={'source_message_id': mid, 'consent': True})
    class BrokenSearch:
        calls = 0
        def index(self, *args):
            self.calls += 1
            raise RuntimeError('SECRET')
    search = BrokenSearch()
    for _ in range(11):
        with client.app.state.db.begin() as db:
            db.execute(update(Outbox).values(available=time.time()-1))
        process_outbox(client.app.state.db, client.app.state.settings, None, search)
    assert search.calls == 10
    assert 'memory_sync_paused' in caplog.text
    assert 'SECRET' not in caplog.text

    from app.worker import retry_outbox
    with client.app.state.db() as db:
        job_id = db.scalar(select(Outbox.id))
    retry_outbox(client.app.state.db, job_id)
    with pytest.raises(ValueError):
        retry_outbox(client.app.state.db, job_id)
    process_outbox(client.app.state.db, client.app.state.settings, None, search)
    assert search.calls == 11

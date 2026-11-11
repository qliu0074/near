"""Fail-fast, per-process admission; slots cover the entire response stream."""
import anyio
from starlette.responses import JSONResponse, StreamingResponse


class ClosingStreamingResponse(StreamingResponse):
    """Close a suspended producer even when disconnect interrupts ASGI send."""

    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


class ConcurrencyLimit:
    def __init__(self, app, limit):
        self.app = app
        self.limit = limit
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/v1/health':
            return await self.app(scope, receive, send)
        # No await between checking and incrementing: atomic on the ASGI loop.
        if self.active >= self.limit:
            return await JSONResponse(
                {'detail': 'Server busy. Please try again later.'}, status_code=503,
                headers={'Retry-After': '1'},
            )(scope, receive, send)
        self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1

"""Sanitized failure handling. Never log provider bodies, URLs or credentials."""
import logging
from contextlib import contextmanager, asynccontextmanager
import httpx

log = logging.getLogger('near.failures')


class NotStarted(Exception):
    """The provider did not accept a generation request."""


@contextmanager
def provider_client(timeout):
    # HTTPX retries only connection establishment, never read/write failures.
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False,
                          transport=httpx.HTTPTransport(retries=2)) as client:
            yield client
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        raise NotStarted('Model connection failed. Please try again later.') from None
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        messages = {
            401: 'Model authentication failed. Contact the administrator.',
            403: 'Model access was denied. Contact the administrator.',
            404: 'Model or endpoint was not found. Contact the administrator.',
            429: 'Model capacity or provider quota is unavailable. Please try again later.',
        }
        # Other statuses (including 400 content inspection and 5xx) can have
        # ambiguous billing semantics. Do not assume they were free.
        if status in messages:
            raise NotStarted(messages[status]) from None
        raise


def report(event, reference, error):
    log.warning('%s reference=%s error_type=%s', event, reference, type(error).__name__)


@asynccontextmanager
async def async_provider_client(timeout):
    # HTTPX retries only connection establishment, never read/write failures.
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False,
                          transport=httpx.AsyncHTTPTransport(retries=2)) as client:
            yield client
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        raise NotStarted('Model connection failed. Please try again later.') from None
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        messages = {
            401: 'Model authentication failed. Contact the administrator.',
            403: 'Model access was denied. Contact the administrator.',
            404: 'Model or endpoint was not found. Contact the administrator.',
            429: 'Model capacity or provider quota is unavailable. Please try again later.',
        }
        # Other statuses (including 400 content inspection and 5xx) can have
        # ambiguous billing semantics. Do not assume they were free.
        if status in messages:
            raise NotStarted(messages[status]) from None
        raise

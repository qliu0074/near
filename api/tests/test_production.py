from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.search import Search
from app.models import SiteBudget
from test_api import client


def production(**overrides):
    values = dict(environment='production', provider='qwen', email_mode='smtp',
                  database_url='postgresql+psycopg://near:secret@postgres/near',
                  origin='https://near.example.com', auto_schema=False,
                  auth_secret='a' * 64, qwen_key='test', qwen_url='https://provider.example/v1',
                  smtp_host='smtp.example.com', smtp_from='near@example.com', smtp_tls=True,
                  es_url='http://elasticsearch:9200', es_key='', es_user='elastic', es_password='secret')
    values.update(overrides)
    return replace(Settings(), **values)


def test_production_authenticated_search_configuration():
    production().validate()
    production(es_user='', es_password='', es_key='api-key').validate()


@pytest.mark.parametrize('overrides', [
    {'provider': 'mock'}, {'email_mode': 'development'}, {'auto_schema': True},
    {'origin': 'http://near.example.com'}, {'origin': 'https://near.example.com/'},
    {'origin': 'https://near.example.com/path'}, {'origin': 'https://near.example.com?x=1'},
    {'origin': 'https://user:password@near.example.com'}, {'origin': 'https://'},
    {'auth_secret': 'short'}, {'smtp_tls': False}, {'es_password': ''}, {'es_url': ''},
    {'qwen_key': ''}, {'database_url': 'sqlite:///near.db'},
])
def test_production_rejects_unsafe_configuration(overrides):
    with pytest.raises(RuntimeError):
        production(**overrides).validate()


def test_search_credentials_and_api_key_precedence():
    received = []

    def respond(request):
        received.append(request.headers['Authorization'])
        return httpx.Response(200, json={'ok': True})

    real_client = httpx.Client
    with patch('app.search.httpx.Client', side_effect=lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(respond))):
        Search(production()).request('GET', '/')
        Search(production(es_key='key')).request('GET', '/')
    assert received == ['Basic ZWxhc3RpYzpzZWNyZXQ=', 'ApiKey key']


def test_readiness_checks_initialized_database(client):
    assert client.get('/v1/ready').status_code == 200
    with client.app.state.db.begin() as db:
        db.delete(db.get(SiteBudget, 1))
    assert client.get('/v1/ready').status_code == 503
    assert client.get('/v1/health').status_code == 200

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_api import client, login, companion
from app.config import Settings
from app.failures import NotStarted
from app.main import create_app
from app.models import Memory, Operation, User
from app.providers import Provider, Reply
from app.retrieval import rank_memories
from app.search import Search


ENDPOINT = 'https://rerank.invalid/api/v1/services/rerank/text-rerank/text-rerank'


def config(**kwargs):
    return replace(Settings(), rerank_enabled=True, rerank_url=ENDPOINT,
                   rerank_key='test-key', provider='qwen', **kwargs)


def memories():
    return [SimpleNamespace(id=str(i), version=1, content=content) for i, content in
            enumerate(['Lavender tea', '  LAVENDER\n tea ', 'Green apples', 'Blue sky'])]


@pytest.mark.parametrize('failed', ['bm25', 'knn', 'both'])
def test_search_branch_failure_and_configured_limits(failed):
    search = Search(replace(Settings(), bm25_candidates=7, knn_candidates=9,
                            knn_num_candidates=25, fusion_candidates=12))
    bodies = []
    def request(method, path, body):
        bodies.append(body)
        branch = 'knn' if 'knn' in body else 'bm25'
        if failed in (branch, 'both'):
            raise httpx.ReadTimeout('private details')
        return {'hits': {'hits': [{'_id': 'one'}, {'_id': 'one'}, {'_id': 'two'}]}}
    search.request = request
    if failed == 'both':
        with pytest.raises(httpx.ReadTimeout):
            search.retrieve('owner', 'companion', 'query', [1.0])
    else:
        assert search.retrieve('owner', 'companion', 'query', [1.0]) == ['one', 'two']
    assert bodies[0]['size'] == 7
    assert bodies[1]['size'] == bodies[1]['knn']['k'] == 9
    assert bodies[1]['knn']['num_candidates'] == 25


def test_fusion_keeps_candidates_beyond_final_memory_limit():
    search = Search(replace(Settings(), fusion_candidates=8, memory_limit=2))
    search.request = lambda *args: {'hits': {'hits': [{'_id': str(i)} for i in range(10)]}}
    assert search.retrieve('o', 'c', 'q', None) == list(map(str, range(8)))


@pytest.mark.parametrize('changes', [
    {'bm25_candidates': 0}, {'knn_num_candidates': 1}, {'fusion_candidates': 501},
    {'memory_limit': 11}, {'rerank_candidates': 41}, {'rerank_timeout': float('nan')},
    {'rerank_url': 'http://insecure.invalid'}, {'rerank_url': ENDPOINT + '?key=secret'},
])
def test_invalid_retrieval_configuration(changes):
    with pytest.raises(RuntimeError):
        replace(config(), **changes).validate()


def test_provider_native_payload_and_separate_key(monkeypatch):
    captured = {}
    class Client:
        def post(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return httpx.Response(200, request=httpx.Request('POST', url),
                json={'output': {'results': [{'index': 1, 'relevance_score': .9}]},
                      'usage': {'total_tokens': 12}})
    @contextmanager
    def fake_client(timeout):
        captured['timeout'] = timeout
        yield Client()
    monkeypatch.setattr('app.providers.provider_client', fake_client)
    result, usage = Provider(config()).rerank_with_usage('query', ['a', 'b'])
    assert usage == 12 and result['results'][0]['index'] == 1
    assert captured['url'] == ENDPOINT
    assert captured['headers']['Authorization'] == 'Bearer test-key'
    assert captured['json'] == {'model': 'gte-rerank-v2',
        'input': {'query': 'query', 'documents': ['a', 'b']},
        'parameters': {'top_n': 2, 'return_documents': False}}


def setup_rank(client, provider, **changes):
    login(client)
    cid = companion(client)
    factory = client.app.state.db
    with factory() as db:
        owner = db.scalar(select(User.id))
    settings = replace(client.app.state.settings, provider='qwen', rerank_enabled=True,
                       rerank_url=ENDPOINT, rerank_key='test-key', **changes)
    def run(rows=None, key='rank-request-001'):
        return rank_memories(factory, settings, provider, owner, cid, 'tea', key,
                             memories() if rows is None else rows)
    return run, factory


def test_rerank_deduplication_top_n_cache_and_usage(client):
    calls = []
    class Reranker:
        def rerank_with_usage(self, query, documents):
            calls.append(documents)
            return {'results': [{'index': 1, 'relevance_score': .8},
                                {'index': 0, 'relevance_score': .1}]}, 17
    run, factory = setup_rank(client, Reranker(), memory_limit=2, rerank_candidates=2)
    assert [m.id for m in run()] == ['2', '0']
    assert [m.id for m in run()] == ['2', '0']
    assert calls == [['Lavender tea', 'Green apples']]
    with factory() as db:
        op = db.scalar(select(Operation).where(Operation.purpose == 'rerank'))
        assert (op.status, op.actual) == ('complete', 17)
        user = db.scalar(select(User))
        assert user.used == 17 and user.reserved == 0
    changed = memories(); changed[2].version += 1
    run(changed)
    assert len(calls) == 2


@pytest.mark.parametrize('result', [None, {}, {'results': []},
    {'results': [{'index': 99, 'relevance_score': .8}]},
    {'results': [{'index': True, 'relevance_score': .8}]},
    {'results': [{'index': 0, 'relevance_score': float('inf')}]},
    {'results': [{'index': 0, 'relevance_score': .8}, {'index': 0, 'relevance_score': .7}]},
])
def test_invalid_rankings_fall_back_but_usage_is_settled(client, result):
    provider = SimpleNamespace(rerank_with_usage=lambda *args: (result, 11))
    run, factory = setup_rank(client, provider)
    assert [m.id for m in run()] == ['0', '2', '3']
    with factory() as db:
        assert db.scalar(select(User)).used == 11
        assert db.scalar(select(User)).reserved == 0


@pytest.mark.parametrize('uncertain', [False, True])
def test_rejection_fallback_and_uncertain_reservation(client, uncertain, caplog):
    def fail(*args):
        if uncertain:
            raise httpx.ReadTimeout('secret-content')
        raise NotStarted('Rejected')
    run, factory = setup_rank(client, SimpleNamespace(rerank_with_usage=fail))
    if uncertain:
        with pytest.raises(HTTPException) as error:
            run()
        assert error.value.status_code == 502
        with pytest.raises(HTTPException) as error:
            run()
        assert error.value.status_code == 409
    else:
        assert [m.id for m in run()] == ['0', '2', '3']
    with factory() as db:
        op = db.scalar(select(Operation).where(Operation.purpose == 'rerank'))
        assert op.status == ('uncertain' if uncertain else 'failed')
        assert bool(db.scalar(select(User)).reserved) == uncertain
    assert 'secret-content' not in caplog.text


def test_partial_ranking_appends_rrf_tail_and_ties_are_stable(client):
    provider = SimpleNamespace(rerank_with_usage=lambda *args: (
        {'results': [{'index': 1, 'relevance_score': .8}, {'index': 0, 'relevance_score': .8}]}, 5))
    run, _ = setup_rank(client, provider)
    assert [m.id for m in run()] == ['0', '2', '3']


def test_disabled_empty_singleton_and_oversized_queries_skip_provider():
    def fail(*args):
        raise AssertionError('Must not call provider or database')
    provider = SimpleNamespace(rerank_with_usage=fail)
    for settings, query, rows in [(replace(config(), rerank_enabled=False), 'tea', memories()),
                                  (replace(config(), provider='mock'), 'tea', memories()),
                                  (config(), 'tea', []), (config(), 'tea', memories()[:2]),
                                  (config(), 'x' * 4001, memories())]:
        rank_memories(fail, settings, provider, 'owner', 'companion', query, 'key', rows)


def test_chat_authorizes_before_rerank_and_fast_mode_skips_it(client, monkeypatch):
    login(client); cid = companion(client)
    factory = client.app.state.db
    with factory.begin() as db:
        owner = db.scalar(select(User.id))
        db.add_all([Memory(id='valid-'+str(i), owner=owner, companion=cid, source='source-'+str(i), content=content)
                    for i, content in enumerate(['lavender', 'apples'])])
        db.add(Memory(id='deleted', owner=owner, companion=cid, source='deleted-source', content='SECRET', deleted=True))
        db.add(Memory(id='foreign', owner='other', companion=cid, source='foreign-source', content='SECRET'))
    monkeypatch.setattr(Search, 'retrieve', lambda *args: ['deleted', 'foreign', 'valid-0', 'valid-1'])
    seen, prompts = [], []
    class RealProvider:
        def embed_with_usage(self, query): return [1., 0.], 2
        def rerank_with_usage(self, query, docs):
            seen.append(docs)
            return {'results': [{'index': 1, 'relevance_score': .9}]}, 3
        def complete(self, messages):
            prompts.append(messages)
            return Reply('ok', 4)
    settings = replace(client.app.state.settings, provider='qwen', rerank_enabled=True,
                       rerank_url=ENDPOINT, rerank_key='key', es_url='http://search.invalid', memory_limit=1)
    app = create_app(settings); app.state.provider = RealProvider()
    with TestClient(app, headers=dict(client.headers), cookies=client.cookies) as second:
        body = {'content': 'tea', 'request_id': 'rerank-chat-001'}
        assert second.post(f'/v1/companions/{cid}/messages', json=body).status_code == 200
        assert second.post(f'/v1/companions/{cid}/messages', json=body).json()['replayed']
        assert second.post(f'/v1/companions/{cid}/messages', json={**body,
            'request_id': 'rerank-fast-001', 'mode': 'fast'}).status_code == 200
    assert seen == [['lavender', 'apples']]
    assert 'apples' in prompts[0][0]['content'] and 'lavender' not in prompts[0][0]['content']
    assert 'SECRET' not in str(prompts)

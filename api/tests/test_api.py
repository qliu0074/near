from dataclasses import replace
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from app.config import Settings
from app.main import create_app
from app.models import Call, User, Message, Outbox, Memory
from app.search import Search, rrf
from app.providers import estimate_input


@pytest.fixture
def client(tmp_path):
    settings = replace(Settings(), database_url=f'sqlite:///{tmp_path}/test.db',
                       es_url='', provider='mock', environment='development', token_limit=100000)
    with TestClient(create_app(settings), headers={'Origin': settings.origin}) as client:
        yield client


def login(client, email='one@example.com'):
    response = client.post('/v1/auth/email/request', json={'email': email})
    assert response.status_code == 200
    code = response.json()['development_code']
    result = client.post('/v1/auth/email/verify', json={'email': email, 'code': code})
    assert result.status_code == 200
    client.headers['x-csrf-token'] = result.json()['csrf']
    return code


def companion(client):
    response = client.post('/v1/companions', json={
        'name': '小树', 'kind': 'animal', 'profile': '温柔的小狐狸', 'fictional': True})
    assert response.status_code == 201
    return response.json()['id']


def send(client, cid, key='request-0001', content='今天很开心'):
    return client.post(f'/v1/companions/{cid}/messages', json={'content': content, 'request_id': key})


def test_auth_logout_and_rotation(client):
    assert client.get('/v1/me').status_code == 401
    code = login(client)
    assert client.get('/v1/me').json()['available'] == 100000
    assert client.post('/v1/auth/email/verify', json={'email':'one@example.com','code':code}).status_code == 400
    assert client.post('/v1/auth/logout').status_code == 200
    assert client.get('/v1/me').status_code == 401


def test_otp_attempts_and_rate_limit(client):
    body = {'email':'one@example.com'}
    code = client.post('/v1/auth/email/request', json=body).json()['development_code']
    assert client.post('/v1/auth/email/request', json=body).status_code == 429
    for _ in range(5):
        assert client.post('/v1/auth/email/verify', json={**body,'code':'000000'}).status_code == 400
    assert client.post('/v1/auth/email/verify', json={**body,'code':code}).status_code == 400


def test_csrf_and_origin(client):
    login(client)
    assert client.post('/v1/auth/logout', headers={'origin':'https://evil.example'}).status_code == 403
    assert client.post('/v1/auth/logout', headers={'x-csrf-token':'wrong'}).status_code == 403


def test_owner_isolation(client):
    login(client)
    cid = companion(client)
    send(client, cid)
    mid = client.get(f'/v1/companions/{cid}/messages').json()[0]['id']
    client.cookies.clear()
    login(client, 'two@example.com')
    assert client.get(f'/v1/companions/{cid}/messages').status_code == 404
    assert send(client, cid).status_code == 404
    assert client.delete(f'/v1/messages/{mid}').status_code == 404
    assert client.get('/v1/sync/events').json()['events'] == []


def test_idempotency_and_accounting(client):
    login(client); cid = companion(client)
    assert send(client, cid).status_code == 200
    used = client.get('/v1/me').json()['used']
    assert used > 0
    assert send(client, cid).json()['replayed']
    assert client.get('/v1/me').json()['used'] == used
    assert client.get('/v1/me').json()['reserved'] == 0
    assert len(client.get(f'/v1/companions/{cid}/messages').json()) == 2
    assert send(client, cid, content='Changed').status_code == 409


def test_insufficient_budget(client):
    login(client); cid = companion(client)
    with client.app.state.db.begin() as db:
        db.execute(update(User).values(used=99999))
    assert send(client, cid).status_code == 429
    assert client.get(f'/v1/companions/{cid}/messages').json() == []


def test_uncertain_provider_keeps_reservation(client):
    login(client); cid = companion(client)
    class Broken:
        def complete(self, _messages):
            raise TimeoutError('private request details must never leak')
    client.app.state.provider = Broken()
    response = send(client, cid)
    assert response.status_code == 502
    assert 'private request details' not in response.text
    assert client.get('/v1/me').json()['reserved'] > 0
    assert send(client, cid).status_code == 409
    assert send(client, cid, key='request-0002').status_code == 429


def test_memory_consent_and_cascade_delete(client):
    login(client); cid = companion(client); send(client, cid)
    mid = client.get(f'/v1/companions/{cid}/messages').json()[0]['id']
    path = f'/v1/companions/{cid}/memories'
    assert client.post(path, json={'source_message_id':mid,'consent':False}).status_code == 422
    response = client.post(path, json={'source_message_id':mid,'consent':True})
    assert response.status_code == 201
    assert len(client.get(path).json()) == 1
    assert client.delete(f'/v1/messages/{mid}').status_code == 200
    assert client.get(path).json() == []
    with client.app.state.db() as db:
        memory = db.scalar(select(Memory))
        assert memory.deleted and memory.content == ''
        assert len(list(db.scalars(select(Outbox)))) == 2
        assert db.scalar(select(Call)).reply == ''


def test_portrait_disabled_without_consuming_quota(client):
    login(client); cid = companion(client)
    for _ in range(4):
        assert client.post(f'/v1/companions/{cid}/portraits').status_code == 503
    assert client.get('/v1/companions').json()[0]['portrait_count'] == 0
    assert client.get('/v1/me').json()['portraits_enabled'] is False


def test_expired_message_not_visible_or_promotable(client):
    login(client); cid = companion(client); send(client,cid)
    with client.app.state.db.begin() as db:
        mid = db.scalar(select(Message.id))
        db.execute(update(Message).values(expires=time.time()-1))
    assert client.get(f'/v1/companions/{cid}/messages').json() == []
    assert client.post(f'/v1/companions/{cid}/memories',json={'source_message_id':mid,'consent':True}).status_code == 404


def test_event_cursor(client):
    login(client); cid = companion(client)
    result = client.get('/v1/sync/events').json()
    assert len(result['events']) == 1
    send(client,cid)
    new = client.get('/v1/sync/events', params={'after':result['cursor']}).json()
    assert len(new['events']) == 2
    assert new['cursor'] > result['cursor']


def test_body_limits_and_whitespace(client):
    login(client); cid = companion(client)
    assert send(client,cid,content=' '*20).status_code == 422
    assert send(client,cid,content='a'*2001).status_code == 422
    assert client.post('/v1/auth/email/request',content='x'*33000).status_code == 413


def test_no_production_mock_bypass():
    with pytest.raises(RuntimeError):
        create_app(replace(Settings(),environment='production'))


def test_rrf_deduplicates_and_fuses():
    assert rrf(['a','b','c'],['b','a','d'])[0:2] == ['a','b']
    assert rrf(['a','a','b']) == ['a','b']


def test_token_estimate_covers_unicode():
    english = estimate_input([{'role':'user','content':'hello'}])
    chinese = estimate_input([{'role':'user','content':'你好呀世界'}])
    assert chinese > english


def test_hybrid_filters_both_branches():
    search = Search(Settings())
    bodies = []
    def fake_request(method, path, body):
        bodies.append(body)
        return {'hits':{'hits':[{'_id':'memory-1'}]}}
    search.request = fake_request
    assert search.retrieve('owner-1','companion-1','query',[1.,0.]) == ['memory-1']
    filters = [{'term':{'owner':'owner-1'}},{'term':{'companion':'companion-1'}},{'term':{'deleted':False}}]
    assert bodies[0]['query']['bool']['filter'] == filters
    assert bodies[1]['knn']['filter']['bool']['filter'] == filters + [{'term':{'embedding_model':search.settings.embedding_model}}]


def test_streaming_persists_and_replays(client):
    login(client); cid = companion(client)
    body = {'content':'你好','request_id':'stream-0001'}
    response = client.post(f'/v1/companions/{cid}/messages?stream=true', json=body)
    assert response.status_code == 200
    assert 'text/event-stream' in response.headers['content-type']
    assert '"type": "delta"' in response.text and '"type": "done"' in response.text
    replay = client.post(f'/v1/companions/{cid}/messages?stream=true', json=body)
    assert '"replayed": true' in replay.text
    assert len(client.get(f'/v1/companions/{cid}/messages').json()) == 2


def test_stream_failure_does_not_persist_partial(client):
    login(client); cid = companion(client)
    class Interrupted:
        def stream(self, prompt):
            yield 'partial'
            raise TimeoutError()
    client.app.state.provider = Interrupted()
    response = client.post(f'/v1/companions/{cid}/messages?stream=true',
        json={'content':'你好','request_id':'stream-0002'})
    assert '"type": "error"' in response.text
    assert client.get(f'/v1/companions/{cid}/messages').json() == []
    assert client.get('/v1/me').json()['reserved'] > 0


def test_all_device_logout(client):
    login(client)
    cookie = client.cookies.get('near_session')
    assert client.post('/v1/auth/logout?all_devices=true').status_code == 200
    client.cookies.set('near_session', cookie)
    assert client.get('/v1/me').status_code == 401


def test_es_outage_is_no_memory_fallback(client, monkeypatch):
    login(client); cid = companion(client)
    captured = []
    attempted = []
    def unavailable(*args):
        attempted.append(True)
        raise ConnectionError('ES unavailable')
    def complete(messages):
        captured.extend(messages)
        from app.providers import Reply
        return Reply('Mock reply', 10)
    monkeypatch.setattr(Search, 'retrieve', unavailable)
    app = create_app(replace(client.app.state.settings, es_url='http://unavailable.invalid'))
    app.state.provider.complete = complete
    with TestClient(app, headers=dict(client.headers), cookies=client.cookies) as second:
        assert send(second,cid).status_code == 200
    assert attempted == [True]
    assert 'MEMORY DATA: []' in captured[0]['content']


@pytest.mark.parametrize('content', ['今天过得怎么样？', '¿Cómo estás hoy? 😊', 'こんにちは、元気ですか？', 'مرحبًا، كيف كان يومك؟'])
def test_multilingual_chat_preserves_text_and_language_instruction(client, content):
    from app.providers import Reply
    login(client); cid = companion(client)
    prompts = []
    def complete(messages):
        prompts.extend(messages)
        return Reply(content, 20)
    client.app.state.provider.complete = complete
    response = send(client, cid, content=content)
    assert response.status_code == 200
    assert response.json()['reply'] == content
    assert prompts[-1]['content'] == content
    assert 'language of the latest user message' in prompts[0]['content']
    assert 'English interface and profile do not determine the reply language' in prompts[0]['content']
    stored = client.get(f'/v1/companions/{cid}/messages').json()
    assert [item['content'] for item in stored] == [content, content]

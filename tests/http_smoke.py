"""Exercise the built Next proxy + actual API without browser dependencies."""
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import httpx

origin = 'http://localhost:3000'
with httpx.Client(base_url=origin, headers={'Origin':origin}, timeout=30, trust_env=False) as client:
    home = client.get('/')
    assert home.status_code == 200 and 'Near' in home.text
    email = f'smoke-{time.time_ns()}@example.com'
    request = client.post('/v1/auth/email/request',json={'email':email})
    assert request.status_code == 200, request.text
    login = client.post('/v1/auth/email/verify',json={'email':email,'code':request.json()['development_code']})
    assert login.status_code == 200, login.text
    client.headers['X-CSRF-Token'] = login.json()['csrf']
    companion = client.post('/v1/companions',json={'name':'小树','kind':'animal','profile':'温柔的虚构狐狸','fictional':True})
    assert companion.status_code == 201, companion.text
    cid = companion.json()['id']
    reply = client.post(f'/v1/companions/{cid}/messages?stream=true',json={'content':'今天很开心','request_id':'http-smoke-001'})
    assert reply.status_code == 200 and '"type": "done"' in reply.text, reply.text
    messages = client.get(f'/v1/companions/{cid}/messages').json()
    assert len(messages) == 2
    result = client.post(f'/v1/companions/{cid}/memories',json={'source_message_id':messages[0]['id'],'consent':True})
    assert result.status_code == 201
    assert len(client.get(f'/v1/companions/{cid}/memories').json()) == 1
    cursor = client.get('/v1/sync/events').json()['cursor']
    connected = threading.Event()
    def second_device():
        with httpx.Client(base_url=origin,cookies=client.cookies,timeout=10,trust_env=False) as device:
            with device.stream('GET',f'/v1/sync/stream?after={cursor}') as stream:
                assert stream.status_code == 200
                connected.set()
                for line in stream.iter_lines():
                    if line.startswith('data: '):
                        return json.loads(line[6:])
        raise AssertionError('No cross-device event received')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pushed=pool.submit(second_device)
        assert connected.wait(5)
        assert client.post(f'/v1/companions/{cid}/messages',json={'content':'同步测试','request_id':'http-smoke-002'}).status_code==200
        assert any(event['kind']=='message.created' for event in pushed.result(timeout=10)['events'])
    assert client.post(f'/v1/companions/{cid}/portraits').status_code==503
    assert client.get('/v1/companions').json()[0]['portrait_count']==0
    assert client.patch(f'/v1/messages/{messages[0]["id"]}/archive',json={'archived':True}).status_code==200
    assert len(client.get(f'/v1/companions/{cid}/archive').json())==1
    assert client.get(f'/v1/companions/{cid}/memories').json()==[]
    assert len(client.get('/v1/account/export').json()['messages'])==4
    assert len(client.post(f'/v1/companions/{cid}/choices',json={'request_id':'http-choice-001'}).json()['choices'])==3
    assert client.get('/v1/usage').status_code==200
    assert client.post('/v1/auth/logout').status_code == 200
    assert client.get('/v1/me').status_code == 401
print('PASS: built web page, proxy, OTP, companion, SSE chat, live second-device push, memory, archive/export, choices, disabled portraits, usage, logout')

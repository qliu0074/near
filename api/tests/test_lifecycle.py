import json
import time
from dataclasses import replace
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from test_api import client, login, companion, send
from app.models import User, SiteBudget, Operation, Message, Memory, Outbox, Call
from app.billing import metered
from app.admin import reconcile
from app.worker import process_outbox, purge_expired
from app.providers import Reply
from app.main import create_app
from fastapi.testclient import TestClient
from app.search import Search


def test_archive_restore_and_source_memory_privacy(client):
    login(client); cid=companion(client); send(client,cid)
    message=client.get(f'/v1/companions/{cid}/messages').json()[0]
    client.post(f'/v1/companions/{cid}/memories',json={'source_message_id':message['id'],'consent':True})
    assert client.patch(f'/v1/messages/{message["id"]}/archive',json={'archived':True}).status_code==200
    assert len(client.get(f'/v1/companions/{cid}/messages').json())==1
    assert client.get(f'/v1/companions/{cid}/memories').json()==[]
    with client.app.state.db.begin() as db:
        db.execute(update(Message).values(expires=time.time()-1))
    purge_expired(client.app.state.db)
    assert len(client.get(f'/v1/companions/{cid}/archive').json())==1
    assert client.patch(f'/v1/messages/{message["id"]}/archive',json={'archived':False}).status_code==200
    assert len(client.get(f'/v1/companions/{cid}/messages').json())==1


def test_profile_optimistic_version(client):
    login(client); cid=companion(client)
    data={'name':'新名字','profile':'原创森林管理员','version':1,'fictional':True}
    assert client.patch(f'/v1/companions/{cid}',json=data).json()['version']==2
    assert client.patch(f'/v1/companions/{cid}',json=data).status_code==409
    assert client.get('/v1/companions').json()[0]['profile']=='原创森林管理员'


def test_account_export_delete_and_durable_search_tombstone(client):
    login(client); cid=companion(client); send(client,cid)
    mid=client.get(f'/v1/companions/{cid}/messages').json()[0]['id']
    client.post(f'/v1/companions/{cid}/memories',json={'source_message_id':mid,'consent':True})
    assert len(client.get('/v1/account/export').json()['memories'])==1
    assert client.request('DELETE','/v1/account',json={'confirm_email':'wrong@example.com'}).status_code==422
    assert client.request('DELETE','/v1/account',json={'confirm_email':'one@example.com'}).status_code==200
    assert client.get('/v1/me').status_code==401
    with client.app.state.db() as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(Message)) is None
        assert db.scalar(select(Memory)) is None
        tombstone=json.loads(db.scalar(select(Outbox.payload).where(Outbox.payload!='')))
        assert tombstone['deleted'] and tombstone['content']==''
        assert db.get(SiteBudget,1).used>0
    indexed=[]
    class Index:
        def index(self,*args): indexed.append(args)
    process_outbox(client.app.state.db,client.app.state.settings,None,Index())
    assert len(indexed)==1 and indexed[0][1]['deleted']


def test_metered_embedding_cache_and_global_budget(client):
    login(client); cid=companion(client)
    factory=client.app.state.db
    with factory() as db: owner=db.scalar(select(User.id))
    calls=[]
    def invoke(): calls.append(True); return [1.,0.],7
    for _ in range(2):
        assert metered(factory,client.app.state.settings,owner,cid,'embedding','same-key',100,invoke)==[1.,0.]
    assert len(calls)==1
    assert client.get('/v1/me').json()['used']==7
    with factory() as db:
        assert db.get(SiteBudget,1).used==7 and db.get(SiteBudget,1).reserved==0
    with pytest.raises(HTTPException) as error:
        metered(factory,replace(client.app.state.settings,site_token_limit=8),owner,cid,'embedding','new-key',100,invoke)
    assert error.value.status_code==429 and len(calls)==1
    assert client.get('/v1/me').json()['reserved']==0


def test_uncertain_embedding_reconcile_once(client):
    login(client); cid=companion(client)
    factory=client.app.state.db
    with factory() as db: owner=db.scalar(select(User.id))
    def broken(): raise TimeoutError('secret detail')
    with pytest.raises(HTTPException):
        metered(factory,client.app.state.settings,owner,cid,'embedding','uncertain',100,broken)
    with factory() as db: operation_id=db.scalar(select(Operation.id))
    assert client.get('/v1/me').json()['reserved']==100
    reconcile(factory,operation_id,12,'test-provider-billing-reference')
    assert client.get('/v1/me').json()['reserved']==0
    assert client.get('/v1/me').json()['used']==12
    with pytest.raises(ValueError): reconcile(factory,operation_id,12,'duplicate')


def test_worker_vectors_charged_once_and_deletion_never_embedded(client):
    login(client); cid=companion(client); send(client,cid)
    mid=client.get(f'/v1/companions/{cid}/messages').json()[0]['id']
    memory=client.post(f'/v1/companions/{cid}/memories',json={'source_message_id':mid,'consent':True}).json()['id']
    factory=client.app.state.db; indexed=[]; calls=[]
    class Embedding:
        def embed_with_usage(self,text): calls.append(text); return [1.,0.],3
    class Index:
        def index(self,*args): indexed.append(args)
    config=replace(client.app.state.settings,provider='qwen',embedding_dims=2)
    process_outbox(factory,config,Embedding(),Index())
    with factory.begin() as db: db.add(Outbox(memory=memory))
    process_outbox(factory,config,Embedding(),Index())
    assert len(calls)==1 and indexed[0][1]['embedding']==[1.,0.]
    assert client.delete(f'/v1/memories/{memory}').status_code==200
    process_outbox(factory,config,Embedding(),Index())
    assert len(calls)==1 and indexed[-1][1]['deleted']
    assert 'embedding' not in indexed[-1][1]


def test_chat_hybrid_uses_query_vector_and_rechecks_ownership(client,monkeypatch):
    login(client); cid=companion(client); send(client,cid)
    mid=client.get(f'/v1/companions/{cid}/messages').json()[0]['id']
    memory=client.post(f'/v1/companions/{cid}/memories',json={'source_message_id':mid,'consent':True}).json()['id']
    vectors=[]; prompts=[]; embeddings=[]
    def retrieve(self,owner,cid,query,vector): vectors.append(vector);return [memory,'foreign-memory']
    monkeypatch.setattr(Search,'retrieve',retrieve)
    settings=replace(client.app.state.settings,provider='qwen',es_url='http://search.invalid',
        qwen_url='https://provider.invalid/v1',qwen_key='test-only-placeholder')
    app=create_app(settings)
    class Provider:
        def embed_with_usage(self,text): embeddings.append(text);return [1.,0.],4
        def complete(self,messages): prompts.append(messages);return Reply('测试回复',9)
    app.state.provider=Provider()
    before=client.get('/v1/me').json()['used']
    with TestClient(app,headers=dict(client.headers),cookies=client.cookies) as second:
        assert send(second,cid,key='hybrid-0001').status_code==200
        assert send(second,cid,key='hybrid-0001').json()['replayed']
        assert second.get('/v1/me').json()['used']==before+13
        assert second.post(f'/v1/companions/{cid}/messages',json={'content':'快一点','request_id':'fast-0001','mode':'fast'}).status_code==200
    assert len(embeddings)==1 and vectors==[[1.,0.]]
    assert '今天很开心' in prompts[0][0]['content']
    assert 'MEMORY DATA: []' in prompts[1][0]['content']


def test_smtp_delivery_does_not_return_code(client,monkeypatch):
    sent=[]
    class SMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def ehlo(self): pass
        def starttls(self,**kwargs): pass
        def send_message(self,message): sent.append(message)
    monkeypatch.setattr('app.mailer.smtplib.SMTP',SMTP)
    app=create_app(replace(client.app.state.settings,email_mode='smtp',smtp_host='mail.invalid',smtp_from='near@example.com',smtp_user=''))
    with TestClient(app,headers=dict(client.headers)) as second:
        response=second.post('/v1/auth/email/request',json={'email':'mail@example.com'})
    assert response.status_code==200 and 'development_code' not in response.json()
    assert len(sent)==1 and sent[0]['To']=='mail@example.com'
    assert sent[0]['Subject'] == 'Your Near sign-in code'
    assert sent[0].get_content().isascii()


def test_choices_and_companion_deletion(client):
    login(client); cid=companion(client); send(client,cid)
    choices = client.post(f'/v1/companions/{cid}/choices',json={'request_id':'choices-0001'}).json()['choices']
    assert len(choices) == 3 and all(choice.isascii() for choice in choices)
    assert client.delete(f'/v1/companions/{cid}').status_code==200
    assert client.get('/v1/companions').json()==[]
    assert client.get(f'/v1/companions/{cid}/messages').status_code==404
    assert any(e['kind']=='companion.deleted' for e in client.get('/v1/sync/events').json()['events'])


def test_equal_timestamp_pagination_has_no_gaps(client):
    login(client); cid=companion(client)
    with client.app.state.db.begin() as db:
        owner=db.scalar(select(User.id))
        for index in range(60):
            db.add(Message(id=f'{index:036}',owner=owner,companion=cid,role='user',content=str(index),created=1000))
    page=client.get(f'/v1/companions/{cid}/messages').json()
    older=client.get(f'/v1/companions/{cid}/messages',params={'before':page[0]['created'],'before_id':page[0]['id']}).json()
    assert len(page)==50 and len(older)==10
    assert len({m['id'] for m in page+older})==60

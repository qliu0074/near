import hashlib
import hmac
import asyncio
import anyio
from starlette.concurrency import run_in_threadpool, iterate_in_threadpool
from contextlib import aclosing
from .concurrency import ConcurrencyLimit, ClosingStreamingResponse
import json
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select, update, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from .config import Settings
from .models import Base, User, Session, LoginCode, Companion, Message, Memory, Call, Event, Outbox, SiteBudget, RateBucket, Operation
from .providers import Provider, Reply, estimate_input
from .search import Search
from . import billing
from .mailer import deliver
from .retrieval import query_embedding
from .failures import NotStarted, report
from .prompts import chat_system_prompt


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class EmailInput(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class CodeInput(EmailInput):
    code: str = Field(pattern=r'^\d{6}$')


class CompanionInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['human', 'animal']
    profile: str = Field(min_length=1, max_length=2000)
    fictional: Literal[True]


class ChatInput(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    mode: Literal['fast', 'normal'] = 'normal'


class MemoryInput(BaseModel):
    source_message_id: str
    consent: Literal[True]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.validate()
    engine = create_engine(settings.database_url,
        connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite') else {},
        pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_schema:
            Base.metadata.create_all(engine)
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = sqlite_insert if engine.dialect.name == 'sqlite' else pg_insert
        with factory.begin() as db:
            db.execute(insert(SiteBudget).values(id=1, used=0, reserved=0).on_conflict_do_nothing())
        yield
        engine.dispose()

    app = FastAPI(title='Near Companion API', lifespan=lifespan,
                  docs_url='/docs' if settings.environment == 'development' else None,
                  redoc_url=None, openapi_url='/openapi.json' if settings.environment == 'development' else None)
    app.state.db = factory
    app.state.provider = Provider(settings)
    app.state.settings = settings

    def code_digest(email: str, code: str) -> str:
        return hmac.new((settings.auth_secret or 'development-only').encode(),
                        f'{email}:{code}'.encode(), hashlib.sha256).hexdigest()

    def rate_limit(request: Request, category: str, limit: int):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = sqlite_insert if engine.dialect.name == 'sqlite' else pg_insert
        # Never trust client-provided X-Forwarded-For without a configured trusted proxy.
        key = digest(f'{category}:{request.client.host if request.client else "unknown"}:{int(time.time()//60)}')
        with factory.begin() as db:
            db.execute(insert(RateBucket).values(id=key, count=0, expires=time.time()+120).on_conflict_do_nothing())
            changed = db.execute(update(RateBucket).where(RateBucket.id == key,
                RateBucket.count < limit).values(count=RateBucket.count+1)).rowcount
            if not changed:
                raise HTTPException(429, 'Too many authentication requests')

    @app.middleware('http')
    async def guard(request: Request, call_next):
        length = request.headers.get('content-length', '0')
        if not length.isdigit() or int(length) > 32768:
            return Response('Request too large', status_code=413)
        if request.method in {'POST', 'PATCH', 'DELETE', 'PUT'}:
            if request.headers.get('origin') != settings.origin:
                return Response('Invalid origin', status_code=403)
            # Bound streamed/chunked bodies too; Content-Length alone is insufficient.
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 32768:
                    return Response('Request too large', status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store, no-transform'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def authenticated(request: Request) -> str:
        token = request.cookies.get('near_session', '')
        with factory() as db:
            session = db.get(Session, digest(token))
            if not session or session.expires < time.time():
                raise HTTPException(401, 'Please sign in')
            if request.method not in {'GET', 'HEAD'} and not secrets.compare_digest(
                request.headers.get('x-csrf-token', ''), session.csrf):
                raise HTTPException(403, 'Invalid CSRF token')
            return session.owner

    def companion_for(db, owner: str, companion_id: str) -> Companion:
        companion = db.get(Companion, companion_id)
        if not companion or companion.owner != owner:
            raise HTTPException(404, 'Companion not found')
        return companion

    def emit(db, owner: str, kind: str, entity: str):
        # Serialize per-owner event insertion/commit to prevent cursor gaps across replicas.
        db.scalar(select(User).where(User.id == owner).with_for_update())
        db.add(Event(owner=owner, kind=kind, entity=entity))

    @app.get('/v1/health')
    def health():
        return {'status': 'ok', 'provider': settings.provider, 'development_only': settings.environment == 'development'}

    @app.get('/v1/ready')
    def ready():
        try:
            with factory() as db:
                db.execute(text('SELECT 1'))
                if db.get(SiteBudget, 1) is None:
                    raise RuntimeError('Missing budget initialization')
        except Exception:
            return Response('Not ready', status_code=503)
        return {'status': 'ready'}

    @app.post('/v1/auth/email/request')
    def request_code(body: EmailInput, request: Request):
        rate_limit(request, 'send-code', 5)
        email = body.email.strip().lower()
        code = str(secrets.randbelow(900000) + 100000)
        now = time.time()
        with factory.begin() as db:
            previous = db.get(LoginCode, email)
            if previous and previous.issued > now - 60:
                raise HTTPException(429, 'Wait 60 seconds before requesting another code')
            if previous:
                previous.digest, previous.expires, previous.issued, previous.attempts = code_digest(email, code), now + 600, now, 0
            else:
                db.add(LoginCode(email=email, digest=code_digest(email, code), expires=now + 600, issued=now))
        try:
            return deliver(settings, email, code)
        except Exception as error:
            reference = secrets.token_hex(8)
            report('email_delivery_failed', reference, error)
            raise HTTPException(503, f'Email delivery unavailable; please retry after one minute. Reference: {reference}') from None

    @app.post('/v1/auth/email/verify')
    def verify(body: CodeInput, response: Response, request: Request):
        rate_limit(request, 'verify-code', 20)
        email = body.email.strip().lower()
        with factory.begin() as db:
            incremented = db.execute(update(LoginCode).where(LoginCode.email == email,
                LoginCode.expires > time.time(), LoginCode.attempts < 5)
                .values(attempts=LoginCode.attempts + 1)).rowcount
            entry = db.get(LoginCode, email)
            valid = bool(incremented and entry and secrets.compare_digest(entry.digest, code_digest(email, body.code)))
            if valid:
                consumed = db.execute(delete(LoginCode).where(LoginCode.email == email,
                    LoginCode.digest == code_digest(email, body.code))).rowcount
                valid = consumed == 1
            if valid:
                user = db.scalar(select(User).where(User.email == email))
                if not user:
                    user = User(email=email)
                    db.add(user)
                    db.flush()
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.add(Session(digest=digest(token), owner=user.id, csrf=csrf, expires=time.time() + 86400 * 7))
        if not valid:
            raise HTTPException(400, 'Invalid or expired code')
        response.set_cookie('near_session', token, httponly=True, samesite='strict',
                            secure=settings.origin.startswith('https://'), max_age=86400 * 7, path='/')
        return {'csrf': csrf, 'email': email}

    @app.get('/v1/me')
    def me(request: Request, owner: str = Depends(authenticated)):
        with factory() as db:
            user = db.get(User, owner)
            session = db.get(Session, digest(request.cookies['near_session']))
            return {'email': user.email, 'csrf': session.csrf, 'used': user.used,
                'reserved': user.reserved, 'available': max(0, settings.token_limit-user.used-user.reserved),
                'provider': settings.provider, 'quota_period': 'lifetime', 'portraits_enabled': False,
                'email_mode': settings.email_mode, 'hybrid_enabled': bool(settings.es_url and settings.embedding_model)}

    @app.post('/v1/auth/logout')
    def logout(request: Request, response: Response, all_devices: bool = False, owner: str = Depends(authenticated)):
        with factory.begin() as db:
            statement = delete(Session).where(Session.owner == owner)
            if not all_devices:
                statement = statement.where(Session.digest == digest(request.cookies['near_session']))
            db.execute(statement)
        response.delete_cookie('near_session', path='/')
        return {'ok': True}

    @app.get('/v1/companions')
    def companions(owner: str = Depends(authenticated)):
        with factory() as db:
            return [{'id': c.id, 'name': c.name, 'kind': c.kind, 'profile': c.profile,
                     'portrait_count': c.portrait_count, 'version': c.version} for c in db.scalars(
                         select(Companion).where(Companion.owner == owner).order_by(Companion.id))]

    @app.post('/v1/companions', status_code=201)
    def create_companion(body: CompanionInput, owner: str = Depends(authenticated)):
        if not body.name.strip() or not body.profile.strip():
            raise HTTPException(422, 'Name and profile cannot be blank')
        from .lifecycle import generate_profile
        profile = generate_profile(factory, settings, app.state.provider, owner, body.name, body.kind, body.profile)
        with factory.begin() as db:
            user = db.scalar(select(User).where(User.id == owner).with_for_update())
            if db.scalar(select(func.count()).select_from(Companion).where(Companion.owner == user.id)) >= 20:
                raise HTTPException(409, 'Development companion limit reached')
            companion = Companion(owner=owner, name=body.name.strip(), kind=body.kind, profile=profile)
            db.add(companion)
            db.flush()
            emit(db, owner, 'companion.created', companion.id)
            return {'id': companion.id}

    @app.get('/v1/companions/{cid}/messages')
    def messages(cid: str, before: float | None = None, before_id: str = '', owner: str = Depends(authenticated)):
        with factory() as db:
            companion_for(db, owner, cid)
            statement = select(Message).where(Message.owner == owner, Message.companion == cid,
                Message.expires > time.time(), Message.archived.is_(False))
            if before is not None:
                from sqlalchemy import or_, and_
                statement = statement.where(or_(Message.created < before,
                    and_(Message.created == before, Message.id < before_id)))
            rows = list(db.scalars(statement.order_by(Message.created.desc(), Message.id.desc()).limit(50)))
            return [{'id': m.id, 'role': m.role, 'content': m.content, 'created': m.created} for m in reversed(rows)]

    @app.post('/v1/companions/{cid}/messages')
    def chat(cid: str, body: ChatInput, stream: bool = False, owner: str = Depends(authenticated)):
        if not body.content.strip():
            raise HTTPException(422, 'Message cannot be blank')
        fingerprint = digest(cid + '\n' + body.mode + '\n' + body.content)
        with factory() as db:
            companion = companion_for(db, owner, cid)
            existing = db.scalar(select(Call).where(Call.owner == owner, Call.key == body.request_id))
            if existing:
                if existing.fingerprint != fingerprint:
                    raise HTTPException(409, 'Idempotency key belongs to a different request')
                if existing.status == 'complete':
                    if stream:
                        payload = json.dumps({'type': 'done', 'reply': existing.reply, 'replayed': True}, ensure_ascii=False)
                        return StreamingResponse(iter([f'data: {payload}\n\n']), media_type='text/event-stream')
                    return {'reply': existing.reply, 'replayed': True}
                if existing.status == 'failed':
                    raise HTTPException(409, 'Previous request was rejected without usage. Submit a new request.')
                raise HTTPException(409, f'Request pending or uncertain; do not resubmit with a new key. Reference: {existing.id}')
            history = list(db.scalars(select(Message).where(Message.companion == cid, Message.owner == owner,
                Message.expires > time.time(), Message.archived.is_(False))
                .order_by(Message.created.desc(), Message.id.desc()).limit(4 if body.mode == 'fast' else 12)))
            memory_rows = []
            memory_unavailable = False
            if settings.es_url and body.mode != 'fast':
                try:
                    vector = query_embedding(factory, settings, app.state.provider, owner, cid, body.content, body.request_id)
                    ids = Search(settings).retrieve(owner, cid, body.content, vector)
                    memory_rows = list(db.scalars(select(Memory).where(Memory.id.in_(ids),
                        Memory.owner == owner, Memory.companion == cid, Memory.deleted.is_(False))))
                    memory_rows.sort(key=lambda memory: ids.index(memory.id))
                except HTTPException:
                    raise
                except Exception as error:
                    memory_unavailable = True
                    report('memory_unavailable', body.request_id, error)
                    # ES entirely unavailable: no memory, NOT fictitious BM25 fallback.
                    memory_rows = []
            prompt = [{'role': 'system', 'content': chat_system_prompt(
                companion.name, companion.profile, [m.content[:400] for m in memory_rows[:5]])}]
            prompt.extend({'role': m.role, 'content': m.content[:600]} for m in reversed(history))
            prompt.append({'role': 'user', 'content': body.content})
        reservation = estimate_input(prompt) + settings.max_output
        if reservation > 24000:
            raise HTTPException(413, 'Context budget exceeded')
        try:
            with factory.begin() as db:
                # Atomic update serializes admission across devices and API replicas.
                billing.reserve(db, settings, owner, reservation)
                current = companion_for(db, owner, cid)
                if current.version != companion.version:
                    raise HTTPException(409, 'Profile changed while preparing reply; please retry')
                for previous in history:
                    fresh = db.get(Message, previous.id)
                    if not fresh or fresh.archived or fresh.expires <= time.time():
                        raise HTTPException(409, 'Conversation changed while preparing reply; please retry')
                for previous in memory_rows:
                    fresh = db.get(Memory, previous.id)
                    if not fresh or fresh.deleted or fresh.version != previous.version:
                        raise HTTPException(409, 'Memory changed while preparing reply; please retry')
                if db.scalar(select(func.count()).select_from(Call).where(Call.owner == owner,
                    Call.created > time.time()-60)) >= 10:
                    raise HTTPException(429, 'Maximum 10 chat calls per minute')
                call = Call(owner=owner, companion=cid, key=body.request_id, fingerprint=fingerprint, reserved=reservation)
                db.add(call)
                db.flush()
                call_id = call.id
        except IntegrityError:
            raise HTTPException(409, 'Duplicate request')
        def uncertain():
            billing.close_failure(factory, Call, call_id)

        def finish(reply: Reply):
            with factory.begin() as db:
                db.scalar(select(SiteBudget).where(SiteBudget.id == 1).with_for_update())
                record = db.scalar(select(Call).where(Call.id == call_id).with_for_update())
                if not record or record.status != 'pending':
                    raise ValueError('Request already reconciled or closed')
                billing.settle(db, owner, reservation, reply.tokens)
                db.execute(update(Call).where(Call.id == call_id).values(status='complete', actual=reply.tokens, reply=reply.text))
                for role, content in [('user', body.content), ('assistant', reply.text)]:
                    message = Message(owner=owner, companion=cid, role=role, content=content)
                    db.add(message)
                    db.flush()
                    emit(db, owner, 'message.created', message.id)

        if stream:
            async def events():
                completed = False
                try:
                    if memory_unavailable:
                        yield 'data: ' + json.dumps({'type': 'warning', 'message': 'Long-term memory is temporarily unavailable. This reply uses your profile and recent chat only.'}) + '\n\n'
                    provider = app.state.provider
                    source = (provider.astream(prompt) if hasattr(provider, 'astream')
                              else iterate_in_threadpool(provider.stream(prompt)))
                    deadline = time.monotonic() + settings.stream_timeout
                    async with aclosing(source):
                        while True:
                            try:
                                part = await asyncio.wait_for(anext(source), max(0, deadline - time.monotonic()))
                            except StopAsyncIteration:
                                break
                            if isinstance(part, Reply):
                                await run_in_threadpool(finish, part)
                                completed = True
                                event = {'type': 'done', 'reply': part.text, 'replayed': False}
                            else:
                                event = {'type': 'delta', 'text': part}
                            yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
                    if not completed:
                        raise ValueError('Missing final usage')
                except NotStarted as error:
                    await run_in_threadpool(billing.close_failure, factory, Call, call_id, safe=True)
                    report('chat_rejected', call_id, error)
                    yield 'data: ' + json.dumps({'type': 'error', 'safe_to_retry': True, 'message': f'{error} No usage reserved. Reference: {call_id}'}) + '\n\n'
                except Exception as error:
                    report('chat_uncertain', call_id, error)
                    yield 'data: ' + json.dumps({'type': 'error', 'message': f'Response incomplete; budget retained for reconciliation. Reference: {call_id}'}) + '\n\n'
                finally:
                    if not completed:
                        with anyio.CancelScope(shield=True):
                            await run_in_threadpool(uncertain)
            return ClosingStreamingResponse(events(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
        try:
            reply = app.state.provider.complete(prompt)
            finish(reply)
        except NotStarted as error:
            billing.close_failure(factory, Call, call_id, safe=True)
            report('chat_rejected', call_id, error)
            raise HTTPException(503, f'{error} No usage reserved. Reference: {call_id}') from None
        except Exception as error:
            uncertain()
            report('chat_uncertain', call_id, error)
            raise HTTPException(502, f'Provider outcome uncertain; reservation retained for reconciliation. Reference: {call_id}') from None
        return {'reply': reply.text, 'replayed': False, 'memory_unavailable': memory_unavailable}

    @app.get('/v1/companions/{cid}/memories')
    def memories(cid: str, owner: str = Depends(authenticated)):
        with factory() as db:
            companion_for(db, owner, cid)
            return [{'id': m.id, 'content': m.content, 'source': m.source} for m in db.scalars(
                select(Memory).where(Memory.owner == owner, Memory.companion == cid, Memory.deleted.is_(False)))]

    @app.post('/v1/companions/{cid}/memories', status_code=201)
    def save_memory(cid: str, body: MemoryInput, owner: str = Depends(authenticated)):
        with factory.begin() as db:
            db.scalar(select(User).where(User.id == owner).with_for_update())
            companion_for(db, owner, cid)
            message = db.get(Message, body.source_message_id)
            if not message or message.owner != owner or message.companion != cid or message.archived or message.expires < time.time():
                raise HTTPException(404, 'Source not found')
            memory = db.scalar(select(Memory).where(Memory.owner == owner, Memory.source == message.id))
            if memory:
                if memory.deleted:
                    memory.deleted, memory.content, memory.version = False, message.content, memory.version + 1
            else:
                memory = Memory(owner=owner, companion=cid, source=message.id, content=message.content)
                db.add(memory)
            db.flush()
            db.add(Outbox(memory=memory.id))
            emit(db, owner, 'memory.changed', memory.id)
            return {'id': memory.id}

    @app.delete('/v1/memories/{mid}')
    def remove_memory(mid: str, owner: str = Depends(authenticated)):
        with factory.begin() as db:
            user = db.scalar(select(User).where(User.id == owner).with_for_update())
            if user.reserved:
                raise HTTPException(409, 'Wait for active or uncertain paid requests before deletion')
            memory = db.get(Memory, mid)
            if not memory or memory.owner != owner:
                raise HTTPException(404, 'Memory not found')
            memory.deleted, memory.content, memory.version = True, '', memory.version + 1
            db.execute(update(Operation).where(Operation.owner == owner, Operation.companion == memory.companion,
                Operation.status == 'complete').values(result='', status='redacted'))
            db.add(Outbox(memory=mid))
            emit(db, owner, 'memory.deleted', mid)
        return {'ok': True}

    @app.delete('/v1/messages/{mid}')
    def remove_message(mid: str, owner: str = Depends(authenticated)):
        with factory.begin() as db:
            user = db.scalar(select(User).where(User.id == owner).with_for_update())
            if user.reserved:
                raise HTTPException(409, 'Wait for active or uncertain paid requests before deletion')
            message = db.get(Message, mid)
            if not message or message.owner != owner:
                raise HTTPException(404, 'Message not found')
            for memory in db.scalars(select(Memory).where(Memory.owner == owner, Memory.source == mid)):
                memory.deleted, memory.content, memory.version = True, '', memory.version + 1
                db.add(Outbox(memory=memory.id))
            # Erase replay payloads as well; retain billing metadata.
            db.execute(update(Call).where(Call.owner == owner, Call.companion == message.companion,
                Call.status == 'complete').values(reply='', status='redacted'))
            db.execute(update(Operation).where(Operation.owner == owner, Operation.companion == message.companion,
                Operation.status == 'complete').values(result='', status='redacted'))
            db.delete(message)
            emit(db, owner, 'message.deleted', mid)
        return {'ok': True}

    @app.post('/v1/companions/{cid}/portraits')
    def portrait(cid: str, owner: str = Depends(authenticated)):
        with factory() as db:
            companion_for(db, owner, cid)
        raise HTTPException(503, 'Portrait generation is not configured; no quota consumed')

    @app.get('/v1/sync/events')
    def events(request: Request, after: int = 0, owner: str = Depends(authenticated)):
        if after < 0:
            raise HTTPException(422, 'Invalid cursor')
        with factory() as db:
            rows = list(db.scalars(select(Event).where(Event.owner == owner, Event.id > after)
                .order_by(Event.id).limit(100)))
        return {'events': [{'id': e.id, 'kind': e.kind, 'entity': e.entity} for e in rows],
                'cursor': rows[-1].id if rows else after, 'has_more': len(rows) == 100}

    @app.get('/v1/sync/stream')
    def event_stream(request: Request, after: int = 0, owner: str = Depends(authenticated)):
        try:
            cursor = max(after, int(request.headers.get('last-event-id', '0')))
            if cursor < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Invalid event cursor')
        session_hash = digest(request.cookies.get('near_session', ''))
        def snapshot(since):
            with factory() as db:
                session = db.get(Session, session_hash)
                if not session or session.expires < time.time():
                    return None
                return [{'id':e.id,'kind':e.kind,'entity':e.entity} for e in db.scalars(
                    select(Event).where(Event.owner == owner, Event.id > since).order_by(Event.id).limit(100))]
        async def generate():
            nonlocal cursor
            for _ in range(60):
                if await request.is_disconnected():
                    break
                rows = await asyncio.to_thread(snapshot, cursor)
                if rows is None:
                    yield 'event: revoked\ndata: {}\n\n'
                    break
                if rows:
                    cursor = rows[-1]['id']
                    yield f'id: {cursor}\ndata: ' + json.dumps({'events':rows,'cursor':cursor}) + '\n\n'
                else:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type='text/event-stream', headers={'X-Accel-Buffering':'no'})

    from .lifecycle import register_lifecycle
    register_lifecycle(app, factory, settings, authenticated, companion_for, emit)
    app.add_middleware(ConcurrencyLimit, limit=settings.max_concurrent_requests)
    return app


app = create_app()

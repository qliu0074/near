"""Leased outbox delivery with metered, idempotent embedding calls."""
import json
import time
from celery import Celery
from sqlalchemy import create_engine, select, delete, update
from sqlalchemy.orm import sessionmaker
from .config import Settings
from .models import Outbox, Memory, Message, Call, Event, LoginCode, Session, User, Operation, RateBucket
from .providers import Provider
from .retrieval import embedding
from .search import Search
from .failures import report

settings = Settings()
celery = Celery('near', broker=settings.redis_url)
celery.conf.update(task_serializer='json', accept_content=['json'], result_serializer='json',
    task_acks_late=True, worker_prefetch_multiplier=1,
    beat_schedule={'outbox': {'task': 'near.sync', 'schedule': 10.0},
                   'retention': {'task': 'near.retention', 'schedule': 300.0}})
factory = sessionmaker(create_engine(settings.database_url, pool_pre_ping=True), expire_on_commit=False)


def process_outbox(db_factory, config, provider, search):
    with db_factory() as db:
        ids = list(db.scalars(select(Outbox.id).where(Outbox.done.is_(False),
            Outbox.available <= time.time(), Outbox.attempts < 10).order_by(Outbox.id).limit(30)))
    for job_id in ids:
        with db_factory.begin() as db:
            claimed = db.execute(update(Outbox).where(Outbox.id == job_id, Outbox.done.is_(False),
                Outbox.available <= time.time()).values(available=time.time()+120)).rowcount
            if not claimed:
                continue
            job = db.get(Outbox, job_id)
            memory = db.get(Memory, job.memory)
            memory_id = job.memory
            if job.payload:
                document = json.loads(job.payload)
            elif memory:
                document = {'owner':memory.owner,'companion':memory.companion,'content':memory.content,
                            'deleted':memory.deleted,'version':memory.version}
            else:
                job.done = True
                continue
        try:
            if not document['deleted'] and config.provider == 'qwen':
                document['embedding'] = embedding(db_factory,config,provider,document['owner'],document['companion'],
                    document['content'],f'memory:{memory_id}:{document["version"]}')
                document['embedding_model'] = config.embedding_model
            with db_factory() as db:
                current = db.get(Memory,memory_id)
                if not document['deleted'] and (not current or current.deleted or current.version != document['version']):
                    document = {**document,'content':'','deleted':True}
                    document.pop('embedding',None)
            search.index(memory_id,document,document['version'])
            with db_factory.begin() as db:
                db.execute(update(Outbox).where(Outbox.id==job_id).values(done=True))
        except Exception as error:
            report('memory_sync_failed', job_id, error)
            with db_factory.begin() as db:
                job = db.get(Outbox,job_id)
                if job:
                    job.attempts += 1
                    if job.attempts == 10:
                        report('memory_sync_paused', job_id, error)
                    elif job.attempts == 5:
                        report('memory_sync_needs_attention', job_id, error)
                    job.available = time.time()+min(3600,2**min(job.attempts,12))


@celery.task(name='near.sync')
def sync():
    if settings.es_url:
        process_outbox(factory,settings,Provider(settings),Search(settings))


def purge_expired(db_factory):
    with db_factory.begin() as db:
        expired = list(db.scalars(select(Message).where(Message.expires < time.time(), Message.archived.is_(False)).order_by(Message.owner).limit(1000)))
        for message in expired:
            # Explicitly promoted memories survive automatic expiry, but not explicit deletion.
            db.scalar(select(User).where(User.id == message.owner).with_for_update())
            db.add(Event(owner=message.owner, kind='message.expired', entity=message.id))
            db.delete(message)
        db.execute(update(Call).where(Call.created < time.time()-259200,
            Call.status == 'complete').values(reply='', status='redacted'))
        db.execute(update(Operation).where(Operation.created < time.time()-259200,
            Operation.status == 'complete').values(result='',status='redacted'))
        db.execute(delete(LoginCode).where(LoginCode.expires < time.time()))
        db.execute(delete(Session).where(Session.expires < time.time()))
        db.execute(delete(RateBucket).where(RateBucket.expires < time.time()))


@celery.task(name='near.retention')
def retention():
    purge_expired(factory)


def retry_outbox(db_factory, job_id):
    """Resume only a paused job, preserving its payload and idempotency keys."""
    with db_factory.begin() as db:
        changed = db.execute(update(Outbox).where(Outbox.id == job_id,
            Outbox.done.is_(False), Outbox.attempts >= 10)
            .values(attempts=0, available=time.time())).rowcount
        if not changed:
            raise ValueError('Job is not paused or does not exist')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['init-index','reindex','local','retry-outbox'])
    parser.add_argument('--job-id', type=int)
    args = parser.parse_args()
    if args.command == 'retry-outbox':
        if args.job_id is None:
            parser.error('retry-outbox requires --job-id from the paused-job log')
        retry_outbox(factory, args.job_id)
        print('Paused job queued again with its original payload.')
    elif args.command == 'init-index':
        Search(settings).create_index()
    elif args.command == 'local':
        if settings.environment != 'development':
            raise RuntimeError('The local worker is only for development; use Celery in production')
        try:
            while True:
                retention()
                sync()
                time.sleep(10)
        except KeyboardInterrupt:
            pass
    else:
        with factory.begin() as db:
            for memory_id in db.scalars(select(Memory.id)):
                db.add(Outbox(memory=memory_id))
        print('Reindex jobs queued')

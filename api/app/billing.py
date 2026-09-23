"""Atomic reservations shared by chat, embeddings, profile generation and story choices."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, update
from .models import SiteBudget, User, Operation
from .failures import NotStarted, report


def reserve(db, settings, owner: str, amount: int):
    site = db.execute(update(SiteBudget).where(SiteBudget.id == 1,
        SiteBudget.used + SiteBudget.reserved + amount <= settings.site_token_limit)
        .values(reserved=SiteBudget.reserved + amount)).rowcount
    if not site:
        raise HTTPException(429, 'Site token budget exhausted')
    user = db.execute(update(User).where(User.id == owner, User.reserved == 0,
        User.used + amount <= settings.token_limit).values(reserved=amount)).rowcount
    if not user:
        raise HTTPException(429, 'Insufficient budget or another paid request is active')


def settle(db, owner: str, held: int, actual: int):
    if held < 0 or actual < 0:
        raise ValueError('Negative usage')
    db.execute(update(SiteBudget).where(SiteBudget.id == 1).values(
        used=SiteBudget.used + actual, reserved=SiteBudget.reserved-held))
    db.execute(update(User).where(User.id == owner).values(
        used=User.used + actual, reserved=User.reserved-held))


def metered(factory, settings, owner: str, companion: str, purpose: str,
            key: str, amount: int, invoke):
    operation_id = hashlib.sha256(f'{owner}:{companion}:{purpose}:{key}'.encode()).hexdigest()
    with factory.begin() as db:
        db.scalar(select(SiteBudget).where(SiteBudget.id == 1).with_for_update())
        existing = db.get(Operation, operation_id)
        if existing:
            if existing.status == 'complete' and existing.result:
                return json.loads(existing.result)
            if existing.status != 'failed':
                raise HTTPException(409, f'Operation pending, expired or uncertain; reference: {operation_id}')
        reserve(db, settings, owner, amount)
        if existing:
            existing.status, existing.reserved = 'pending', amount
        else:
            db.add(Operation(id=operation_id, owner=owner, companion=companion,
                purpose=purpose, reserved=amount))
    try:
        value, actual = invoke()
        if not isinstance(actual, int) or actual < 0:
            raise ValueError('Invalid provider usage')
        with factory.begin() as db:
            db.scalar(select(SiteBudget).where(SiteBudget.id == 1).with_for_update())
            operation = db.scalar(select(Operation).where(Operation.id == operation_id).with_for_update())
            if operation.status != 'pending':
                raise ValueError('Operation status changed')
            settle(db, owner, amount, actual)
            operation.status, operation.actual, operation.result = 'complete', actual, json.dumps(value, ensure_ascii=False)
        return value
    except NotStarted as error:
        close_failure(factory, Operation, operation_id, safe=True)
        report('provider_rejected', operation_id, error)
        raise HTTPException(503, f'{error} No usage reserved. Reference: {operation_id}') from None
    except Exception as error:
        report('provider_uncertain', operation_id, error)
        with factory.begin() as db:
            db.execute(update(Operation).where(Operation.id == operation_id,
                Operation.status == 'pending').values(status='uncertain'))
        raise HTTPException(502, f'Provider result uncertain; usage reservation retained. Reference: {operation_id}') from None


def close_failure(factory, model, record_id, safe=False):
    """Serialize against completion/reconciliation; release at most once."""
    with factory.begin() as db:
        db.scalar(select(SiteBudget).where(SiteBudget.id == 1).with_for_update())
        record = db.scalar(select(model).where(model.id == record_id).with_for_update())
        if record and record.status == 'pending':
            if safe:
                settle(db, record.owner, record.reserved, 0)
            record.status = 'failed' if safe else 'uncertain'

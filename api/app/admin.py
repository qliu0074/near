"""Operator-only reconciliation; inspect provider billing and stop the affected worker first."""
import argparse
import hashlib
import json
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from .config import Settings
from .models import Call, Operation, SiteBudget
from .billing import settle


def reconcile(factory, operation_id: str, actual_tokens: int, evidence: str):
    if actual_tokens < 0 or not evidence.strip():
        raise ValueError('Nonnegative usage and a billing evidence reference are required')
    with factory.begin() as db:
        # Match budget lock ordering used by ordinary requests.
        db.scalar(select(SiteBudget).where(SiteBudget.id == 1).with_for_update())
        record = db.scalar(select(Call).where(Call.id == operation_id).with_for_update())
        if record is None:
            record = db.scalar(select(Operation).where(Operation.id == operation_id).with_for_update())
        if record is None or record.status not in {'pending', 'uncertain'}:
            raise ValueError('Only pending or uncertain operations can be reconciled')
        settle(db, record.owner, record.reserved, actual_tokens)
        record.actual, record.status = actual_tokens, 'reconciled'
        db.add(Operation(id='audit-'+hashlib.sha256(operation_id.encode()).hexdigest(),
            owner=record.owner, companion=record.companion, purpose='reconciliation', status='complete',
            reserved=0, actual=0, result=json.dumps({'operation':operation_id,'evidence':evidence})))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation_id')
    parser.add_argument('--actual-tokens',type=int,required=True)
    parser.add_argument('--evidence',required=True,help='Billing reference; never paste credentials or conversation content')
    parser.add_argument('--workers-stopped',action='store_true',required=True)
    args=parser.parse_args()
    engine=create_engine(Settings().database_url,pool_pre_ping=True)
    reconcile(sessionmaker(engine),args.operation_id,args.actual_tokens,args.evidence)
    print('Usage reconciled; the original request remains non-replayable.')

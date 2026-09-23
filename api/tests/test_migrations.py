from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_migration_preserves_existing_usage_and_adds_defaults(tmp_path,monkeypatch):
    from app import config
    from dataclasses import replace
    settings=replace(config.Settings(),database_url=f'sqlite:///{tmp_path}/migration.db')
    monkeypatch.setattr(config,'Settings',lambda:settings)
    cfg=Config('alembic.ini')
    command.upgrade(cfg,'0001')
    engine=create_engine(settings.database_url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users(id,email,used,reserved) VALUES ('owner','test@example.com',123,45)"))
        db.execute(text("INSERT INTO companions(id,owner,name,kind,profile,portrait_count) VALUES ('companion','owner','Test','human','Original',0)"))
    command.upgrade(cfg,'head')
    with engine.connect() as db:
        assert db.execute(text('SELECT used,reserved FROM site_budget WHERE id=1')).one()==(123,45)
        assert db.execute(text('SELECT version FROM companions')).scalar()==1
        assert db.execute(text('SELECT email FROM users')).scalar()=='test@example.com'
    command.check(cfg)
    engine.dispose()

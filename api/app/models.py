import time
import uuid
from sqlalchemy import String, Text, Integer, Float, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    used: Mapped[int] = mapped_column(default=0)
    reserved: Mapped[int] = mapped_column(default=0)
    __table_args__ = (CheckConstraint('used >= 0 AND reserved >= 0'),)


class LoginCode(Base):
    __tablename__ = 'login_codes'
    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(default=0)
    issued: Mapped[float] = mapped_column(Float, default=time.time)


class Session(Base):
    __tablename__ = 'sessions'
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class Companion(Base):
    __tablename__ = 'companions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    profile: Mapped[str] = mapped_column(Text)
    portrait_count: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=1, server_default='1')
    __table_args__ = (CheckConstraint('portrait_count >= 0 AND portrait_count <= 4'),)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    companion: Mapped[str] = mapped_column(ForeignKey('companions.id'), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    expires: Mapped[float] = mapped_column(Float, default=lambda: time.time() + 259200)
    archived: Mapped[bool] = mapped_column(default=False, server_default='0')


class Memory(Base):
    __tablename__ = 'memories'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    companion: Mapped[str] = mapped_column(ForeignKey('companions.id'), index=True)
    source: Mapped[str] = mapped_column(String(36), index=True)
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    deleted: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (UniqueConstraint('owner', 'source'),)


class Call(Base):
    __tablename__ = 'calls'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    companion: Mapped[str] = mapped_column(String(36))
    key: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    reserved: Mapped[int] = mapped_column(Integer)
    actual: Mapped[int] = mapped_column(default=0)
    reply: Mapped[str] = mapped_column(Text, default='')
    created: Mapped[float] = mapped_column(Float, default=time.time)
    __table_args__ = (UniqueConstraint('owner', 'key'),)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(36))


class Outbox(Base):
    __tablename__ = 'outbox'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    memory: Mapped[str] = mapped_column(String(36))
    done: Mapped[bool] = mapped_column(default=False, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    available: Mapped[float] = mapped_column(Float, default=time.time)
    payload: Mapped[str] = mapped_column(Text, default='', server_default='')


class Operation(Base):
    __tablename__ = 'operations'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36), index=True)
    companion: Mapped[str] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    reserved: Mapped[int] = mapped_column(Integer)
    actual: Mapped[int] = mapped_column(default=0)
    result: Mapped[str] = mapped_column(Text, default='')
    created: Mapped[float] = mapped_column(Float, default=time.time)


class SiteBudget(Base):
    __tablename__ = 'site_budget'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    used: Mapped[int] = mapped_column(default=0)
    reserved: Mapped[int] = mapped_column(default=0)
    __table_args__ = (CheckConstraint('used >= 0 AND reserved >= 0'),)


class RateBucket(Base):
    __tablename__ = 'rate_buckets'
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    expires: Mapped[float] = mapped_column(Float)

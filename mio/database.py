"""Database models and engine factory. SQLite is useful for tests; Docker uses PostgreSQL."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def create_database(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)

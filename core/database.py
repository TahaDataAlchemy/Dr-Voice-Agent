"""
Database engine + session dependency.

- Production: Supabase Postgres through the *session pooler* (IPv4-friendly) with SSL.
- Local/offline dev and tests: SQLite.

The same SQLModel models and services run on both engines; only the DDL details that are
Postgres-specific (regex CHECK constraints, triggers, RLS) live in the Alembic migration.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import Depends
from sqlalchemy import Engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from config import get_settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "db", "postgres"}


def normalize_database_url(url: str) -> str:
    """Rewrite provider-style URLs so SQLAlchemy uses the psycopg v3 driver, and force SSL off-box."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    if url.startswith("postgresql+psycopg://"):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.hostname not in LOCAL_HOSTS and "sslmode" not in query:
            query["sslmode"] = ["require"]
            parsed = parsed._replace(query=urlencode(query, doseq=True))
            url = urlunparse(parsed)
    return url


def build_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    url = normalize_database_url(url or settings.database_url)

    if url.startswith("sqlite"):
        if url in ("sqlite://", "sqlite:///:memory:"):
            # Shared in-memory DB for tests: one connection reused across threads.
            return create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool, echo=False
            )
        db_path = url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False}, echo=False)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    # Postgres (Supabase pooler). Keep the pool small: the free-tier session pooler has few slots.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_recycle=1800,
        echo=False,
    )


engine: Engine = build_engine()


def create_all() -> None:
    """Create tables directly (SQLite/dev/tests). Postgres uses Alembic migrations instead."""
    # Import models so they are registered on SQLModel.metadata before create_all.
    from modules.auth import user_model  # noqa: F401
    from modules.calls import call_model  # noqa: F401
    from modules.patients import patient_model  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]

"""Database construction and request transaction scope."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    pass


def make_engine(settings: Settings):
    url = settings.database_url.get_secret_value()
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 20}
    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session

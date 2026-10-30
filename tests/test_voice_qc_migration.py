"""Frozen populated SQLite/PostgreSQL schema roundtrip and cell-owner fences."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_voice_qc_frozen_populated_roundtrip_parity_and_owner_fences(tmp_path, backend):
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import MetaData, create_engine, event, select
    from sqlalchemy.exc import IntegrityError

    from alembic import command
    from videotranslate.db import Base
    from videotranslate.models.core import utcnow

    admin = None
    if backend == "postgresql":
        import psycopg
        from psycopg import sql

        url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not url:
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        name = "voice_qc_migration_" + uuid4().hex
        admin = psycopg.connect(url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (url.rsplit("/", 1)[0] + "/" + name).replace("postgresql://", "postgresql+psycopg://")
    else:
        url = f"sqlite:///{tmp_path}/voice-qc-migration.db"
    engine = create_engine(url)
    if backend == "sqlite":

        @event.listens_for(engine, "connect")
        def enforce_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    w1, w2, p1, p2, t1, t2 = [str(uuid4()) for _ in range(6)]
    now = utcnow()
    try:
        command.upgrade(config, "0009_synthesis")
        old = MetaData()
        old.reflect(engine)
        with engine.begin() as db:
            for workspace in (w1, w2):
                db.execute(
                    old.tables["workspaces"]
                    .insert()
                    .values(id=workspace, name="Existing", created_at=now)
                )
            for project in (p1, p2):
                db.execute(
                    old.tables["projects"]
                    .insert()
                    .values(
                        id=project,
                        workspace_id=w1,
                        name="Populated",
                        status="draft",
                        revision=1,
                        event_sequence=0,
                        source_language="en",
                        target_languages=[],
                        source_track_index=0,
                        settings={},
                        created_at=now,
                        updated_at=now,
                    )
                )
            for track, project in ((t1, p1), (t2, p2)):
                db.execute(
                    old.tables["language_tracks"]
                    .insert()
                    .values(
                        id=track,
                        project_id=project,
                        workspace_id=w1,
                        tag="ja",
                        mode="Fast",
                        revision=1,
                        archived=False,
                        created_at=now,
                    )
                )
        for _ in range(2):
            command.upgrade(config, "head")
            current = MetaData()
            current.reflect(engine)
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
                assert set(db.execute(select(current.tables["projects"].c.id)).scalars()) == {
                    p1,
                    p2,
                }
            values = dict(
                id=str(uuid4()),
                project_id=p1,
                workspace_id=w1,
                track_id=t1,
                signature=uuid4().hex,
                admission_sequence=0,
                actor_id=str(uuid4()),
                created_at=now,
            )
            commands = current.tables["voice_qc_commands"]
            with engine.begin() as db:
                db.execute(commands.insert().values(**values))
            for wrong in ({"project_id": p2}, {"workspace_id": w2}, {"track_id": t2}):
                with pytest.raises(IntegrityError), engine.begin() as db:
                    db.execute(
                        commands.insert().values(
                            **(values | wrong | {"id": str(uuid4()), "signature": uuid4().hex})
                        )
                    )
            command.downgrade(config, "0009_synthesis")
            with engine.connect() as db:
                assert set(db.execute(select(old.tables["projects"].c.id)).scalars()) == {p1, p2}
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
        frozen = open("alembic/versions/0010_voice_qc.py").read()
        assert "videotranslate" not in frozen and "Base.metadata" not in frozen
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

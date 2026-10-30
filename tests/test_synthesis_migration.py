"""Frozen populated SQLite/PostgreSQL schema roundtrip and cell-owner fences."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_synthesis_frozen_populated_roundtrip_parity_and_owner_fences(tmp_path, backend):
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
        name = "synthesis_migration_" + uuid4().hex
        admin = psycopg.connect(url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (url.rsplit("/", 1)[0] + "/" + name).replace("postgresql://", "postgresql+psycopg://")
    else:
        url = f"sqlite:///{tmp_path}/synthesis-migration.db"
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
        command.upgrade(config, "0008_translation_operations")
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
            root = str(uuid4())
            values = dict(
                id=root,
                project_id=p1,
                workspace_id=w1,
                track_id=t1,
                segment_id=None,
                scope_key="track",
                revision=0,
                current_version_id=None,
                created_at=now,
            )
            roots, versions = (
                current.tables["voice_settings"],
                current.tables["voice_settings_versions"],
            )
            with engine.begin() as db:
                db.execute(roots.insert().values(**values))
            for wrong in ({"project_id": p2}, {"workspace_id": w2}):
                with pytest.raises(IntegrityError), engine.begin() as db:
                    db.execute(
                        roots.insert().values(
                            **(
                                values
                                | wrong
                                | {"id": str(uuid4()), "scope_key": "foreign:" + uuid4().hex}
                            )
                        )
                    )
            version = dict(
                id=str(uuid4()),
                project_id=p1,
                workspace_id=w1,
                settings_id=root,
                track_id=t1,
                parent_version_id=None,
                revision=1,
                override=True,
                ns=32,
                gs=2.0,
                dn=True,
                sp=1.0,
                du=None,
                pp=True,
                po=True,
                actor_id=str(uuid4()),
                created_at=now,
            )
            with engine.begin() as db:
                db.execute(versions.insert().values(**version))
                db.execute(
                    roots.update()
                    .where(roots.c.id == root)
                    .values(current_version_id=version["id"], revision=1)
                )
            for wrong in ({"project_id": p2}, {"workspace_id": w2}, {"track_id": t2}):
                with pytest.raises(IntegrityError), engine.begin() as db:
                    db.execute(
                        versions.insert().values(
                            **(version | wrong | {"id": str(uuid4()), "revision": 2})
                        )
                    )
            with engine.begin() as db:
                db.execute(roots.update().values(current_version_id=None))
            command.downgrade(config, "0008_translation_operations")
            with engine.connect() as db:
                assert set(db.execute(select(old.tables["projects"].c.id)).scalars()) == {p1, p2}
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
        frozen = open("alembic/versions/0009_synthesis.py").read()
        assert "videotranslate" not in frozen and "Base.metadata" not in frozen
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

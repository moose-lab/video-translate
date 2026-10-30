"""Frozen populated 0010 up/down/up with exact owned settings family fences."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_fit_frozen_migration_populated_roundtrip_and_family_fences(tmp_path, backend):
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
        name = "fit_migration_" + uuid4().hex
        admin = psycopg.connect(url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (url.rsplit("/", 1)[0] + "/" + name).replace("postgresql://", "postgresql+psycopg://")
    else:
        url = f"sqlite:///{tmp_path}/fit.db"
    engine = create_engine(url)
    if backend == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(db, _):
            db.execute("PRAGMA foreign_keys=ON")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    w1, w2, p1, p2, r1, r2, v1, v2 = [str(uuid4()) for _ in range(8)]
    now = utcnow()
    try:
        command.upgrade(config, "0010_voice_qc")
        metadata = MetaData()
        metadata.reflect(engine)
        with engine.begin() as db:
            for w in (w1, w2):
                db.execute(
                    metadata.tables["workspaces"]
                    .insert()
                    .values(id=w, name="Old workspace", created_at=now)
                )
            for p in (p1, p2):
                db.execute(
                    metadata.tables["projects"]
                    .insert()
                    .values(
                        id=p,
                        workspace_id=w1,
                        name="Preserved old project",
                        status="draft",
                        revision=7,
                        event_sequence=13,
                        source_language="en",
                        target_languages=[],
                        source_track_index=0,
                        settings={"unchanged": True},
                        created_at=now,
                        updated_at=now,
                    )
                )
        for _ in range(2):
            command.upgrade(config, "head")
            current = MetaData()
            current.reflect(engine)
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
                project = (
                    db.execute(
                        select(current.tables["projects"]).where(
                            current.tables["projects"].c.id == p1
                        )
                    )
                    .mappings()
                    .one()
                )
                assert project["revision"] == 7 and project["settings"] == {"unchanged": True}
            roots, versions = (
                current.tables["fit_settings_states"],
                current.tables["fit_settings_versions"],
            )
            with engine.begin() as db:
                for p, r, v in ((p1, r1, v1), (p2, r2, v2)):
                    db.execute(
                        roots.insert().values(
                            id=r, project_id=p, workspace_id=w1, revision=0, created_at=now
                        )
                    )
                    db.execute(
                        versions.insert().values(
                            id=v,
                            settings_id=r,
                            project_id=p,
                            workspace_id=w1,
                            revision=1,
                            settings={},
                            policy="shared_fit_v1",
                            actor_id=str(uuid4()),
                            created_at=now,
                        )
                    )
                    db.execute(
                        roots.update()
                        .where(roots.c.id == r)
                        .values(current_version_id=v, revision=1)
                    )
            # UPDATE exactly one owner/family column: no unique violation can masquerade as FK protection.
            for table, identity, wrong in (
                (roots, r1, {"current_version_id": v2}),
                (versions, v1, {"settings_id": r2}),
                (versions, v1, {"workspace_id": w2}),
                (versions, v1, {"parent_version_id": v2}),
            ):
                with pytest.raises(IntegrityError), engine.begin() as db:
                    db.execute(table.update().where(table.c.id == identity).values(**wrong))
            command.downgrade(config, "0010_voice_qc")
        command.upgrade(config, "head")
        migration = open("alembic/versions/0011_fit_plans.py").read()
        assert "videotranslate.models" not in migration and "Base.metadata" not in migration
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

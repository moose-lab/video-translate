"""Additive 0014 migration preserves projects and matches owned metadata."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_source_import_migration(tmp_path, backend):
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import MetaData, create_engine, select

    from alembic import command
    from videotranslate.db import Base
    from videotranslate.models.core import utcnow

    admin = None
    if backend == "postgresql":
        import psycopg
        from psycopg import sql

        admin_url = os.getenv("VT_TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            pytest.skip("Isolated PostgreSQL administrator not configured")
        name = "source_import_migration_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/migration.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0013_pipeline")
        metadata = MetaData()
        metadata.reflect(engine)
        workspace, project = str(uuid4()), str(uuid4())
        with engine.begin() as db:
            db.execute(
                metadata.tables["workspaces"]
                .insert()
                .values(id=workspace, name="kept", created_at=utcnow())
            )
            db.execute(
                metadata.tables["projects"]
                .insert()
                .values(
                    id=project,
                    workspace_id=workspace,
                    name="kept",
                    revision=7,
                    event_sequence=9,
                    status="draft",
                    source_language="en",
                    target_languages=[],
                    source_track_index=0,
                    settings={"keep": True},
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        for _ in range(2):
            command.upgrade(cfg, "0014_source_import")
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
                row = db.execute(select(metadata.tables["projects"])).mappings().one()
                assert row["settings"] == {"keep": True} and row["revision"] == 7
            command.downgrade(cfg, "0013_pipeline")
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

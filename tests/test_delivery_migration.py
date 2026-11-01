"""Frozen 0012 additive migration preserves populated 0011 on SQLite/PostgreSQL."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_delivery_frozen_migration_populated_roundtrip(tmp_path, backend):
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
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        name = "delivery_migration_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/delivery.db"
    engine = create_engine(url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    workspace, project = str(uuid4()), str(uuid4())
    now = utcnow()
    try:
        command.upgrade(config, "0011_fit_plans")
        metadata = MetaData()
        metadata.reflect(engine)
        with engine.begin() as db:
            db.execute(
                metadata.tables["workspaces"]
                .insert()
                .values(id=workspace, name="preserved", created_at=now)
            )
            db.execute(
                metadata.tables["projects"]
                .insert()
                .values(
                    id=project,
                    workspace_id=workspace,
                    name="preserved",
                    status="draft",
                    revision=4,
                    event_sequence=9,
                    source_language="en",
                    target_languages=[],
                    source_track_index=0,
                    settings={"keep": True},
                    created_at=now,
                    updated_at=now,
                )
            )
        for _ in range(2):
            command.upgrade(config, "head")
            metadata = MetaData()
            metadata.reflect(engine)
            assert "delivery_commands" in metadata.tables
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
                saved = (
                    db.execute(
                        select(metadata.tables["projects"]).where(
                            metadata.tables["projects"].c.id == project
                        )
                    )
                    .mappings()
                    .one()
                )
                assert saved["revision"] == 4 and saved["settings"] == {"keep": True}
            command.downgrade(config, "0011_fit_plans")
        command.upgrade(config, "head")
        source = open("alembic/versions/0012_deliveries.py").read()
        assert "Base.metadata" not in source and "videotranslate.models" not in source
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

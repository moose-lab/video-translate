"""0013 is frozen and additive over populated delivery schema."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_pipeline_migration_roundtrip(tmp_path, backend):
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import MetaData, create_engine, inspect, text

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
        name = "pipeline_migration_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/pipeline.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "0012_deliveries")
        m = MetaData()
        m.reflect(engine)
        workspace, project = str(uuid4()), str(uuid4())
        with engine.begin() as db:
            db.execute(
                m.tables["workspaces"]
                .insert()
                .values(id=workspace, name="preserved", created_at=utcnow())
            )
            db.execute(
                m.tables["projects"]
                .insert()
                .values(
                    id=project,
                    workspace_id=workspace,
                    name="preserved",
                    status="draft",
                    revision=7,
                    event_sequence=11,
                    source_language="en",
                    target_languages=[],
                    source_track_index=0,
                    settings={"keep": True},
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        for _ in range(2):
            command.upgrade(config, "0013_pipeline")
            with engine.connect() as db:
                # Compare historical 0013 independently of the additive 0014 table.
                context = MigrationContext.configure(db, opts={
                    "include_object": lambda obj, name, type_, reflected, compare_to:
                        not (type_ == "table" and name == "source_imports")
                })
                assert compare_metadata(context, Base.metadata) == []
                for table in ('workflow_intents', 'translation_commands'):
                    column = next(c for c in inspect(db).get_columns(table) if c['name'] == 'continuation_stopped')
                    value = db.execute(text('SELECT ' + column['default'])).scalar()
                    assert value is False or (type(value) is int and value == 0), (table, value)
                row = db.execute(m.tables["projects"].select()).mappings().one()
                assert row["settings"] == {"keep": True} and row["revision"] == 7
            command.downgrade(config, "0012_deliveries")
        command.upgrade(config, "head")
        source = open("alembic/versions/0013_pipeline.py").read()
        assert "Base.metadata" not in source and "videotranslate.models" not in source
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

"""Frozen 0005→0006 populated migration evidence on SQLite and opt-in PostgreSQL."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_populated_request_alias_and_upload_fence_migration_roundtrip(tmp_path, backend):
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

        admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            pytest.skip("Opt-in isolated PostgreSQL test server unavailable")
        name = "analysis_recovery_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/recovery-migration.db"
    engine = create_engine(url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    workspace_id, project_id, run_id = (str(uuid4()) for _ in range(3))
    now = utcnow()
    try:
        command.upgrade(config, "0005_analysis_workflow")
        previous = MetaData()
        previous.reflect(engine)
        with engine.begin() as db:
            db.execute(
                previous.tables["workspaces"]
                .insert()
                .values(id=workspace_id, name="Original", created_at=now)
            )
            db.execute(
                previous.tables["projects"]
                .insert()
                .values(
                    id=project_id,
                    workspace_id=workspace_id,
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
            db.execute(
                previous.tables["stage_runs"]
                .insert()
                .values(
                    id=run_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    stage="probe",
                    scope_key="probe",
                    options={},
                    input_project_revision=1,
                    dependency_fingerprint="0" * 64,
                    dependency_snapshot={},
                    output_key="output.probe",
                    idempotency_key="original-key",
                    request_fingerprint="1" * 64,
                    status="failed",
                    is_stale=False,
                    attempt_count=0,
                    auto_failures=0,
                    due_at=now,
                    remote_state="not_submitted",
                    created_at=now,
                    updated_at=now,
                )
            )
            for state in ("writing", "orphan"):
                request_id = str(uuid4())
                db.execute(
                    previous.tables["reference_requests"]
                    .insert()
                    .values(
                        id=request_id,
                        project_id=project_id,
                        workspace_id=workspace_id,
                        created_at=now,
                        run_id=None,
                        origin="uploaded",
                        actor_id=str(uuid4()),
                        payload={"text": "private original", "language": "en"},
                        dependency_snapshot={},
                        upload_key=f"{workspace_id}/{project_id}/reference-uploads/{request_id}",
                        upload_size=4,
                        upload_sha256="2" * 64,
                        upload_state=state,
                    )
                )
        for _ in range(2):
            command.upgrade(config, "0006_analysis_recovery_fixes")
            current = MetaData()
            current.reflect(engine)
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
                alias = db.execute(select(current.tables["run_request_keys"])).mappings().one()
                assert alias["run_id"] == run_id and alias["project_id"] == project_id
                assert alias["workspace_id"] == workspace_id and alias["key"] == "original-key"
                assert alias["request_fingerprint"] == "1" * 64
                rows = db.execute(select(current.tables["reference_requests"])).mappings().all()
                assert {row["upload_state"]: row["upload_write_settled"] for row in rows} == {
                    "writing": False,
                    "orphan": True,
                }
                assert all(
                    row["upload_lease_expires_at"] is None and row["upload_token"] is None
                    for row in rows
                )
            command.downgrade(config, "0005_analysis_workflow")
            with engine.connect() as db:
                run = db.execute(select(previous.tables["stage_runs"])).mappings().one()
                assert (
                    run["idempotency_key"] == "original-key"
                    and run["request_fingerprint"] == "1" * 64
                )
                rows = db.execute(select(previous.tables["reference_requests"])).mappings().all()
                assert len(rows) == 2 and all(row["upload_sha256"] == "2" * 64 for row in rows)
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

"""Frozen 0006→0007 populated migration evidence on SQLite and opt-in PostgreSQL."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_populated_prepared_lifecycle_migration_roundtrip(tmp_path, backend):
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
        name = "analysis_prepared_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/prepared-migration.db"
    engine = create_engine(url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    workspace_id, project_id, run_id = (str(uuid4()) for _ in range(3))
    now = utcnow()
    try:
        command.upgrade(config, "0006_analysis_recovery_fixes")
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
            operation_id = str(uuid4())
            db.execute(
                previous.tables["private_operations"]
                .insert()
                .values(
                    id=operation_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    created_at=now,
                    run_id=run_id,
                    generation="3" * 64,
                    input_fingerprint="0" * 64,
                    connection_revision=0,
                    provider="cpu",
                    model="ffmpeg",
                    host="",
                    prefix="",
                    phase="prepared",
                    request_payload={},
                    prepared_payload={"objects": []},
                    public_facts={},
                )
            )
            for state in ("writing", "orphan", "deleting", "deleted", "published"):
                object_id = str(uuid4())
                db.execute(
                    previous.tables["prepared_objects"]
                    .insert()
                    .values(
                        id=object_id,
                        project_id=project_id,
                        workspace_id=workspace_id,
                        created_at=now,
                        operation_id=operation_id,
                        state=state,
                        storage_key=f"{workspace_id}/{project_id}/prepared/{object_id}",
                        metadata_json={"sha256": "2" * 64},
                    )
                )
            asset_id, track_id, selection_id, transcript_id, segment_id = (
                str(uuid4()) for _ in range(5)
            )
            owned = {"workspace_id": workspace_id, "project_id": project_id, "created_at": now}
            db.execute(
                previous.tables["assets"]
                .insert()
                .values(
                    **owned,
                    id=asset_id,
                    kind="source_video",
                    filename="source.mp4",
                    content_type="video/mp4",
                    byte_size=1,
                    sha256="4" * 64,
                    storage_key=f"{workspace_id}/{project_id}/source/{asset_id}",
                )
            )
            db.execute(
                previous.tables["source_tracks"]
                .insert()
                .values(
                    **owned,
                    id=track_id,
                    source_asset_id=asset_id,
                    probe_run_id=run_id,
                    audio_ordinal=0,
                    stream_index=1,
                    codec="aac",
                    language="en",
                    channels=1,
                    sample_rate=16000,
                    duration_ms=5000,
                )
            )
            db.execute(
                previous.tables["source_selections"]
                .insert()
                .values(
                    **owned,
                    id=selection_id,
                    track_id=track_id,
                    revision=1,
                    start_ms=0,
                    end_ms=5000,
                    actor_id=str(uuid4()),
                )
            )
            originals = [{"start": 0.8, "end": 5.04, "speaker": 0, "text": "Fixture words"}]
            db.execute(
                previous.tables["transcript_revisions"]
                .insert()
                .values(
                    **owned,
                    id=transcript_id,
                    selection_id=selection_id,
                    provenance="provider",
                    actor_id=str(uuid4()),
                    run_id=run_id,
                    provider="nvidia_stream",
                    original_segments=originals,
                )
            )
            db.execute(
                previous.tables["segments"]
                .insert()
                .values(
                    **owned,
                    id=segment_id,
                    transcript_id=transcript_id,
                    display_index=0,
                    original_text="Fixture words",
                    original_speaker_label="0",
                    revision=0,
                    archived=False,
                )
            )
        historical = MetaData()
        for table in Base.metadata.tables.values():
            if table.name not in {"translation_commands", "translation_phases"}:
                table.to_metadata(historical)
        for _ in range(2):
            command.upgrade(config, "0007_prepared_object_lifecycle")
            current = MetaData()
            current.reflect(engine)
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), historical) == []
                rows = db.execute(select(current.tables["prepared_objects"])).mappings().all()
                assert {r["state"]: r["write_settled"] for r in rows} == {
                    "writing": False,
                    "orphan": True,
                    "deleting": False,
                    "deleted": False,
                    "published": True,
                }
                assert all(
                    not r["delete_pending"]
                    and r["gc_checked_at"] is None
                    and r["reservation_token"] is None
                    for r in rows
                )
                assert all(r["metadata_json"]["sha256"] == "2" * 64 for r in rows)
                assert len(current.tables["prepared_objects"].foreign_key_constraints) == len(
                    previous.tables["prepared_objects"].foreign_key_constraints
                )
                assert (
                    db.execute(
                        select(current.tables["segments"].c.source_analysis_flags)
                    ).scalar_one()
                    == []
                )
                assert (
                    db.execute(
                        select(current.tables["transcript_revisions"].c.original_segments)
                    ).scalar_one()
                    == originals
                )
            command.downgrade(config, "0006_analysis_recovery_fixes")
            with engine.connect() as db:
                run = db.execute(select(previous.tables["stage_runs"])).mappings().one()
                assert (
                    run["idempotency_key"] == "original-key"
                    and run["request_fingerprint"] == "1" * 64
                )
                rows = db.execute(select(previous.tables["prepared_objects"])).mappings().all()
                assert len(rows) == 5 and all(
                    r["metadata_json"]["sha256"] == "2" * 64 for r in rows
                )
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

"""Frozen populated schema roundtrip and owner fences, SQLite and isolated PostgreSQL."""

import os
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_translation_migration_is_frozen_populated_roundtrip_and_parity(tmp_path, backend):
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

        admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        name = "translation_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/translation-migration.db"
    engine = create_engine(url)
    if backend == "sqlite":

        @event.listens_for(engine, "connect")
        def enforce_foreign_keys(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    workspace, project, foreign, run = [str(uuid4()) for _ in range(4)]
    asset_id, source_track, selection_id, transcript_id, track_id, command_id = [
        str(uuid4()) for _ in range(6)
    ]
    other_workspace = str(uuid4())
    now = utcnow()
    try:
        command.upgrade(config, "0007_prepared_object_lifecycle")
        previous = MetaData()
        previous.reflect(engine)
        with engine.begin() as db:
            db.execute(
                previous.tables["workspaces"]
                .insert()
                .values(id=workspace, name="Existing", created_at=now)
            )
            db.execute(
                previous.tables["workspaces"]
                .insert()
                .values(id=other_workspace, name="Other workspace", created_at=now)
            )
            for project_id in (project, foreign):
                db.execute(
                    previous.tables["projects"]
                    .insert()
                    .values(
                        id=project_id,
                        workspace_id=workspace,
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
                    id=run,
                    workspace_id=workspace,
                    project_id=project,
                    stage="probe",
                    scope_key="probe",
                    options={},
                    input_project_revision=1,
                    dependency_fingerprint="0" * 64,
                    dependency_snapshot={},
                    output_key="output.probe",
                    request_fingerprint="1" * 64,
                    status="succeeded",
                    is_stale=False,
                    attempt_count=0,
                    auto_failures=0,
                    due_at=now,
                    remote_state="not_submitted",
                    created_at=now,
                    updated_at=now,
                )
            )
            common = {"workspace_id": workspace, "project_id": project, "created_at": now}
            db.execute(
                previous.tables["assets"]
                .insert()
                .values(
                    id=asset_id,
                    **common,
                    filename="source.mp4",
                    content_type="video/mp4",
                    byte_size=1,
                    sha256="3" * 64,
                    kind="source_video",
                    storage_key="existing-source",
                )
            )
            db.execute(
                previous.tables["source_tracks"]
                .insert()
                .values(
                    id=source_track,
                    **common,
                    source_asset_id=asset_id,
                    probe_run_id=run,
                    audio_ordinal=0,
                    stream_index=0,
                    codec="aac",
                    language="en",
                    channels=1,
                    sample_rate=16000,
                    duration_ms=1000,
                )
            )
            db.execute(
                previous.tables["source_selections"]
                .insert()
                .values(
                    id=selection_id,
                    **common,
                    track_id=source_track,
                    revision=1,
                    start_ms=0,
                    end_ms=1000,
                    actor_id=str(uuid4()),
                )
            )
            db.execute(
                previous.tables["transcript_revisions"]
                .insert()
                .values(
                    id=transcript_id,
                    **common,
                    selection_id=selection_id,
                    provenance="manual",
                    actor_id=str(uuid4()),
                    original_segments=[],
                )
            )
            db.execute(
                previous.tables["language_tracks"]
                .insert()
                .values(id=track_id, **common, tag="ja", mode="Fast", revision=1, archived=False)
            )
        for _ in range(2):
            command.upgrade(config, "head")
            current = MetaData()
            current.reflect(engine)
            assert (
                "translation_commands" in current.tables and "translation_phases" in current.tables
            )
            with engine.connect() as db:
                assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
                assert db.execute(select(current.tables["stage_runs"].c.id)).scalar_one() == run
            commands, phase = (
                current.tables["translation_commands"],
                current.tables["translation_phases"],
            )
            command_values = dict(
                id=command_id,
                workspace_id=workspace,
                project_id=project,
                track_id=track_id,
                selection_id=selection_id,
                transcript_id=transcript_id,
                signature="a" * 64,
                actor_id=str(uuid4()),
                payload={"original": "private"},
                row_heads={},
                created_at=now,
            )
            with engine.begin() as db:
                db.execute(commands.insert().values(**command_values))
                db.execute(
                    phase.insert().values(
                        id=str(uuid4()),
                        workspace_id=workspace,
                        project_id=project,
                        command_id=command_id,
                        run_id=run,
                        parent_phase_id=None,
                        batch_index=0,
                        phase="draft",
                        input_payload={"private": "source"},
                        input_fingerprint="2" * 64,
                        dependency_snapshot={},
                        guard_snapshot={},
                        publication={},
                        applied=False,
                        created_at=now,
                    )
                )
            # All required values and parent IDs are valid. Only project ownership differs.
            with pytest.raises(IntegrityError), engine.begin() as db:
                db.execute(
                    commands.insert().values(
                        **(
                            command_values
                            | {"id": str(uuid4()), "project_id": foreign, "signature": "b" * 64}
                        )
                    )
                )
            with pytest.raises(IntegrityError), engine.begin() as db:
                db.execute(
                    phase.insert().values(
                        id=str(uuid4()),
                        workspace_id=workspace,
                        project_id=foreign,
                        command_id=command_id,
                        run_id=None,
                        parent_phase_id=None,
                        batch_index=1,
                        phase="draft",
                        input_payload={},
                        input_fingerprint="2" * 64,
                        dependency_snapshot={},
                        guard_snapshot={},
                        publication={},
                        applied=False,
                        created_at=now,
                    )
                )
            with pytest.raises(IntegrityError), engine.begin() as db:
                db.execute(
                    commands.insert().values(
                        **(
                            command_values
                            | {
                                "id": str(uuid4()),
                                "workspace_id": other_workspace,
                                "signature": "c" * 64,
                            }
                        )
                    )
                )
            command.downgrade(config, "0007_prepared_object_lifecycle")
            with engine.connect() as db:
                assert db.execute(select(previous.tables["stage_runs"].c.id)).scalar_one() == run
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
    finally:
        engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

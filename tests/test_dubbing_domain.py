"""CPU probe and immutable source selection; isolated DB, no provider access."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from dubbing_helpers import create_line, guard, select_source, selected
from sqlalchemy import func, select


def test_real_probe_selection_and_read_only_paged_timeline(dubbing_project):
    c, _, p = dubbing_project
    result = selected(dubbing_project)
    assert 2000 <= result["end_ms"] < 2200
    assert result["track"]["audio_ordinal"] == 0
    assert result["track"]["stream_index"] == 1
    assert result["track"]["sample_rate"] > 0
    assert result["track"]["probe_run_id"]
    first = c.get(f"/api/projects/{p['id']}/timeline").json()
    assert first["segments"] == [] and first["total"] == 0
    assert first["transcript"] is None
    from videotranslate.models.dubbing import LanguageTrack

    with c.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LanguageTrack)) == 0
    assert first["language_tracks"][0]["materialized"] is False
    line = create_line(dubbing_project, result)
    view = c.get(f"/api/projects/{p['id']}/timeline?limit=1").json()
    assert view["segments"][0]["id"] == line["segment"]["id"]
    assert view["transcript"]["provenance"] == "manual"
    assert "storage_key" not in str(view)
    assert c.get(f"/api/projects/{p['id']}/timeline?limit=201").status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"audio_ordinal": 1},
        {"start_ms": -1},
        {"start_ms": True},
        {"start_ms": 0.5},
        {"start_ms": "0"},
        {"end_ms": 0},
        {"start_ms": 900, "end_ms": 800},
        {"end_ms": 3000},
    ],
)
def test_invalid_source_windows_and_ordinals(dubbing_project, change):
    assert select_source(dubbing_project, **change).status_code == 422


def test_selection_lineage_and_legacy_track_patch_make_old_transcript_historical(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    line = create_line(dubbing_project, s)
    response = c.patch(f"/api/projects/{p['id']}", headers=h, json={"source_track_index": 1})
    assert response.status_code == 200
    view = c.get(f"/api/projects/{p['id']}/timeline").json()
    assert view["transcript"]["stale"] is True
    body = guard(s, line["transcript_revision"]) | {"revision": 1, "text": "changed"}
    assert (
        c.patch(
            f"/api/projects/{p['id']}/segments/{line['segment']['id']}", headers=h, json=body
        ).status_code
        == 409
    )
    assert (
        c.get(
            f"/api/projects/{p['id']}/transcripts/{line['transcript_revision']}/segments"
        ).status_code
        == 200
    )


def test_source_selection_requires_current_successful_probe(dubbing_project):
    from videotranslate.models.execution import StageRun

    c, _, _ = dubbing_project
    with c.app.state.session_factory.begin() as db:
        run = db.scalar(select(StageRun))
        run.is_stale = True
    assert select_source(dubbing_project).status_code == 409


def test_same_and_different_row_actual_simultaneous_cas(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    b = create_line(dubbing_project, s, "second", a["transcript_revision"], 600, 1000)
    base = f"/api/projects/{p['id']}/segments/"

    def race(ids):
        barrier = Barrier(2)

        def edit(pair):
            index, segment_id = pair
            barrier.wait()
            return c.patch(
                base + segment_id,
                headers=h,
                json=guard(s, a["transcript_revision"]) | {"revision": 1, "text": f"Edit {index}"},
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            return sorted(pool.map(edit, enumerate(ids)))

    assert race([a["segment"]["id"], b["segment"]["id"]]) == [200, 200]
    # Two fresh requests against the same revision, using a new segment.
    d = create_line(dubbing_project, s, "third", a["transcript_revision"], 1000, 1500)
    assert race([d["segment"]["id"], d["segment"]["id"]]) == [200, 409]


def test_changing_selection_allows_fresh_manual_batch_and_never_rebinds_old(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    old = create_line(dubbing_project, s)
    current = c.get(f"/api/projects/{p['id']}").json()
    response = c.put(
        f"/api/projects/{p['id']}/source-selection",
        headers=h,
        json={
            "revision": current["revision"],
            "source_asset_id": p["source_asset_id"],
            "audio_ordinal": 0,
            "start_ms": 500,
            "end_ms": 1500,
        },
    )
    assert response.status_code == 200, response.text
    new = create_line(dubbing_project, response.json())
    assert new["transcript_revision"] != old["transcript_revision"]
    assert new["segment"]["absolute_start_ms"] == 500


def test_legacy_track_roundtrip_does_not_reactivate_historical_selection(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    create_line(dubbing_project, s)
    for ordinal in [1, 0]:
        assert (
            c.patch(
                f"/api/projects/{p['id']}", headers=h, json={"source_track_index": ordinal}
            ).status_code
            == 200
        )
    assert c.get(f"/api/projects/{p['id']}/timeline").json()["transcript"]["stale"]


def test_workspace_cross_project_and_deleted_resources_are_hidden(
    dubbing_project, client_factory, register
):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    line = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    speaker = c.post(base + "/speakers", headers=h, json={"name": "A"}).json()
    neighbor = c.post("/api/projects", headers=h, json={"name": "Neighbor"}).json()
    nid = neighbor["id"]
    # Same workspace, different project: even history and cast binding cannot borrow IDs.
    assert (
        c.get(f"/api/projects/{nid}/segments/{line['segment']['id']}/revisions").status_code == 404
    )
    assert (
        c.patch(
            f"/api/projects/{nid}/speakers/{speaker['id']}",
            headers=h,
            json={"revision": 1, "name": "Bad"},
        ).status_code
        == 404
    )
    assert (
        c.get(f"/api/projects/{nid}/transcripts/{line['transcript_revision']}/segments").status_code
        == 404
    )
    foreign = client_factory(database_url=c.app.state.settings.database_url.get_secret_value())
    fh = {"X-CSRF-Token": register(foreign, "foreign@example.com")["csrf_token"]}
    assert foreign.get(base + "/timeline").status_code == 404
    assert (
        foreign.put(
            base + "/source-selection",
            headers=fh,
            json={"revision": 1, "source_asset_id": p["source_asset_id"], "audio_ordinal": 0},
        ).status_code
        == 404
    )
    assert c.post(base + "/speakers", json={"name": "No CSRF"}).status_code == 403
    assert c.delete(base, headers=h).status_code == 204
    assert c.get(base + "/segments/" + line["segment"]["id"] + "/revisions").status_code == 404


def test_database_composite_foreign_keys_reject_wrong_project_and_wrong_cell(
    dubbing_project, register
):
    from sqlalchemy.exc import IntegrityError

    from videotranslate.models.core import Project
    from videotranslate.models.dubbing import Segment, SegmentRevision, SourceTrack

    c, h, p = dubbing_project
    s = selected(dubbing_project)
    first = create_line(dubbing_project, s)
    second = create_line(dubbing_project, s, "Other", first["transcript_revision"], 600, 1000)
    neighbor = c.post("/api/projects", headers=h, json={"name": "Neighbor"}).json()
    with c.app.state.session_factory() as db:
        project = db.get(Project, p["id"])
        original = db.get(SourceTrack, s["track"]["id"])
        db.add(
            SourceTrack(
                project_id=neighbor["id"],
                workspace_id=project.workspace_id,
                source_asset_id=original.source_asset_id,
                probe_run_id=original.probe_run_id,
                audio_ordinal=0,
                stream_index=1,
                codec="aac",
                language="und",
                channels=1,
                sample_rate=44100,
                duration_ms=2000,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    with c.app.state.session_factory() as db:
        one = db.get(Segment, first["segment"]["id"])
        two = db.get(Segment, second["segment"]["id"])
        one.current_revision_id = two.current_revision_id
        with pytest.raises(IntegrityError):
            db.commit()
    with c.app.state.session_factory() as db:
        one = db.get(Segment, first["segment"]["id"])
        db.add(
            SegmentRevision(
                project_id=neighbor["id"],
                workspace_id=one.workspace_id,
                segment_id=one.id,
                text="bad",
                start_ms=0,
                end_ms=1,
                actor_id="fake",
                provenance="manual",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_dubbing_migration_roundtrip_and_metadata_parity(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    from alembic import command
    from videotranslate.db import Base

    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path}/migrated.db"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(config, "0003_cloud_services")
    assert "source_tracks" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    engine.dispose()


def test_verified_unversioned_baseline_upgrade_preserves_fake_credentials(tmp_path):
    """Simulate increment-3 development create_all, never inspect the user's preview DB."""
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import MetaData, create_engine, inspect, text
    from sqlalchemy.orm import Session

    from alembic import command
    from videotranslate.db import Base
    from videotranslate.models import dubbing
    from videotranslate.models.core import Workspace
    from videotranslate.models.providers import WorkspaceCredential

    domain = {
        table.name
        for table in Base.metadata.tables.values()
        if table.name
        in {
            cls.__tablename__
            for cls in (
                dubbing.SourceTrack,
                dubbing.SourceSelection,
                dubbing.SourceState,
                dubbing.TranscriptRevision,
                dubbing.Segment,
                dubbing.SegmentRevision,
                dubbing.SegmentParent,
                dubbing.Speaker,
                dubbing.SpeakerRevision,
                dubbing.LanguageTrack,
                dubbing.ContextRevision,
                dubbing.TranslationRevision,
                dubbing.TranslationState,
            )
        }
    }
    baseline = MetaData()
    for table in Base.metadata.tables.values():
        if table.name not in domain and table.name not in {
            "run_request_keys",
            "translation_commands",
            "translation_phases",
            "voice_settings",
            "voice_settings_versions",
            "synthesis_commands",
            "synthesis_lines",
            "natural_outputs",
            "audio_selections",
            "audio_selection_versions",
            "private_operations",
            "prepared_objects",
            "analysis_media",
            "workflow_intents",
            "workflow_children",
            "reference_requests",
            "voice_references",
            "reference_versions",
            "voice_bindings",
            "voice_binding_versions",
        }:
            table.to_metadata(baseline)
    index = next(
        i for i in baseline.tables["assets"].indexes if i.name == "uq_assets_id_project_workspace"
    )
    baseline.tables["assets"].indexes.remove(index)
    url = f"sqlite:///{tmp_path}/baseline-dev.db"
    engine = create_engine(url)
    baseline.create_all(engine)
    with Session(engine) as db:
        workspace = Workspace(name="Isolated fake")
        db.add(workspace)
        db.flush()
        db.add(
            WorkspaceCredential(
                workspace_id=workspace.id,
                kind="huggingface",
                revision=1,
                ciphertext="test-only-opaque-ciphertext",
            )
        )
        db.commit()
    with engine.connect() as connection:
        assert "alembic_version" not in inspect(connection).get_table_names()
        assert compare_metadata(MigrationContext.configure(connection), baseline) == []
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.stamp(config, "0003_cloud_services")
    command.upgrade(config, "head")
    assert "uq_assets_id_project_workspace" in {
        i["name"] for i in inspect(engine).get_indexes("assets")
    }
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT ciphertext FROM workspace_credentials")).scalar_one()
            == "test-only-opaque-ciphertext"
        )
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    engine.dispose()


def test_postgres_dubbing_roundtrip_ownership_and_simultaneous_cas(
    client_factory, register, tmp_path
):
    """Opt-in local test server only; create/drop our own unique database, never a user DB."""
    import os
    from uuid import uuid4

    import psycopg
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from dubbing_helpers import make_probed_project
    from psycopg import sql
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError

    from alembic import command
    from videotranslate.db import Base
    from videotranslate.models.core import Project
    from videotranslate.models.dubbing import SourceTrack, Speaker

    admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Opt-in isolated PostgreSQL test server unavailable")
    name = "dubbing_4a_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
    url = admin_url.rsplit("/", 1)[0] + "/" + name
    sqlalchemy_url = url.replace("postgresql://", "postgresql+psycopg://")
    engine = create_engine(sqlalchemy_url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    client = None
    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        fixture = make_probed_project(
            lambda: client_factory(database_url=sqlalchemy_url), register, tmp_path
        )
        client, h, p = fixture
        s = selected(fixture)
        a = create_line(fixture, s)
        b = create_line(fixture, s, "Other", a["transcript_revision"], 600, 1000)
        neighbor = client.post("/api/projects", headers=h, json={"name": "Other"}).json()
        with client.app.state.session_factory() as db:
            project = db.get(Project, p["id"])
            original = db.get(SourceTrack, s["track"]["id"])
            db.add(
                SourceTrack(
                    project_id=neighbor["id"],
                    workspace_id=project.workspace_id,
                    source_asset_id=original.source_asset_id,
                    probe_run_id=original.probe_run_id,
                    audio_ordinal=0,
                    stream_index=1,
                    codec="aac",
                    language="und",
                    channels=1,
                    sample_rate=44100,
                    duration_ms=2000,
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()

        def race(ids):
            barrier = Barrier(2)

            def edit(pair):
                index, sid = pair
                barrier.wait()
                return client.patch(
                    f"/api/projects/{p['id']}/segments/{sid}",
                    headers=h,
                    json=guard(s, a["transcript_revision"])
                    | {"revision": 1, "text": f"PG edit {index}"},
                ).status_code

            with ThreadPoolExecutor(2) as pool:
                return sorted(pool.map(edit, enumerate(ids)))

        assert race([a["segment"]["id"], b["segment"]["id"]]) == [200, 200]
        d = create_line(fixture, s, "Third", a["transcript_revision"], 1000, 1500)
        assert race([d["segment"]["id"], d["segment"]["id"]]) == [200, 409]
        base = f"/api/projects/{p['id']}"
        old_role = client.post(base + "/speakers", headers=h, json={"name": "Historical PG role"})
        assert old_role.status_code == 201, old_role.text
        with client.app.state.session_factory() as db:
            project = db.get(Project, p["id"])
            db.add(
                Speaker(
                    project_id=neighbor["id"],
                    workspace_id=project.workspace_id,
                    selection_id=s["id"],
                    name="Wrong selection owner",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
        current = client.get(base).json()
        new_selection = client.put(
            base + "/source-selection",
            headers=h,
            json={
                "revision": current["revision"],
                "source_asset_id": p["source_asset_id"],
                "audio_ordinal": 0,
                "start_ms": 500,
                "end_ms": 1500,
            },
        )
        assert new_selection.status_code == 200, new_selection.text
        new_role = client.post(base + "/speakers", headers=h, json={"name": "Current PG role"})
        assert new_role.status_code == 201, new_role.text
        assert new_role.json()["selection_id"] == new_selection.json()["id"]
        assert (
            client.post(
                base + "/segments",
                headers=h,
                json=guard(new_selection.json())
                | {
                    "text": "Current PG line",
                    "start_ms": 0,
                    "end_ms": 500,
                    "speaker_id": new_role.json()["id"],
                },
            ).status_code
            == 201
        )
        # Exercise downgrade with populated domain history and pointer cycles.
        client.app.state.engine.dispose()
        command.downgrade(config, "0003_cloud_services")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        engine.dispose()
        if client:
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_bounded_json_requests_and_invalid_unicode_are_rejected_safely(dubbing_project):
    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    response = c.post(base + "/speakers", headers=h, json={"name": "nul\u0000name"})
    assert response.status_code == 422
    response = c.post(
        base + "/speakers",
        headers=h | {"Content-Type": "application/json"},
        content=b'{"name":"A"' + b" " * (4 * 1024 * 1024) + b"}",
    )
    assert response.status_code == 422


def test_timeline_caps_cast_and_track_summaries_and_lists_page_them(dubbing_project):
    from videotranslate.models.core import Project
    from videotranslate.models.dubbing import LanguageTrack, Speaker

    c, _, p = dubbing_project
    selection = selected(dubbing_project)
    with c.app.state.session_factory.begin() as db:
        project = db.get(Project, p["id"])
        for index in range(205):
            db.add(
                Speaker(
                    project_id=project.id,
                    workspace_id=project.workspace_id,
                    name=f"Work label {index}",
                    selection_id=selection["id"],
                )
            )
            db.add(
                LanguageTrack(
                    project_id=project.id,
                    workspace_id=project.workspace_id,
                    tag=f"test-{index}",
                    archived=True,
                )
            )
    base = f"/api/projects/{p['id']}"
    view = c.get(base + "/timeline").json()
    assert len(view["cast"]) == 200 and view["cast_total"] == 205
    assert len(view["language_tracks"]) <= 200 and view["language_tracks_total"] == 206
    page = c.get(base + "/speakers?limit=5&offset=200").json()
    assert len(page["items"]) == 5 and page["total"] == 205
    page = c.get(base + "/language-tracks?limit=5&offset=200").json()
    assert len(page["items"]) == 5 and page["total"] == 205


@pytest.mark.parametrize(
    "glossary",
    [{"word": "\ud800"}, {"\udfff": "word"}, {"word": "bad\x01control"}, {"bad\x02key": "word"}],
)
def test_nested_glossary_invalid_unicode_is_safe_422_and_never_persisted(dubbing_project, glossary):
    import json

    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    body = json.dumps({"tag": "ja", "glossary": glossary}, ensure_ascii=True)
    response = c.post(
        base + "/language-tracks", headers=h | {"Content-Type": "application/json"}, content=body
    )
    assert response.status_code == 422, response.text
    assert "word" not in response.text
    assert c.get(base + "/language-tracks").json()["total"] == 0


def test_nested_glossary_unicode_roundtrip_and_structural_bounds(dubbing_project):
    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    glossary = {"你好": "مرحبا e\u0301 😀"}
    created = c.post(base + "/language-tracks", headers=h, json={"tag": "ja", "glossary": glossary})
    assert created.status_code == 201, created.text
    assert c.get(base + "/language-tracks/ja/contexts").json()["items"][0]["glossary"] == glossary
    nested = "text"
    for _ in range(60):
        nested = [nested]
    response = c.patch(
        base + "/language-tracks/ja", headers=h, json={"revision": 1, "glossary": {"word": nested}}
    )
    assert response.status_code == 422, response.text
    assert c.get(base + "/language-tracks/ja/contexts").json()["total"] == 1


def test_wrong_glossary_value_never_echoes_private_term_in_validation_location(dubbing_project):
    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    sentinel = "PRIVATE_DIALOGUE_SENTINEL"
    body = {"tag": "ja", "glossary": {sentinel: {"invalid": "type"}}}
    response = c.post(base + "/language-tracks", headers=h, json=body)
    assert response.status_code == 422, response.text
    assert sentinel not in response.text
    assert response.json()["error"]["details"][0]["field"] == "body.glossary"
    assert c.get(base + "/language-tracks").json()["total"] == 0

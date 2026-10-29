"""QUALITY regressions use real storage/media and explicit recording providers."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from dubbing_helpers import guard, selected
from sqlalchemy import select
from test_analysis_execution import claimed
from test_analysis_workflow import configure_remote, recording_provider, timeline

from videotranslate.execution.context import RunContext
from videotranslate.execution.contracts import LeaseLost, RunCreate
from videotranslate.execution.prepared import Operations, cleanup_orphans, store_audio
from videotranslate.execution.service import claim_run, create_run
from videotranslate.execution.worker import Worker
from videotranslate.media.audio import AudioFile
from videotranslate.models.analysis import PreparedObject
from videotranslate.models.core import Project, utcnow
from videotranslate.models.execution import StageRun


def analysis(fixture):
    client, headers, p = fixture
    response = client.post(
        f"/api/projects/{p['id']}/workflow",
        headers=headers,
        json={
            "action": "analyse",
            "expected_editor_fingerprint": timeline(fixture)["editor_fingerprint"],
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def completed(fixture, monkeypatch):
    client, _, _ = fixture
    selected(fixture)
    configure_remote(fixture)
    provider = recording_provider(monkeypatch, client)
    intent = analysis(fixture)
    worker = Worker(client.app.state.settings)
    for _ in range(3):
        assert worker.run_once()
    return intent, worker, provider


def test_completed_analysis_replay_is_local_and_preserves_immutable_source(
    dubbing_project, monkeypatch
):
    client, _, p = dubbing_project
    first, worker, provider = completed(dubbing_project, monkeypatch)
    original = timeline(dubbing_project)
    second = analysis(dubbing_project)
    assert second["id"] != first["id"]
    assert worker.run_once()  # a durable guarded cache-review intent, never another ASR
    current = timeline(dubbing_project)
    assert current["transcript"]["id"] == original["transcript"]["id"]
    assert current["segments"] == original["segments"] and current["cast"] == original["cast"]
    assert len([url for url in provider.posts if "/hf-inference/" in url]) == 1
    assert (
        client.get(f"/api/projects/{p['id']}/workflow/{second['id']}").json()["status"] == "review"
    )
    assert analysis(dubbing_project)["id"] == second["id"]
    assert not worker.run_once()


def test_completed_analysis_replay_preserves_manual_source_and_cast(dubbing_project, monkeypatch):
    client, headers, p = dubbing_project
    _, worker, provider = completed(dubbing_project, monkeypatch)
    base = f"/api/projects/{p['id']}"
    before = timeline(dubbing_project)
    old_proof = before["editor_fingerprint"]
    role = client.post(base + "/speakers", headers=headers, json={"name": "My edited cast"}).json()
    line = before["segments"][0]
    corrected = client.patch(
        base + "/segments/" + line["id"],
        headers=headers,
        json=guard(before["source"], before["transcript"]["id"])
        | {"revision": line["revision"], "text": "Human corrected words", "speaker_id": role["id"]},
    )
    assert corrected.status_code == 200
    manual = timeline(dubbing_project)
    stale_browser = client.post(
        base + "/workflow",
        headers=headers,
        json={"action": "analyse", "expected_editor_fingerprint": old_proof},
    )
    assert stale_browser.status_code == 409
    analysis(dubbing_project)
    assert worker.run_once()
    current = timeline(dubbing_project)
    assert current["segments"] == manual["segments"] and current["cast"] == manual["cast"]
    assert current["transcript"]["id"] == manual["transcript"]["id"]
    assert len([url for url in provider.posts if "/hf-inference/" in url]) == 1


def test_cached_review_keeps_enqueue_editor_guard_and_changed_audio_runs_again(
    dubbing_project, monkeypatch
):
    client, headers, p = dubbing_project
    _, worker, provider = completed(dubbing_project, monkeypatch)
    base = f"/api/projects/{p['id']}"
    cached = analysis(dubbing_project)
    source = timeline(dubbing_project)
    role = client.post(base + "/speakers", headers=headers, json={"name": "After queue"})
    assert role.status_code == 201
    assert worker.run_once()
    assert client.get(base + "/workflow/" + cached["id"]).json()["status"] == "stale"
    assert len([url for url in provider.posts if "/hf-inference/" in url]) == 1
    current = client.get(base).json()
    assert (
        client.put(
            base + "/source-selection",
            headers=headers,
            json={
                "revision": current["revision"],
                "source_asset_id": p["source_asset_id"],
                "audio_ordinal": 0,
                "start_ms": 200,
                "end_ms": 1200,
            },
        ).status_code
        == 200
    )
    analysis(dubbing_project)
    for _ in range(3):
        assert worker.run_once()
    assert len([url for url in provider.posts if "/hf-inference/" in url]) == 2
    assert timeline(dubbing_project)["source"]["id"] != source["source"]["id"]


def prepared(execution_project, tmp_path):
    client, _, project = execution_project
    ctx = claimed(client, project)
    op = Operations(ctx).prepare(provider="cpu", model="ffmpeg")
    path = tmp_path / "audio"
    path.write_bytes(b"prepared")
    audio = AudioFile(path, 1, 16000, 1, 8, hashlib.sha256(b"prepared").hexdigest())
    return ctx, op, audio


def collect(ctx, limit=1):
    with ctx.session_factory() as db:
        workspace = db.get(StageRun, ctx.run_id).workspace_id
    return cleanup_orphans(
        ctx.session_factory,
        ctx.storage,
        workspace_id=workspace,
        before=utcnow() + timedelta(days=1),
        limit=limit,
    )


def test_prepared_cache_protection_does_not_starve_later_garbage(execution_project, tmp_path):
    ctx, op, audio = prepared(execution_project, tmp_path)
    current = store_audio(ctx, op.id, audio, "asr_audio")
    Operations(ctx).cache({"objects": [current]}, {"object_count": 1})
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
        project = db.get(Project, run.project_id)
        create_run(db, project.workspace_id, project.id, RunCreate(stage="probe"), "other")
        lease = claim_run(db, "other")
    other = RunContext(ctx.session_factory, ctx.storage, ctx.settings, lease.id, lease.lease_token)
    second_op = Operations(other).prepare(provider="cpu", model="ffmpeg")
    garbage = store_audio(other, second_op.id, audio, "asr_audio")
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, other.run_id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
    assert 1 in [collect(ctx) for _ in range(4)]
    with ctx.session_factory() as db:
        assert db.get(PreparedObject, current).state == "orphan"
        assert db.get(PreparedObject, garbage).state == "deleted"


@pytest.mark.parametrize("order", ["delete_first", "writer_first", "delete_done_before_writer"])
def test_prepared_writer_settlement_survives_lease_loss_and_gc_races(
    execution_project, tmp_path, monkeypatch, order
):
    ctx, op, audio = prepared(execution_project, tmp_path)
    put_started, put_release = Event(), Event()
    delete_started, delete_release = Event(), Event()
    original_put, original_delete = ctx.storage.put, ctx.storage.delete

    def put(key, source, content_type):
        put_started.set()
        assert put_release.wait(10)
        original_put(key, source, content_type)

    def delete(key):
        delete_started.set()
        if order == "writer_first":
            assert delete_release.wait(10)
        original_delete(key)
        if order == "delete_done_before_writer":
            assert delete_release.wait(10)

    monkeypatch.setattr(ctx.storage, "put", put)
    monkeypatch.setattr(ctx.storage, "delete", delete)
    with ThreadPoolExecutor(2) as pool:
        pending = pool.submit(store_audio, ctx, op.id, audio, "asr_audio")
        try:
            assert put_started.wait(5)
            assert collect(ctx) == 0  # the original live lease remains protected
            with ctx.session_factory.begin() as db:
                db.get(StageRun, ctx.run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
                record = db.scalar(
                    select(PreparedObject).where(PreparedObject.operation_id == op.id)
                )
            if order == "delete_first":
                assert collect(ctx) == 1
                put_release.set()
                with pytest.raises(LeaseLost):
                    pending.result(timeout=5)
                with ctx.storage.open(record.storage_key) as source:
                    assert source.read() == b"prepared"
            else:
                pending_gc = pool.submit(collect, ctx)
                assert delete_started.wait(5)
                put_release.set()
                with pytest.raises(LeaseLost):
                    pending.result(timeout=5)
                delete_release.set()
                assert pending_gc.result(timeout=5) == 1
            for _ in range(3):
                collect(ctx)
            with ctx.session_factory() as db:
                row = db.get(PreparedObject, record.id)
                assert row.state == "deleted" and row.write_settled and not row.delete_pending
                assert row.asset_id is None
            with pytest.raises(FileNotFoundError):
                ctx.storage.open(record.storage_key)
        finally:
            put_release.set()
            delete_release.set()


def test_prepared_crash_tombstone_and_failed_deletes_rotate_without_losing_late_bytes(
    execution_project, tmp_path, monkeypatch
):
    import io

    ctx, op, audio = prepared(execution_project, tmp_path)
    object_id = store_audio(ctx, op.id, audio, "asr_audio")
    with ctx.session_factory.begin() as db:
        record = db.get(PreparedObject, object_id)
        record.state, record.write_settled = "writing", False  # crash before settlement
        db.get(StageRun, ctx.run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    assert collect(ctx) == 1
    ctx.storage.put(record.storage_key, io.BytesIO(b"late bytes"), "audio/wav")
    original = ctx.storage.delete
    attempts = []

    def unavailable(key):
        attempts.append(key)
        if len(attempts) < 3:
            raise OSError("test-only delete failure")
        original(key)

    monkeypatch.setattr(ctx.storage, "delete", unavailable)
    for _ in range(4):
        assert collect(ctx) == 0
    assert len(attempts) >= 3
    with pytest.raises(FileNotFoundError):
        ctx.storage.open(record.storage_key)


def test_current_manifest_only_protects_referenced_objects_and_stale_cache_retires(
    execution_project, tmp_path
):
    from videotranslate.execution.inputs import set_inputs

    ctx, op, audio = prepared(execution_project, tmp_path)
    extra = store_audio(ctx, op.id, audio, "vocals")
    current = store_audio(ctx, op.id, audio, "instrumental")
    Operations(ctx).cache({"objects": [current]}, {"object_count": 1})
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
    assert 1 in [collect(ctx) for _ in range(3)]
    with ctx.session_factory() as db:
        assert db.get(PreparedObject, extra).state == "deleted"
        assert db.get(PreparedObject, current).state == "orphan"
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        set_inputs(db, db.get(Project, run.project_id), {"source.video": "replacement"})
    assert 1 in [collect(ctx) for _ in range(3)]
    with ctx.session_factory() as db:
        assert db.get(PreparedObject, current).state == "deleted"


@pytest.mark.parametrize("speaker", [0, 4294967295])
def test_nvidia_uint32_speaker_ids_remain_numeric_in_normalized_originals(speaker):
    from videotranslate.dubbing.analysis_contracts import NormalizedTranscript
    from videotranslate.providers.nvidia_stream import normalize_final

    rows = normalize_final(
        {
            "type": "result",
            "isFinal": True,
            "receivedAudioMs": 5000,
            "segments": [
                {"startTime": 0.8, "endTime": 5.04, "speaker": speaker, "text": "Fixture words"}
            ],
        }
    )
    payload = NormalizedTranscript.model_validate(
        {"selection_id": "selection", "segments": rows}
    ).model_dump(exclude_none=True)
    assert type(payload["segments"][0]["speaker"]) is int
    assert payload["segments"][0]["speaker"] == speaker and payload["segments"][0]["end"] == 5.04


@pytest.mark.parametrize("speaker", [True, False, -1, 4294967296, 0.0])
def test_nvidia_rejects_invalid_numeric_speaker_ids(speaker):
    from videotranslate.providers.nvidia_stream import normalize_final

    with pytest.raises(ValueError):
        normalize_final(
            {
                "type": "result",
                "isFinal": True,
                "receivedAudioMs": 5000,
                "segments": [
                    {"startTime": 0.8, "endTime": 5.04, "speaker": speaker, "text": "Fixture words"}
                ],
            }
        )


def test_nvidia_frame_tail_is_explicitly_bounded_and_originals_are_immutable(
    dubbing_project, monkeypatch, tmp_path
):
    import subprocess

    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.dubbing import TranscriptRevision
    from videotranslate.providers.nvidia_stream import normalize_final

    client, headers, _ = dubbing_project
    path = tmp_path / "five.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=32x32:r=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    base = f"/api/projects/{dubbing_project[2]['id']}"
    p = client.post(
        base + "/source",
        headers=headers,
        files={"file": ("five.mp4", path.read_bytes(), "video/mp4")},
    ).json()["project"]
    assert client.post(base + "/runs", headers=headers, json={"stage": "probe"}).status_code == 201
    worker = Worker(client.app.state.settings)
    assert worker.run_once()
    fixture = client, headers, p
    selected(fixture)
    current = client.get(base).json()
    assert (
        client.patch(
            base, headers=headers, json={"revision": current["revision"], "source_language": "en"}
        ).status_code
        == 200
    )
    configure_remote(fixture, adapter="nvidia_stream")
    recording_provider(monkeypatch, client)

    def stream(pcm, **kw):
        assert len(pcm) == 5000 * 32
        kw["before_send"]()
        return normalize_final(
            {
                "type": "result",
                "isFinal": True,
                "receivedAudioMs": 5000,
                "segments": [
                    {"startTime": 0.8, "endTime": 5.04, "speaker": 0, "text": "Fixture words"}
                ],
            }
        )

    monkeypatch.setattr("videotranslate.providers.nvidia_stream.stream_remote", stream)
    analysis(fixture)
    for _ in range(3):
        assert worker.run_once()
    result = timeline(fixture)
    assert result["segments"][0]["end_ms"] == 5000
    assert "provider_end_clipped" in result["segments"][0]["source_analysis_flags"]
    assert result["cast"][0]["name"] == "0"
    with client.app.state.session_factory() as db:
        original = db.get(TranscriptRevision, result["transcript"]["id"]).original_segments[0]
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.provider == "nvidia_stream")
        )
        assert (
            original["end"] == 5.04
            and type(original["speaker"]) is int
            and original["speaker"] == 0
        )
        assert operation.prepared_payload["segments"][0] == original


def test_frame_tail_tolerance_is_nvidia_only_and_over_50ms_is_rejected():
    from videotranslate.dubbing.analysis import working_timings
    from videotranslate.providers.nvidia_stream import normalize_final

    with pytest.raises(ValueError):
        normalize_final(
            {
                "type": "result",
                "isFinal": True,
                "receivedAudioMs": 5000,
                "segments": [
                    {"startTime": 0.8, "endTime": 5.051, "speaker": 0, "text": "Fixture words"}
                ],
            }
        )
    with pytest.raises(ValueError):
        working_timings([{"start": 0.8, "end": 5.04}], 5000, "hf_asr")
    with pytest.raises(ValueError):
        working_timings([{"start": 0.8, "end": 5.051}], 5000, "nvidia_stream")


def test_partial_stem_download_retry_collects_superseded_audio_without_another_model_call(
    dubbing_project, monkeypatch
):
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.providers.contracts import ProviderError

    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)
    download = provider.download
    calls = 0

    def fail_second(self, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProviderError("network")
        return download(self, url, **kwargs)

    monkeypatch.setattr(provider, "download", fail_second)
    response = client.post(
        f"/api/projects/{p['id']}/workflow",
        headers=headers,
        json={
            "action": "prepare_media",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    assert response.status_code == 202
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    sf = client.app.state.session_factory
    with sf.begin() as db:
        run = db.scalar(
            select(StageRun).where(StageRun.project_id == p["id"], StageRun.stage == "separate")
        )
        assert run.status == "retry_wait"
        run.due_at = utcnow()
    assert worker.run_once()
    with sf() as db:
        run = db.get(StageRun, run.id)
        assert run.status == "succeeded"
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run.id))
        extra = db.scalar(
            select(PreparedObject).where(
                PreparedObject.operation_id == op.id, PreparedObject.state == "orphan"
            )
        )
        assert extra.id not in op.prepared_payload["objects"]
        published = db.scalars(
            select(PreparedObject).where(
                PreparedObject.operation_id == op.id, PreparedObject.state == "published"
            )
        ).all()
        assert len(published) == 2
    for _ in range(4):
        cleanup_orphans(
            sf,
            client.app.state.storage,
            workspace_id=run.workspace_id,
            before=utcnow() + timedelta(days=1),
            limit=1,
        )
    with sf() as db:
        assert db.get(PreparedObject, extra.id).state == "deleted"
        assert all(db.get(PreparedObject, row.id).state == "published" for row in published)
    with pytest.raises(FileNotFoundError):
        client.app.state.storage.open(extra.storage_key)
    for row in published:
        with client.app.state.storage.open(row.storage_key) as source:
            assert source.read(4) == b"RIFF"
    assert len([url for url in provider.posts if "/call/predict" in url]) == 1


def test_prepared_tombstones_and_protected_arrivals_cannot_starve_each_other(
    execution_project, tmp_path
):
    import io

    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.core import new_id

    ctx, op, audio = prepared(execution_project, tmp_path)
    tombstone = store_audio(ctx, op.id, audio, "asr_audio")
    protected = store_audio(ctx, op.id, audio, "asr_audio")
    Operations(ctx).cache({"objects": [protected]}, {"object_count": 1})
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
        row = db.get(PreparedObject, tombstone)
        row.state, row.write_settled = "deleted", False
    ctx.storage.put(row.storage_key, io.BytesIO(b"late bytes"), "audio/wav")
    garbage = new_id()
    key = f"{row.workspace_id}/{row.project_id}/prepared/{garbage}"
    ctx.storage.put(key, io.BytesIO(b"garbage"), "audio/wav")
    with ctx.session_factory.begin() as db:
        db.add(
            PreparedObject(
                id=garbage,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                operation_id=op.id,
                storage_key=key,
                state="orphan",
                write_settled=True,
            )
        )
    counts = []
    for _ in range(5):
        # New protected arrivals must not jump ahead of older candidates forever.
        with ctx.session_factory.begin() as db:
            new = new_id()
            db.add(
                PreparedObject(
                    id=new,
                    workspace_id=row.workspace_id,
                    project_id=row.project_id,
                    operation_id=op.id,
                    storage_key=f"{row.workspace_id}/{row.project_id}/prepared/{new}",
                    state="orphan",
                    write_settled=True,
                )
            )
            operation = db.get(PrivateOperation, op.id)
            operation.prepared_payload = {"objects": operation.prepared_payload["objects"] + [new]}
        counts.append(collect(ctx))
    assert 1 in counts
    with pytest.raises(FileNotFoundError):
        ctx.storage.open(row.storage_key)
    with pytest.raises(FileNotFoundError):
        ctx.storage.open(key)
    with ctx.session_factory() as db:
        assert db.get(PreparedObject, protected).state == "orphan"
        assert db.get(PreparedObject, garbage).state == "deleted"


def test_gc_refreshes_manifest_after_waiting_for_project_lock(
    execution_project, tmp_path, monkeypatch
):
    from videotranslate.execution import prepared_objects
    from videotranslate.models.analysis import PrivateOperation

    ctx, op, audio = prepared(execution_project, tmp_path)
    object_id = store_audio(ctx, op.id, audio, "asr_audio")
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
    original = prepared_objects._lock_run_project
    changed = False

    def commit_cache_before_lock(db, run_id):
        nonlocal changed
        if not changed:
            changed = True
            # Another worker commits success after GC reads the operation but
            # before GC obtains the project lock. The locked read must refresh it.
            with ctx.session_factory.begin() as other:
                current = other.get(PrivateOperation, op.id)
                current.phase, current.prepared_payload = "prepared", {"objects": [object_id]}
                other.get(StageRun, run_id).remote_state = "completed"
        return original(db, run_id)

    monkeypatch.setattr(prepared_objects, "_lock_run_project", commit_cache_before_lock)
    assert collect(ctx) == 0
    with ctx.session_factory() as db:
        assert db.get(PreparedObject, object_id).state == "orphan"

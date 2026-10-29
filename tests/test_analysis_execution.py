"""Recovery tests use contract doubles, never actual paid inference."""

from datetime import timedelta

from videotranslate.execution.context import RunContext
from videotranslate.execution.contracts import RunCreate, StageResult
from videotranslate.execution.registry import STAGES, StageDefinition
from videotranslate.execution.service import claim_run, create_run, retry_run
from videotranslate.execution.worker import Worker
from videotranslate.models.core import Project, utcnow
from videotranslate.models.execution import StageRun


def claimed(client, project):
    sf = client.app.state.session_factory
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        run_id = create_run(db, p.workspace_id, p.id, RunCreate(stage="probe")).id
        lease = claim_run(db, "first")
    return RunContext(
        sf, client.app.state.storage, client.app.state.settings, run_id, lease.lease_token
    )


def test_private_payload_is_not_public_and_recovery_keeps_generation(execution_project):
    from videotranslate.execution.prepared import Operations

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    operation = ops.prepare(
        provider="hf_router",
        model="test/model",
        connection_revision=7,
        host="https://router.huggingface.co",
        prefix="/hf-inference",
    )
    ops.begin()
    result = ops.cache(
        {"segments": [{"text": "private dialogue", "start": 0, "end": 1}]}, {"segment_count": 1}
    )
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        assert run.remote_id is None and run.remote_state == "completed"
        generation = run.request_key
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
    seen = []
    stage = STAGES["probe"]

    def handle(restarted):
        store = Operations(restarted)
        recovered = store.cached()
        seen.append(store.payload(recovered.prepared_id))
        return recovered

    registry = {
        "probe": StageDefinition("probe", stage.validate_options, stage.resolve_inputs, handle)
    }
    assert Worker(ctx.settings, registry=registry).run_once()
    public = client.get(f"/api/runs/{ctx.run_id}").json()
    assert public["status"] == "succeeded" and public["result"] == {"segment_count": 1}
    assert "private dialogue" not in str(public) and "router.huggingface.co" not in str(public)
    assert seen[0]["segments"][0]["text"] == "private dialogue"
    with ctx.session_factory() as db:
        run = db.get(StageRun, ctx.run_id)
        assert run.request_key == generation
    assert result.prepared_id == operation.id


def test_failed_publication_retry_reuses_private_success(execution_project):
    from videotranslate.execution.prepared import Operations

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    ops.prepare(
        provider="hf_router",
        model="test/model",
        connection_revision=1,
        host="https://router.huggingface.co",
        prefix="/hf-inference",
    )
    ops.begin()
    ops.cache({"segments": []}, {"segment_count": 0})
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        key = run.request_key
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
        retry_run(db, run.workspace_id, run.id)
        assert run.request_key == key
    with ctx.session_factory.begin() as db:
        lease = claim_run(db, "second")
    resumed = Operations(
        RunContext(ctx.session_factory, ctx.storage, ctx.settings, ctx.run_id, lease.lease_token)
    )
    assert resumed.cached().facts == {"segment_count": 0}


def test_terminal_files_saved_before_download_and_old_host_is_retained(execution_project):
    from videotranslate.execution.prepared import Operations

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    ops.prepare(
        provider="demucs",
        model="htdemucs_ft",
        connection_revision=2,
        host="https://old.hf.space",
        prefix="/gradio_api",
    )
    ops.begin()
    ops.accept("real-job-1")
    ops.terminal(
        {
            "vocals": {"path": "/tmp/private-vocals.wav"},
            "instrumental": {"path": "/tmp/private-music.wav"},
        }
    )
    recovered = Operations(ctx).current()
    assert recovered.host == "https://old.hf.space" and recovered.prefix == "/gradio_api"
    assert recovered.remote_id == "real-job-1" and recovered.connection_revision == 2
    assert recovered.terminal_payload["vocals"]["path"] == "/tmp/private-vocals.wav"
    public = client.get(f"/api/runs/{ctx.run_id}").json()
    assert "private-vocals" not in str(public) and "old.hf.space" not in str(public)


def test_known_terminal_failure_can_retry_new_generation(execution_project):
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import fail_run

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    original = ops.prepare(
        provider="demucs",
        model="htdemucs_ft",
        connection_revision=2,
        host="https://old.hf.space",
        prefix="/gradio_api",
    )
    ops.begin()
    ops.accept("dead-job")
    ops.failed()
    with ctx.session_factory.begin() as db:
        fail_run(db, ctx.run_id, ctx.lease_token, StageFailure(FailureCode.INVALID_MEDIA))
        run = db.get(StageRun, ctx.run_id)
        assert run.remote_state == "completed"
        retry_run(db, run.workspace_id, run.id)
        assert run.request_key != original.generation
        assert run.remote_id is None


def test_changed_inputs_cannot_reuse_cached_payload(execution_project):
    from videotranslate.execution.inputs import set_inputs
    from videotranslate.execution.prepared import Operations

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    ops.prepare(
        provider="hf_router",
        model="test/model",
        connection_revision=1,
        host="https://router.huggingface.co",
        prefix="/hf-inference",
    )
    ops.begin()
    ops.cache({"segments": []}, {"segment_count": 0})
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        key = run.request_key
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "changed"})
        retry_run(db, run.workspace_id, run.id)
        assert run.request_key != key
        lease = claim_run(db, "second")
    resumed = Operations(
        RunContext(ctx.session_factory, ctx.storage, ctx.settings, ctx.run_id, lease.lease_token)
    )
    assert resumed.cached() is None


def test_terminal_download_failure_retry_reuses_known_files(execution_project):
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import fail_run

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    original = ops.prepare(
        provider="demucs",
        model="htdemucs_ft",
        connection_revision=2,
        host="https://old.hf.space",
        prefix="/gradio_api",
    )
    ops.begin()
    ops.accept("job-files")
    ops.terminal({"vocals": {"path": "/tmp/v.wav"}, "instrumental": {"path": "/tmp/i.wav"}})
    with ctx.session_factory.begin() as db:
        fail_run(
            db, ctx.run_id, ctx.lease_token, StageFailure(FailureCode.TRANSIENT, retryable=True)
        )
        run = db.get(StageRun, ctx.run_id)
        run.status = "failed"
        retry_run(db, run.workspace_id, run.id)
        assert run.request_key == original.generation and run.remote_id == "job-files"


def test_publication_guard_is_atomic_and_prevents_all_publisher_writes(execution_project):
    from videotranslate.execution.service import finish_run

    client, _, project = execution_project
    ctx = claimed(client, project)
    called = []
    stage = STAGES["probe"]
    registry = {
        "probe": StageDefinition(
            "probe",
            stage.validate_options,
            stage.resolve_inputs,
            lambda _: StageResult({}),
            lambda *args: called.append(True),
            publication_guard=lambda *args: False,
        )
    }
    with ctx.session_factory.begin() as db:
        assert finish_run(
            db, ctx.run_id, ctx.lease_token, StageResult({"safe": True}), registry=registry
        )
        assert db.get(StageRun, ctx.run_id).status == "stale"
    assert called == []


def test_pending_jobs_can_wait_beyond_auto_failure_budget(execution_project):
    from videotranslate.execution.contracts import StagePending

    client, _, project = execution_project
    ctx = claimed(client, project)
    ctx.begin_submission("provider", "model")
    ctx.record_submission("long-public-job")
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
    stage = STAGES["probe"]

    def wait(context):
        assert context.remote_checkpoint() == "long-public-job"
        raise StagePending()

    registry = {
        "probe": StageDefinition("probe", stage.validate_options, stage.resolve_inputs, wait)
    }
    worker = Worker(ctx.settings, registry=registry)
    for _ in range(5):
        assert worker.run_once()
        with ctx.session_factory.begin() as db:
            run = db.get(StageRun, ctx.run_id)
            assert run.status == "retry_wait" and run.auto_failures == 0
            run.due_at = utcnow()


def test_ready_unsubmitted_operation_changes_generation_on_new_inputs(execution_project):
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.inputs import set_inputs
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import fail_run

    client, _, project = execution_project
    ctx = claimed(client, project)
    first = Operations(ctx).prepare(provider="cpu", model="ffmpeg")
    with ctx.session_factory.begin() as db:
        fail_run(db, ctx.run_id, ctx.lease_token, StageFailure(FailureCode.INVALID_MEDIA))
        run = db.get(StageRun, ctx.run_id)
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "changed"})
        retry_run(db, run.workspace_id, run.id)
        lease = claim_run(db, "new-inputs")
    resumed = RunContext(
        ctx.session_factory, ctx.storage, ctx.settings, ctx.run_id, lease.lease_token
    )
    second = Operations(resumed).prepare(provider="cpu", model="ffmpeg")
    assert first.generation != second.generation and first.id != second.id


def test_orphan_cleanup_keeps_recoverable_cache_and_only_deletes_old_unpublished_generation(
    execution_project, tmp_path
):
    import hashlib

    from videotranslate.execution.inputs import set_inputs
    from videotranslate.execution.prepared import Operations, cleanup_orphans, store_audio
    from videotranslate.media.audio import AudioFile
    from videotranslate.models.analysis import PreparedObject

    client, _, project = execution_project
    ctx = claimed(client, project)
    op = Operations(ctx)
    generation = op.prepare(provider="cpu", model="ffmpeg")
    path = tmp_path / "prepared.wav"
    path.write_bytes(b"a validated test object")
    audio = AudioFile(
        path, 1, 16000, 1, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()
    )
    object_id = store_audio(ctx, generation.id, audio, "asr_audio")
    op.cache({"objects": [object_id]}, {"object_count": 1})
    with ctx.session_factory.begin() as db:
        run = db.get(StageRun, ctx.run_id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
        workspace = run.workspace_id
    assert (
        cleanup_orphans(
            ctx.session_factory,
            ctx.storage,
            workspace_id=workspace,
            before=utcnow() + timedelta(days=1),
        )
        == 0
    )
    with ctx.session_factory.begin() as db:
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "changed"})
        run = db.get(StageRun, ctx.run_id)
        retry_run(db, run.workspace_id, run.id)
        run.status = "failed"
    assert (
        cleanup_orphans(
            ctx.session_factory,
            ctx.storage,
            workspace_id=workspace,
            before=utcnow() + timedelta(days=1),
        )
        == 1
    )
    with ctx.session_factory() as db:
        record = db.get(PreparedObject, object_id)
        assert record.state == "deleted"
        import pytest

        with pytest.raises(FileNotFoundError):
            ctx.storage.open(record.storage_key)


def test_abandoned_writing_reservation_is_cleanable_after_lease_expiry(execution_project, tmp_path):
    import hashlib

    from videotranslate.execution.prepared import Operations, cleanup_orphans, store_audio
    from videotranslate.media.audio import AudioFile
    from videotranslate.models.analysis import PreparedObject

    client, _, project = execution_project
    ctx = claimed(client, project)
    operation = Operations(ctx).prepare(provider="cpu", model="ffmpeg")
    path = tmp_path / "object"
    path.write_bytes(b"prepared")
    object_id = store_audio(
        ctx,
        operation.id,
        AudioFile(path, 1, 16000, 1, 8, hashlib.sha256(b"prepared").hexdigest()),
        "asr_audio",
    )
    with ctx.session_factory.begin() as db:
        record = db.get(PreparedObject, object_id)
        record.state = "writing"  # crash before the post-storage checkpoint
        run = db.get(StageRun, ctx.run_id)
        workspace_id = run.workspace_id
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
    assert (
        cleanup_orphans(
            ctx.session_factory,
            ctx.storage,
            workspace_id=workspace_id,
            before=utcnow() + timedelta(days=1),
        )
        == 1
    )


def test_poll_auth_failure_retains_already_paid_handle_and_generation(execution_project):
    from videotranslate.dubbing.analysis import provider_failure
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import fail_run
    from videotranslate.providers.contracts import ProviderError

    client, _, project = execution_project
    ctx = claimed(client, project)
    ops = Operations(ctx)
    operation = ops.prepare(
        provider="demucs",
        model="htdemucs_ft",
        connection_revision=3,
        host="https://saved.hf.space",
        prefix="/gradio_api",
    )
    ops.begin()
    ops.accept("already-paid-job")
    failure = provider_failure(ops, ProviderError("auth"))
    with ctx.session_factory.begin() as db:
        fail_run(db, ctx.run_id, ctx.lease_token, failure)
        run = db.get(StageRun, ctx.run_id)
        retry_run(db, run.workspace_id, run.id)
        assert run.remote_id == "already-paid-job" and run.request_key == operation.generation


def test_materialized_media_must_match_immutable_source_hash(execution_project, tmp_path):
    import pytest

    from videotranslate.dubbing.analysis import materialize
    from videotranslate.execution.contracts import FailureCode, StageFailure

    client, _, project = execution_project
    ctx = claimed(client, project)
    asset = ctx.source_asset()
    asset.sha256 = "0" * 64
    with pytest.raises(StageFailure) as error:
        materialize(ctx, asset, tmp_path / "source", max_bytes=1000000)
    assert error.value.code == FailureCode.INVALID_MEDIA

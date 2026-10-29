"""Durable analysis intents and source editor protection; no actual inference."""

from dubbing_helpers import create_line, selected
from sqlalchemy import select

from videotranslate.execution.worker import Worker
from videotranslate.models.core import Asset
from videotranslate.models.execution import StageRun


def timeline(fixture):
    client, _, p = fixture
    return client.get(f"/api/projects/{p['id']}/timeline").json()


def test_media_only_intent_queues_real_extraction_and_does_not_require_asr(dubbing_project):
    fixture = dubbing_project
    client, headers, p = fixture
    selected(fixture)
    base = f"/api/projects/{p['id']}"
    # Manual source for a language outside NVIDIA is permitted to prepare media.
    current = client.get(base).json()
    response = client.patch(
        base, headers=headers, json={"revision": current["revision"], "source_language": "ja"}
    )
    assert response.status_code == 200
    body = {
        "action": "prepare_media",
        "expected_editor_fingerprint": timeline(fixture)["editor_fingerprint"],
    }
    first = client.post(base + "/workflow", headers=headers, json=body)
    assert first.status_code == 202, first.text
    duplicate = client.post(base + "/workflow", headers=headers, json=body)
    assert duplicate.status_code == 202 and duplicate.json()["id"] == first.json()["id"]
    assert first.json()["stage"] == "extract"
    assert Worker(client.app.state.settings).run_once()
    status = client.get(base + "/workflow/" + first.json()["id"]).json()
    # Separation needs an explicit configured remote connection, never a fake background.
    assert status["status"] == "paused" and status["next_action"] == "configure_separation"
    sf = client.app.state.session_factory
    with sf() as db:
        runs = db.scalars(select(StageRun).where(StageRun.project_id == p["id"])).all()
        extract = next(r for r in runs if r.stage == "extract")
        assert extract.status == "succeeded" and not extract.is_stale
        assert extract.result["duration_ms"] == 2000
        assert all(r.stage != "transcribe" for r in runs)
        assets = db.scalars(select(Asset).where(Asset.project_id == p["id"])).all()
        assert {a.kind for a in assets} == {"source_video", "working_audio", "asr_audio"}
    assert "storage_key" not in str(status) and "private" not in str(status)


def test_old_browser_cannot_enqueue_replacement_after_manual_edit(dubbing_project):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    before = timeline(dubbing_project)
    create_line(dubbing_project, selection, text="A manual edit")
    response = client.post(
        f"/api/projects/{p['id']}/workflow",
        headers=headers,
        json={"action": "analyse", "expected_editor_fingerprint": before["editor_fingerprint"]},
    )
    assert response.status_code == 409


def test_editor_fingerprint_covers_source_and_cast_but_excludes_targets(dubbing_project):
    client, headers, p = dubbing_project
    selected(dubbing_project)
    base = f"/api/projects/{p['id']}"
    before = timeline(dubbing_project)["editor_fingerprint"]
    response = client.post(base + "/language-tracks", headers=headers, json={"tag": "ja"})
    assert response.status_code == 201
    assert timeline(dubbing_project)["editor_fingerprint"] == before
    role = client.post(base + "/speakers", headers=headers, json={"name": "Human role"})
    assert role.status_code == 201
    after = timeline(dubbing_project)["editor_fingerprint"]
    assert after != before
    role = role.json()
    assert (
        client.patch(
            base + "/speakers/" + role["id"],
            headers=headers,
            json={"revision": role["revision"], "name": "Renamed"},
        ).status_code
        == 200
    )
    assert timeline(dubbing_project)["editor_fingerprint"] != after


def configure_remote(fixture, adapter="hf_asr"):
    client, headers, _ = fixture
    assert (
        client.put(
            "/api/providers/separation",
            headers=headers,
            json={
                "revision": 0,
                "adapter": "demucs",
                "space_id": "test/demucs",
                "model": "htdemucs_ft",
            },
        ).status_code
        == 200
    )
    config = {"revision": 0, "adapter": adapter}
    config.update(
        {
            "endpoint": "https://router.huggingface.co/v1",
            "model": "openai/whisper-large-v3",
            "credential_ref": "huggingface",
        }
        if adapter == "hf_asr"
        else {
            "space_id": "nvidia/nemotron-diarization",
            "endpoint": "https://nvidia-nemotron-diarization.hf.space",
            "model": "nemotron-diarization",
        }
    )
    assert (
        client.put("/api/providers/transcription", headers=headers, json=config).status_code == 200
    )
    if adapter == "hf_asr":
        assert (
            client.put(
                "/api/credentials/huggingface",
                headers=headers,
                json={"revision": 0, "token": "isolated-test-token"},
            ).status_code
            == 200
        )


def recording_provider(monkeypatch, client, *, on_asr=None, download_fails=False):
    """Explicit contract double returns the actual prepared WAV as distinct stems."""
    import json
    import tempfile
    from pathlib import Path

    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.providers.contracts import ProviderError

    class Recording:
        allowed_hosts = set()
        posts, polls, downloads = [], [], []
        audio = b""
        failed = False

        def get(self, url, **kw):
            if "api/spaces" in url:
                return b'{"host":"https://saved-demucs.hf.space"}'
            return b'{"named_endpoints":{"/predict":{"parameters":[{"parameter_name":"audio"}],"returns":[{"component":"Audio","label":"Vocals"},{"component":"Audio","label":"Instrumental"}]}}}'

        def upload(self, url, **kw):
            type(self).audio = kw["content"]
            assert kw["filename"] == "audio.wav"
            return ["/tmp/upload.wav"]

        def post_json(self, url, body, **kw):
            with client.app.state.session_factory() as db:
                rows = db.scalars(select(PrivateOperation)).all()
                assert any(row.phase == "submitting" for row in rows)
            self.posts.append(url)
            if url.endswith("/call/predict"):
                return b'{"event_id":"actual-remote-id"}'
            assert url.endswith("/hf-inference/models/openai/whisper-large-v3")
            assert kw["headers"]["Authorization"] == "Bearer isolated-test-token"
            if on_asr:
                on_asr()
            return json.dumps(
                {
                    "text": "actual contract response",
                    "chunks": [{"text": "private exact words", "timestamp": [0.1, 1.0]}],
                }
            ).encode()

        def get_sse(self, url, **kw):
            self.polls.append(url)
            return b'event: complete\ndata: [{"path":"/tmp/vocals.wav"},{"path":"/tmp/instrumental.wav"}]\n\n'

        def download(self, url, **kw):
            self.downloads.append(url)
            if download_fails and not type(self).failed:
                type(self).failed = True
                raise ProviderError("network")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
                out.write(self.audio)
                return Path(out.name)

        def close(self):
            pass

    monkeypatch.setattr("videotranslate.dubbing.analysis.make_http", lambda _: Recording())
    return Recording


def test_durable_real_stages_publish_exact_hf_source_without_inventing_speakers(
    dubbing_project, monkeypatch
):
    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)
    base = f"/api/projects/{p['id']}"
    response = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "analyse",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    assert response.status_code == 202, response.text
    worker = Worker(client.app.state.settings)
    for _ in range(3):
        assert worker.run_once()
    current = timeline(dubbing_project)
    assert current["transcript"]["provenance"] == "provider"
    assert len(current["segments"]) == 1 and current["cast"] == []
    assert current["segments"][0]["text"] == "private exact words"
    assert current["segments"][0]["speaker_id"] is None
    assert current["segments"][0]["start_ms"] == 100
    status = client.get(base + "/workflow/" + response.json()["id"]).json()
    assert status["status"] == "review" and status["next_action"] == "source_and_cast_review"
    assert len(provider.posts) == 2 and len(provider.polls) == 1
    with client.app.state.session_factory() as db:
        runs = db.scalars(select(StageRun).where(StageRun.project_id == p["id"])).all()
        assert all(r.status == "succeeded" and not r.is_stale for r in runs)
        assert all("private exact words" not in str(r.result) for r in runs)


def test_asr_publication_cannot_overwrite_edit_made_after_command(dubbing_project, monkeypatch):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    configure_remote(dubbing_project)

    def edit():
        create_line(dubbing_project, selection, text="preserved human correction")

    provider = recording_provider(monkeypatch, client, on_asr=edit)
    base = f"/api/projects/{p['id']}"
    response = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "analyse",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    assert response.status_code == 202
    worker = Worker(client.app.state.settings)
    for _ in range(3):
        assert worker.run_once()
    current = timeline(dubbing_project)
    assert current["segments"][0]["text"] == "preserved human correction"
    status = client.get(base + "/workflow/" + response.json()["id"]).json()
    assert status["status"] == "stale"
    assert len(provider.posts) == 2


def test_prepare_and_analyse_share_media_paid_job_and_reuse_after_asr_settings_change(
    dubbing_project, monkeypatch
):
    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)
    base = f"/api/projects/{p['id']}"
    proof = timeline(dubbing_project)["editor_fingerprint"]
    prepare = client.post(
        base + "/workflow",
        headers=headers,
        json={"action": "prepare_media", "expected_editor_fingerprint": proof},
    )
    analyse = client.post(
        base + "/workflow",
        headers=headers,
        json={"action": "analyse", "expected_editor_fingerprint": proof},
    )
    assert prepare.status_code == analyse.status_code == 202
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    assert sum(url.endswith("/call/predict") for url in provider.posts) == 1
    with client.app.state.session_factory() as db:
        assert (
            len(
                db.scalars(
                    select(StageRun).where(
                        StageRun.project_id == p["id"], StageRun.stage == "extract"
                    )
                ).all()
            )
            == 1
        )
    # Only ASR settings changed. Media-only command keeps identity and paid separation.
    config = {
        "revision": 1,
        "adapter": "hf_asr",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
    }
    assert (
        client.put("/api/providers/transcription", headers=headers, json=config).status_code == 200
    )
    again = client.post(
        base + "/workflow",
        headers=headers,
        json={"action": "prepare_media", "expected_editor_fingerprint": proof},
    )
    assert again.status_code == 202 and again.json()["id"] == prepare.json()["id"]
    new_analysis = client.post(
        base + "/workflow",
        headers=headers,
        json={"action": "analyse", "expected_editor_fingerprint": proof},
    )
    assert new_analysis.status_code == 202
    status = client.get(base + "/workflow/" + new_analysis.json()["id"]).json()
    assert status["stage"] == "transcribe"
    assert sum(url.endswith("/call/predict") for url in provider.posts) == 1


def test_known_terminal_files_survive_download_retry_without_second_sse_or_post(
    dubbing_project, monkeypatch
):
    from videotranslate.models.core import utcnow

    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client, download_fails=True)
    response = client.post(
        f"/api/projects/{p['id']}/workflow",
        headers=headers,
        json={
            "action": "prepare_media",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    with client.app.state.session_factory.begin() as db:
        run = db.scalar(
            select(StageRun).where(StageRun.project_id == p["id"], StageRun.stage == "separate")
        )
        assert run.status == "retry_wait"
        run.due_at = utcnow()
    assert worker.run_once()
    assert len(provider.posts) == len(provider.polls) == 1
    status = client.get(f"/api/projects/{p['id']}/workflow/{response.json()['id']}").json()
    assert status["status"] == "review"


def test_terminal_child_failure_and_explicit_retry_update_durable_intent(
    dubbing_project, monkeypatch
):
    from videotranslate.providers.contracts import ProviderTerminalError

    client, headers, project = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)
    original = provider.get_sse

    def terminal_failure(self, url, **kw):
        raise ProviderTerminalError()

    monkeypatch.setattr(provider, "get_sse", terminal_failure)
    base = f"/api/projects/{project['id']}"
    response = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "prepare_media",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    current = client.get(base + "/workflow/" + response.json()["id"]).json()
    assert current["status"] == "failed" and current["next_action"] == "review_run"
    with client.app.state.session_factory() as db:
        run = db.scalar(
            select(StageRun).where(
                StageRun.project_id == project["id"], StageRun.stage == "separate"
            )
        )
        run_id = run.id
    monkeypatch.setattr(provider, "get_sse", original)
    assert (
        client.post("/api/runs/" + run_id + "/retry", headers=headers, json={}).status_code == 200
    )
    assert client.get(base + "/workflow/" + response.json()["id"]).json()["status"] == "running"
    assert worker.run_once()
    assert client.get(base + "/workflow/" + response.json()["id"]).json()["status"] == "review"


def test_invalid_terminal_stem_is_retryable_as_new_job_not_dead_poll(dubbing_project, monkeypatch):
    from videotranslate.models.analysis import PrivateOperation

    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)
    original = provider.download

    def broken_audio(self, url, **kw):
        path = original(self, url, **kw)
        path.write_bytes(b"not decodable provider media")
        return path

    monkeypatch.setattr(provider, "download", broken_audio)
    base = f"/api/projects/{p['id']}"
    queued = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "prepare_media",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    with client.app.state.session_factory() as db:
        run = db.scalar(
            select(StageRun).where(StageRun.project_id == p["id"], StageRun.stage == "separate")
        )
        operation = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run.id))
        assert run.status == "failed" and operation.phase == "failed"
        run_id = run.id
    monkeypatch.setattr(provider, "download", original)
    assert (
        client.post("/api/runs/" + run_id + "/retry", headers=headers, json={}).status_code == 200
    )
    assert worker.run_once()
    assert len(provider.posts) == 2
    assert client.get(base + "/workflow/" + queued.json()["id"]).json()["status"] == "review"


def test_private_normalized_source_rejects_invalid_unicode_before_success_cache():
    import pytest

    from videotranslate.dubbing.analysis_contracts import NormalizedTranscript

    with pytest.raises(ValueError):
        NormalizedTranscript.model_validate(
            {
                "selection_id": "selection",
                "segments": [{"start": 0.0, "end": 1.0, "text": "invalid\ud800"}],
            }
        )
    with pytest.raises(ValueError):
        NormalizedTranscript.model_validate(
            {
                "selection_id": "selection",
                "segments": [{"start": 0.0, "end": 0.0, "text": "zero timing"}],
            }
        )


def test_source_edit_after_asr_queue_before_worker_is_durably_stale_without_call(
    dubbing_project, monkeypatch
):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)
    base = f"/api/projects/{p['id']}"
    queued = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "analyse",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    create_line(dubbing_project, selection, text="Preserved before model starts")
    assert worker.run_once()
    current = client.get(base + "/workflow/" + queued.json()["id"]).json()
    assert current["status"] == "stale"
    assert len(provider.posts) == 1
    assert not worker.run_once(), "guard failure must not leave an endlessly reclaimed lease"


def test_generic_asr_entry_cannot_bypass_client_editor_proof(dubbing_project, monkeypatch):
    client, headers, p = dubbing_project
    selected(dubbing_project)
    response = client.post(
        f"/api/projects/{p['id']}/runs", headers=headers, json={"stage": "transcribe"}
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "WORKFLOW_REQUIRED"


def test_new_intent_does_not_resubmit_unresolved_failed_paid_separation(
    dubbing_project, monkeypatch
):
    from videotranslate.providers.contracts import ProviderError

    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    provider = recording_provider(monkeypatch, client)

    def denied_poll(self, url, **kw):
        raise ProviderError("auth")

    monkeypatch.setattr(provider, "get_sse", denied_poll)
    base = f"/api/projects/{p['id']}"
    body = {
        "action": "analyse",
        "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
    }
    assert client.post(base + "/workflow", headers=headers, json=body).status_code == 202
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    second = client.post(
        base + "/workflow", headers=headers, json=body | {"action": "prepare_media"}
    )
    assert second.status_code == 202
    worker.run_once()
    assert len(provider.posts) == 1
    assert client.get(base + "/workflow/" + second.json()["id"]).json()["status"] == "failed"


def test_uncertain_asr_keeps_command_idempotent_and_blocks_new_intent(dubbing_project, monkeypatch):
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import claim_run

    client, headers, p = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project)
    recording_provider(monkeypatch, client)
    base = f"/api/projects/{p['id']}"
    body = {
        "action": "analyse",
        "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
    }
    first = client.post(base + "/workflow", headers=headers, json=body)
    worker = Worker(client.app.state.settings)
    assert worker.run_once() and worker.run_once()
    with client.app.state.session_factory.begin() as db:
        run = claim_run(db, "test-inflight")
    ctx = RunContext(
        client.app.state.session_factory,
        client.app.state.storage,
        client.app.state.settings,
        run.id,
        run.lease_token,
    )
    ops = Operations(ctx)
    ops.prepare(
        provider="hf_asr",
        model="openai/whisper-large-v3",
        connection_revision=1,
        host="https://router.huggingface.co",
        prefix="/hf-inference",
    )
    ops.begin()
    repeated = client.post(base + "/workflow", headers=headers, json=body)
    assert repeated.status_code == 202 and repeated.json()["id"] == first.json()["id"]
    different = client.post(base + "/workflow", headers=headers, json=body | {"auto_advance": True})
    assert (
        different.status_code == 409 and different.json()["error"]["code"] == "SUBMISSION_UNCERTAIN"
    )

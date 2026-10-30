"""Recording Gradio protocol with real CPU audio; never real inference."""
# ruff: noqa: F811

import json

import pytest
from sqlalchemy import select
from test_synthesis_domain import body, path, synthesis_project  # noqa: F401
from test_translation_operations import drain
from test_voice_references import wav_bytes

from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.execution import StageRun


class RecordingClone:
    allowed_hosts = set()

    def __init__(self, root):
        self.root = root
        self.posts, self.uploads, self.gets, self.downloads = [], [], [], []
        self.hook = None
        self.download_failure = False
        self.missing_id = False
        self.pending = False
        self.output = wav_bytes(0.6)
        self.enum = ["Chinese", "Japanese", "English"]

    def close(self):
        pass

    def get(self, url, **kwargs):
        self.gets.append(url)
        if "/api/spaces/" in url:
            return json.dumps(
                {"host": "https://k2-fsa-omnivoice.hf.space", "sha": "actual-model-revision"}
            ).encode()
        params = [
            {"parameter_name": x}
            for x in [
                "text",
                "lang",
                "ref_aud",
                "ref_text",
                "instruct",
                "ns",
                "gs",
                "dn",
                "sp",
                "du",
                "pp",
                "po",
            ]
        ]
        params[1]["type"] = {"enum": self.enum}
        return json.dumps(
            {
                "named_endpoints": {
                    "/_clone_fn": {
                        "parameters": params,
                        "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                    }
                }
            }
        ).encode()

    def upload(self, url, **kwargs):
        self.uploads.append((url, kwargs))
        return ["/remote/private/reference.wav"]

    def post_json(self, url, payload, **kwargs):
        self.posts.append((url, payload))
        if self.hook:
            self.hook()
        return json.dumps(
            {} if self.missing_id else {"event_id": f"actual-event-{len(self.posts)}"}
        )

    def get_sse(self, url, **kwargs):
        self.gets.append(url)
        if self.pending:
            return b"event: heartbeat\ndata: null\n\n"
        return b'event: complete\ndata: [{"path":"/remote/private/generated.wav"},"Done."]\n\n'

    def download(self, url, **kwargs):
        self.downloads.append(url)
        if self.download_failure:
            raise OSError("recorded download loss")
        dest = self.root / f"provider-{len(self.downloads)}.bin"
        dest.write_bytes(self.output)
        return dest


def install_clone(monkeypatch, tmp_path):
    http = RecordingClone(tmp_path)
    monkeypatch.setattr("videotranslate.dubbing.remote_synthesis.make_http", lambda _: http)
    return http


def queue(fixture, **kw):
    c, h, *_ = fixture
    response = c.post(path(fixture) + "/synthesize", headers=h, json=body(fixture, **kw))
    assert response.status_code == 202, response.text
    return response.json()


def history(fixture):
    c, *_ = fixture
    return c.get(path(fixture) + f"/segments/{fixture[4]['id']}/audio-history").json()


def test_natural_output_is_measured_private_selected_and_not_accepted(
    synthesis_project, monkeypatch, tmp_path
):
    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)
    drain(c)
    state = c.get(path(synthesis_project) + "/synthesis/" + request["id"]).json()
    assert state["lines"][0]["status"] == "succeeded", state
    assert len(http.posts) == 1 and len(http.uploads) == 1
    args = http.posts[0][1]["data"]
    assert args[:2] == ["這是目標文字。", "Chinese"]
    assert args[3] == "Human supplied exact words"
    result = history(synthesis_project)
    assert (
        result["selection_revision"] == 1
        and result["selected_output_id"] == result["outputs"][0]["id"]
    )
    output = result["outputs"][0]
    assert output["natural_duration_ms"] == 600
    assert output["slot_duration_ms"] == 800 and output["ratio"] == 0.75
    assert output["measurement"] == "ffprobe_full_decode_sha256_v1"
    assert output["acceptance"] == "not_assessed"
    public = str(c.get(f"/api/projects/{synthesis_project[2]['id']}/events").json())
    assert "Human supplied exact words" not in public and "這是目標文字" not in public
    assert "/remote/private" not in public
    with c.app.state.session_factory() as db:
        op = db.scalar(
            select(PrivateOperation).join(StageRun).where(StageRun.stage == "synthesize")
        )
        assert op.phase == "prepared" and op.remote_id == "actual-event-1"
        assert op.request_payload["prepared"]["metadata_revision"] == "actual-model-revision"
        assert op.request_payload["prepared"]["api_name"] == "_clone_fn"
        assert op.terminal_payload["audio"]["path"] == "/remote/private/generated.wav"
        assert op.prepared_payload["raw_metadata"]["container"] == "wav"


def test_download_retry_resumes_saved_terminal_without_metadata_upload_or_post(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    http.download_failure = True
    request = queue(synthesis_project)
    assert Worker(c.app.state.settings).run_once()
    run_id = request["lines"][0]["run_id"]
    with c.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        assert op.phase == "terminal" and op.terminal_payload["audio"]["path"]
    # Force the retry due for deterministic recorded failure recovery.
    with c.app.state.session_factory.begin() as db:
        from videotranslate.models.core import utcnow

        db.get(StageRun, run_id).due_at = utcnow()
    http.download_failure = False
    before = len(http.gets)
    assert Worker(c.app.state.settings).run_once()
    assert len(http.gets) == before and len(http.posts) == 1 and len(http.uploads) == 1
    assert history(synthesis_project)["selection_revision"] == 1


def test_same_wording_manual_edit_blocks_selection_but_fresh_command_reuses_paid_success(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, _, s, line, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)

    def edit():
        response = c.patch(
            path(synthesis_project) + f"/segments/{line['id']}",
            headers=h,
            json={
                "selection_revision": s["revision"],
                "transcript_revision": line["transcript_revision"],
                "revision": 1,
                "expected_source_text_fingerprint": line["source_text_fingerprint"],
                "text": "這是目標文字。",
                "approved": True,
                "locked": True,
            },
        )
        assert response.status_code == 200

    http.hook = edit
    queue(synthesis_project)
    drain(c)
    assert len(http.posts) == 1
    assert history(synthesis_project)["selected_output_id"] is None
    assert len(history(synthesis_project)["outputs"]) == 1
    request = body(synthesis_project)
    request["segments"][0]["translation_revision"] = 2
    http.hook = None
    response = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert response.status_code == 202, response.text
    drain(c)
    assert len(http.posts) == 1
    assert history(synthesis_project)["selection_revision"] == 1


def test_missing_event_id_requires_explicit_ack_and_no_automatic_resubmit(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    http.missing_id = True
    request = queue(synthesis_project)
    drain(c)
    run_id = request["lines"][0]["run_id"]
    assert len(http.posts) == 1
    assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 409
    http.missing_id = False
    assert (
        c.post(
            f"/api/runs/{run_id}/retry", headers=h, json={"acknowledge_uncertain_submission": True}
        ).status_code
        == 200
    )
    drain(c)
    assert len(http.posts) == 2 and history(synthesis_project)["selection_revision"] == 1


def test_done_corrupt_audio_never_publishes(synthesis_project, monkeypatch, tmp_path):
    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    http.output = b"This is not audio"
    queue(synthesis_project)
    drain(c)
    assert history(synthesis_project)["outputs"] == []
    assert len(http.posts) == 1


def test_slot_edit_recomputes_planning_preserves_uploaded_reference_natural(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, p, s, line, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    before = history(synthesis_project)
    response = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"]) | {"revision": 1, "end_ms": 1200},
    )
    assert response.status_code == 200
    after = history(synthesis_project)
    assert after["selected_output_id"] == before["selected_output_id"]
    assert after["outputs"][0]["slot_duration_ms"] == 1200
    assert after["outputs"][0]["ratio"] == 0.5 and not after["outputs"][0]["stale"]
    request = body(synthesis_project)
    request["segments"][0]["selection_revision"] = 1
    preserved = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert preserved.status_code == 202 and preserved.json()["status"] == "selection_preserved"
    drain(c)
    assert len(http.posts) == 1


def test_explicit_regeneration_is_paid_but_manual_selection_wins_slow_replacement(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, _, s, line, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    original = history(synthesis_project)["selected_output_id"]
    request = body(synthesis_project, replace_selected=True, regenerate=True)
    request["segments"][0]["selection_revision"] = 1

    def choose():
        result = c.put(
            path(synthesis_project) + f"/segments/{line['id']}/audio-selection",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 1,
                "output_id": original,
                "translation_revision": 1,
                "expected_source_text_fingerprint": line["source_text_fingerprint"],
            },
        )
        assert result.status_code == 200, result.text

    http.hook = choose
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )
    drain(c)
    result = history(synthesis_project)
    assert len(http.posts) == 2
    assert result["selected_output_id"] == original and result["selection_revision"] == 2
    assert len(result["outputs"]) == 2 and result["selections"][0]["provenance"] == "manual"


def test_prepared_restart_lease_loss_does_not_resubmit(synthesis_project, monkeypatch, tmp_path):
    from datetime import timedelta

    from videotranslate.dubbing.remote_synthesis import handler
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import claim_run
    from videotranslate.models.core import utcnow

    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)
    sf = c.app.state.session_factory
    with sf.begin() as db:
        run = claim_run(db, "before-crash")
    context = RunContext(sf, c.app.state.storage, c.app.state.settings, run.id, run.lease_token)
    result = handler(context)
    with sf.begin() as db:
        assert db.get(PrivateOperation, result.prepared_id).phase == "prepared"
        db.get(StageRun, run.id).lease_expires_at = utcnow() - timedelta(seconds=1)
    assert Worker(c.app.state.settings).run_once()
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 1
    assert (
        c.get(path(synthesis_project) + "/synthesis/" + request["id"]).json()["lines"][0]["status"]
        == "succeeded"
    )


def test_cancel_after_post_retains_actual_handle_and_terminal_without_selection(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)
    run_id = request["lines"][0]["run_id"]
    http.hook = lambda: c.post(f"/api/runs/{run_id}/cancel", headers=h)
    drain(c)
    with c.app.state.session_factory() as db:
        run = db.get(StageRun, run_id)
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        assert run.status == "cancelled" and run.remote_id == "actual-event-1"
        assert op.remote_id == "actual-event-1" and op.terminal_payload is not None
    assert history(synthesis_project)["selected_output_id"] is None
    assert len(http.posts) == 1


def test_schema_language_rejection_occurs_before_upload_and_named_post(
    synthesis_project, monkeypatch, tmp_path
):
    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    http.enum = ["English"]
    request = queue(synthesis_project)
    drain(c)
    run = c.get("/api/runs/" + request["lines"][0]["run_id"]).json()
    assert run["safe_error"]["code"] == "UNSUPPORTED_LANGUAGE"
    assert http.posts == [] and http.uploads == [] and history(synthesis_project)["outputs"] == []


def test_tampered_wrong_generation_cache_is_not_reused(synthesis_project, monkeypatch, tmp_path):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    with c.app.state.session_factory.begin() as db:
        operation = db.scalar(
            select(PrivateOperation).join(StageRun).where(StageRun.stage == "synthesize")
        )
        operation.generation = "wrong-generation"
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )
    drain(c)
    assert len(http.posts) == 2 and history(synthesis_project)["selection_revision"] == 2


def test_connection_change_during_download_recovery_does_not_redirect_poll(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    http.download_failure = True
    request = queue(synthesis_project)
    assert Worker(c.app.state.settings).run_once()
    result = c.put(
        "/api/providers/synthesis",
        headers=h,
        json={
            "revision": 1,
            "adapter": "omnivoice",
            "space_id": "someone/AnotherSpace",
            "model": "OmniVoice",
            "credential_ref": None,
        },
    )
    assert result.status_code == 200
    with c.app.state.session_factory.begin() as db:
        from videotranslate.models.core import utcnow

        db.get(StageRun, request["lines"][0]["run_id"]).due_at = utcnow()
    http.download_failure = False
    drain(c)
    assert len(http.posts) == 1 and len(http.uploads) == 1
    assert all("AnotherSpace" not in url for url in http.gets + http.downloads)
    assert history(synthesis_project)["selected_output_id"] is None
    assert len(history(synthesis_project)["outputs"]) == 1


def test_two_targets_and_roles_resolve_correct_reference_line_override_isolates_role_edits(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import create_line, guard, make_track

    c, h, p, s, line, _, ref = synthesis_project
    base = f"/api/projects/{p['id']}"
    role = c.post(base + "/speakers", headers=h, json={"name": "Actor"}).json()
    assigned = c.patch(
        base + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"]) | {"revision": 1, "speaker_id": role["id"]},
    )
    assert assigned.status_code == 200
    line2 = create_line(
        (c, h, p),
        s,
        "Second actor",
        transcript=line["transcript_revision"],
        start_ms=800,
        end_ms=1500,
    )["segment"]
    assert (
        c.patch(
            base + f"/segments/{line2['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"]) | {"revision": 1, "speaker_id": role["id"]},
        ).status_code
        == 200
    )
    ref2 = c.post(
        base + f"/references/{ref['reference_id']}/versions",
        headers=h,
        json={
            "parent_version_id": ref["id"],
            "text": "Corrected actor two reference",
            "language": "en",
        },
    ).json()
    binding_path = base + f"/speakers/{role['id']}/reference"
    assert (
        c.put(
            binding_path,
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 0,
                "expected_speaker_revision": role["revision"],
                "reference_version_id": ref2["id"],
            },
        ).status_code
        == 200
    )
    make_track(c, h, base, "ja")
    for tag, targets in (("ja", ("日本語一。", "日本語二。")), ("zh-Hant", (None, "第二個角色。"))):
        for source, target in zip((line, line2), targets, strict=True):
            if target:
                result = c.patch(
                    base + f"/language-tracks/{tag}/segments/{source['id']}",
                    headers=h,
                    json=guard(s, line["transcript_revision"])
                    | {
                        "revision": 0,
                        "expected_source_text_fingerprint": source["source_text_fingerprint"],
                        "text": target,
                        "approved": True,
                    },
                )
                assert result.status_code == 200, result.text
    http = install_clone(monkeypatch, tmp_path)
    request = body(synthesis_project)
    request["segments"].append(
        {
            "id": line2["id"],
            "translation_revision": 1,
            "expected_source_text_fingerprint": line2["source_text_fingerprint"],
            "selection_revision": 0,
        }
    )
    for tag in ("zh-Hant", "ja"):
        assert (
            c.post(base + f"/language-tracks/{tag}/synthesize", headers=h, json=request).status_code
            == 202
        )
    drain(c)
    assert len(http.posts) == 4
    args = [data["data"] for _, data in http.posts]
    assert {(a[0], a[1], a[3]) for a in args} == {
        ("這是目標文字。", "Chinese", "Human supplied exact words"),
        ("第二個角色。", "Chinese", "Corrected actor two reference"),
        ("日本語一。", "Japanese", "Human supplied exact words"),
        ("日本語二。", "Japanese", "Corrected actor two reference"),
    }
    assert (
        c.put(
            binding_path,
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 1,
                "expected_speaker_revision": role["revision"],
                "reference_version_id": ref["id"],
            },
        ).status_code
        == 200
    )
    assert not history(synthesis_project)["outputs"][0]["stale"]
    second = c.get(path(synthesis_project) + f"/segments/{line2['id']}/audio-history").json()
    assert second["outputs"][0]["stale"]
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )
    drain(c)
    assert len(http.posts) == 4


def test_pending_poll_uses_saved_host_after_connection_change(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    http.pending = True
    request = queue(synthesis_project)
    assert Worker(c.app.state.settings).run_once()
    run_id = request["lines"][0]["run_id"]
    with c.app.state.session_factory() as db:
        run = db.get(StageRun, run_id)
        assert run.remote_id == "actual-event-1" and run.remote_state == "submitted"
    assert (
        c.put(
            "/api/providers/synthesis",
            headers=h,
            json={
                "revision": 1,
                "adapter": "omnivoice",
                "space_id": "another/Model",
                "model": "OmniVoice",
                "credential_ref": None,
            },
        ).status_code
        == 200
    )
    with c.app.state.session_factory.begin() as db:
        from videotranslate.models.core import utcnow

        db.get(StageRun, run_id).due_at = utcnow()
    http.pending = False
    drain(c)
    assert len(http.posts) == 1
    assert (
        http.gets[-1]
        == "https://k2-fsa-omnivoice.hf.space/gradio_api/call/_clone_fn/actual-event-1"
    )
    assert history(synthesis_project)["selected_output_id"] is None


def test_raw_mp3_is_normalized_to_verified_wav_with_actual_raw_provenance(
    synthesis_project, monkeypatch, tmp_path
):
    import subprocess

    c, *_ = synthesis_project
    source, mp3 = tmp_path / "raw.wav", tmp_path / "raw.mp3"
    source.write_bytes(wav_bytes(0.6))
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), str(mp3)], check=True)
    http = install_clone(monkeypatch, tmp_path)
    http.output = mp3.read_bytes()
    queue(synthesis_project)
    drain(c)
    result = history(synthesis_project)
    assert len(result["outputs"]) == 1 and result["outputs"][0]["container"] == "wav"
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).join(StageRun).where(StageRun.stage == "synthesize")
        )
        payload = operation.prepared_payload
        assert payload["raw_metadata"]["container"] == "mp3"
        assert payload["raw_metadata"]["sha256"] != payload["metadata"]["sha256"]
        from videotranslate.models.core import Asset

        asset = db.get(Asset, result["outputs"][0]["audio_asset_id"])
        with c.app.state.storage.open(asset.storage_key) as content:
            assert content.read(4) == b"RIFF"


def test_publication_transaction_failure_retains_prepared_success_for_retry(
    synthesis_project, monkeypatch, tmp_path
):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES

    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)

    def fail_publish(*args):
        raise ValueError("injected publication rollback")

    registry = STAGES | {"synthesize": replace(STAGES["synthesize"], publish=fail_publish)}
    assert Worker(c.app.state.settings, registry=registry).run_once()
    run_id = request["lines"][0]["run_id"]
    assert history(synthesis_project)["outputs"] == []
    assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 200
    drain(c)
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 1


def test_late_storage_lease_loss_settles_orphan_and_redownloads_same_terminal(
    synthesis_project, monkeypatch, tmp_path
):
    from datetime import timedelta

    from videotranslate.models.analysis import PreparedObject
    from videotranslate.models.core import utcnow
    from videotranslate.storage import LocalStorage

    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)
    run_id = request["lines"][0]["run_id"]
    original = LocalStorage.put
    once = []

    def lose_lease(storage, key, content, content_type):
        if not once and "/prepared/" in key:
            once.append(key)
            with c.app.state.session_factory.begin() as db:
                db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
        return original(storage, key, content, content_type)

    monkeypatch.setattr(LocalStorage, "put", lose_lease)
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory() as db:
        record = db.scalar(select(PreparedObject).where(PreparedObject.storage_key == once[0]))
        assert record.state == "orphan" and record.write_settled
    assert Worker(c.app.state.settings).run_once()
    assert len(http.posts) == 1 and len(http.downloads) == 2
    assert history(synthesis_project)["selection_revision"] == 1


def test_corrupted_private_cache_evidence_is_rejected_before_reuse(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    with c.app.state.session_factory.begin() as db:
        op = db.scalar(
            select(PrivateOperation).join(StageRun).where(StageRun.stage == "synthesize")
        )
        op.public_facts = {"dialogue": "corrupted evidence"}
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )
    drain(c)
    assert len(http.posts) == 2


def test_preparation_is_durable_before_post_and_ready_restart_does_not_upload_again(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.prepared import Operations
    from videotranslate.models.core import utcnow

    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)
    run_id = request["lines"][0]["run_id"]
    original = Operations.begin

    def fail_before_post(self):
        raise StageFailure(FailureCode.TRANSIENT, retryable=True)

    monkeypatch.setattr(Operations, "begin", fail_before_post)
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory.begin() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        assert op.phase == "ready" and op.request_payload["prepared"]["args"][2]["path"]
        assert op.request_payload["prepared"]["schema_sha256"]
        db.get(StageRun, run_id).due_at = utcnow()
    assert len(http.uploads) == 1 and http.posts == []
    monkeypatch.setattr(Operations, "begin", original)

    def inspect_submission():
        with c.app.state.session_factory() as db:
            op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
            assert (
                op.phase == "submitting"
                and op.request_payload["prepared"]["api_name"] == "_clone_fn"
            )
            assert db.get(StageRun, run_id).remote_state == "submitting"

    http.hook = inspect_submission
    drain(c)
    assert len(http.posts) == 1 and len(http.uploads) == 1
    assert history(synthesis_project)["selection_revision"] == 1


def test_partial_batch_failure_retries_only_failed_line(synthesis_project, monkeypatch, tmp_path):
    from dubbing_helpers import create_line, guard

    c, h, p, s, line, _, ref = synthesis_project
    second = create_line(
        (c, h, p),
        s,
        "Other source",
        transcript=line["transcript_revision"],
        start_ms=900,
        end_ms=1600,
    )["segment"]
    base = f"/api/projects/{p['id']}"
    assert (
        c.put(
            base + f"/segments/{second['id']}/reference",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {"revision": 0, "expected_segment_revision": 1, "reference_version_id": ref["id"]},
        ).status_code
        == 200
    )
    assert (
        c.patch(
            path(synthesis_project) + f"/segments/{second['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 0,
                "expected_source_text_fingerprint": second["source_text_fingerprint"],
                "text": "第二句。",
                "approved": True,
            },
        ).status_code
        == 200
    )
    request = body(synthesis_project)
    request["segments"].append(
        {
            "id": second["id"],
            "translation_revision": 1,
            "expected_source_text_fingerprint": second["source_text_fingerprint"],
            "selection_revision": 0,
        }
    )
    http = install_clone(monkeypatch, tmp_path)
    http.hook = lambda: setattr(
        http, "output", b"bad" if http.posts[-1][1]["data"][0] == "第二句。" else wav_bytes(0.6)
    )
    queued_response = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert queued_response.status_code == 202, queued_response.text
    queued = queued_response.json()
    drain(c)
    assert len(http.posts) == 2 and history(synthesis_project)["selection_revision"] == 1, c.get(
        path(synthesis_project) + "/synthesis/" + queued["id"]
    ).json()
    details = c.get(path(synthesis_project) + "/synthesis/" + queued["id"]).json()
    page = c.get(
        path(synthesis_project) + "/synthesis/" + queued["id"], params={"limit": 1, "offset": 1}
    ).json()
    assert len(page["lines"]) == 1 and page["total"] == 2
    failed = next(x for x in details["lines"] if x["segment_id"] == second["id"])
    assert failed["status"] == "failed"
    http.hook = None
    http.output = wav_bytes(0.6)
    assert c.post(f"/api/runs/{failed['run_id']}/retry", headers=h, json={}).status_code == 200
    drain(c)
    assert len(http.posts) == 2
    assert history(synthesis_project)["selection_revision"] == 1
    assert (
        c.get(path(synthesis_project) + f"/segments/{second['id']}/audio-history").json()[
            "selection_revision"
        ]
        == 1
    )


def test_actual_handle_returned_after_lease_expiry_is_fenced_and_saved(
    synthesis_project, monkeypatch, tmp_path
):
    from datetime import timedelta

    from videotranslate.models.core import utcnow

    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    request = queue(synthesis_project)
    run_id = request["lines"][0]["run_id"]

    def expire():
        with c.app.state.session_factory.begin() as db:
            db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)

    http.hook = expire
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory() as db:
        assert db.get(StageRun, run_id).remote_id == "actual-event-1"
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        assert op.remote_id == "actual-event-1" and op.phase == "accepted"
    http.hook = None
    assert Worker(c.app.state.settings).run_once()
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 1


def test_late_handle_cannot_overwrite_explicitly_acknowledged_replacement_generation(
    synthesis_project,
):
    from datetime import timedelta

    from videotranslate.execution.context import RunContext
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import claim_run
    from videotranslate.models.core import utcnow

    c, h, *_ = synthesis_project
    request = queue(synthesis_project)
    run_id = request["lines"][0]["run_id"]
    with c.app.state.session_factory.begin() as db:
        run = claim_run(db, "old-owner")
    context = RunContext(
        c.app.state.session_factory,
        c.app.state.storage,
        c.app.state.settings,
        run_id,
        run.lease_token,
    )
    operations = Operations(context)
    operation = operations.prepare(provider="omnivoice", model="OmniVoice")
    binding = operations.begin()
    with c.app.state.session_factory.begin() as db:
        db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    Worker(c.app.state.settings).run_once()
    result = c.post(
        f"/api/runs/{run_id}/retry", headers=h, json={"acknowledge_uncertain_submission": True}
    )
    assert result.status_code == 200, result.text
    operations.accept("late-real-event", binding=binding)
    with c.app.state.session_factory() as db:
        current = db.get(StageRun, run_id)
        assert current.remote_id is None and current.remote_state == "not_submitted"
        assert db.get(PrivateOperation, operation.id).phase == "accepted"
        assert db.get(PrivateOperation, operation.id).remote_id == "late-real-event"


def test_source_wording_edit_is_permission_guard_and_same_target_reuses_natural(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, p, s, line, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    latest = []

    def edit_source():
        response = c.patch(
            f"/api/projects/{p['id']}/segments/{line['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {"revision": 1, "text": "Corrected English source"},
        )
        assert response.status_code == 200
        latest.append(response.json())

    http.hook = edit_source
    queue(synthesis_project)
    drain(c)
    assert history(synthesis_project)["selected_output_id"] is None
    timeline = c.get(
        f"/api/projects/{p['id']}/timeline", params={"target_language": "zh-Hant"}
    ).json()["segments"][0]
    proof = latest[0]["source_text_fingerprint"]
    response = c.patch(
        path(synthesis_project) + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": timeline["translation"]["revision"],
            "expected_source_text_fingerprint": proof,
            "text": "這是目標文字。",
            "approved": True,
        },
    )
    assert response.status_code == 200
    request = body(synthesis_project)
    request["segments"][0].update(
        translation_revision=response.json()["revision"], expected_source_text_fingerprint=proof
    )
    http.hook = None
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )
    drain(c)
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 1


@pytest.mark.parametrize("field", ["reference_version_id", "translation_revision_id"])
def test_cache_rejects_inconsistent_immutable_lineage(
    synthesis_project, monkeypatch, tmp_path, field
):
    from dubbing_helpers import guard

    from videotranslate.models.synthesis import SynthesisLine

    c, h, p, s, line, _, ref = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queued = queue(synthesis_project)
    drain(c)
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    if field == "reference_version_id":
        new = c.post(
            f"/api/projects/{p['id']}/references/{ref['reference_id']}/versions",
            headers=h,
            json={"parent_version_id": ref["id"], "text": ref["text"], "language": ref["language"]},
        ).json()
        value = new["id"]
    else:
        translated = c.patch(
            path(synthesis_project) + f"/segments/{line['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 1,
                "expected_source_text_fingerprint": line["source_text_fingerprint"],
                "text": "這是目標文字。",
                "approved": True,
                "locked": True,
            },
        ).json()
        request["segments"][0]["translation_revision"] = translated["revision"]
        with c.app.state.session_factory() as db:
            from videotranslate.models.dubbing import TranslationState

            value = db.scalar(select(TranslationState)).current_revision_id
    with c.app.state.session_factory.begin() as db:
        setattr(db.get(SynthesisLine, queued["lines"][0]["id"]), field, value)
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )
    drain(c)
    assert len(http.posts) == 2


def test_dormant_track_control_edit_does_not_block_explicit_line_override(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, _, s, line, *_ = synthesis_project
    controls = guard(s, line["transcript_revision"]) | {"revision": 0, "controls": {"sp": 1.1}}
    assert (
        c.put(
            path(synthesis_project) + f"/segments/{line['id']}/voice-settings",
            headers=h,
            json=controls,
        ).status_code
        == 200
    )
    http = install_clone(monkeypatch, tmp_path)

    def edit_defaults():
        response = c.put(
            path(synthesis_project) + "/voice-settings",
            headers=h,
            json=guard(s, line["transcript_revision"]) | {"revision": 0, "controls": {"ns": 48}},
        )
        assert response.status_code == 200

    http.hook = edit_defaults
    queue(synthesis_project)
    drain(c)
    assert len(http.posts) == 1 and http.posts[0][1]["data"][8] == 1.1
    assert history(synthesis_project)["selection_revision"] == 1

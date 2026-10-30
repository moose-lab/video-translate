"""Actual CPU preparation and recording HF HTTP; no external inference."""

# ruff: noqa: F811
import base64
import io
import json
import wave

import pytest
from dubbing_helpers import guard
from test_synthesis_domain import path, synthesis_project  # noqa: F401
from test_synthesis_operations import history, install_clone, queue
from test_translation_operations import drain


class RecordingASR:
    allowed_hosts = set()

    def __init__(self):
        self.posts = []
        self.hook = None
        self.language = None
        self.text = "這是目標文字。"
        self.fail = False

    def close(self):
        pass

    def post_json(self, url, body, **kwargs):
        self.posts.append((url, body, kwargs))
        if self.hook:
            self.hook()
        if self.fail:
            raise TimeoutError()
        value = {"chunks": [{"text": self.text, "timestamp": [0, 0.6]}]}
        if self.language is not None:
            value["language"] = self.language
        return json.dumps(value).encode()


def prepared(fixture, monkeypatch, tmp_path):
    c, h, *_ = fixture
    install_clone(monkeypatch, tmp_path)
    queue(fixture)
    drain(c)
    assert (
        c.put(
            "/api/credentials/huggingface", headers=h, json={"revision": 0, "token": "hf_test_qc"}
        ).status_code
        == 200
    )
    configured = c.put(
        "/api/providers/verification",
        headers=h,
        json={
            "revision": 0,
            "adapter": "hf_router",
            "model": "openai/whisper-large-v3",
            "credential_ref": "huggingface",
        },
    )
    assert configured.status_code == 200, configured.text
    http = RecordingASR()
    monkeypatch.setattr("videotranslate.dubbing.remote_voice_qc.make_http", lambda _: http)
    return http


def qc_body(fixture, target_revision=1):
    output = history(fixture)
    return guard(fixture[3], fixture[4]["transcript_revision"]) | {
        "segments": [
            {
                "id": fixture[4]["id"],
                "translation_revision": target_revision,
                "expected_source_text_fingerprint": fixture[4]["source_text_fingerprint"],
                "selection_revision": output["selection_revision"],
                "output_id": output["selected_output_id"],
            }
        ]
    }


def enqueue(fixture, **kwargs):
    c, h, *_ = fixture
    response = c.post(path(fixture) + "/voice-qc", headers=h, json=qc_body(fixture, **kwargs))
    assert response.status_code == 202, response.text
    return response.json()


def detail(fixture, request):
    return fixture[0].get(path(fixture) + "/voice-qc/" + request["id"]).json()


def test_selected_audio_independent_recognition_and_listening_are_separate(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    request = enqueue(synthesis_project)
    drain(synthesis_project[0])
    result = detail(synthesis_project, request)
    assert result["lines"][0]["status"] == "succeeded", result
    assert len(http.posts) == 1
    url, body, options = http.posts[0]
    assert "whisper-large-v3" in url and set(body) == {"inputs", "parameters"}
    assert body["parameters"] == {"return_timestamps": True}
    assert "_timeout_profile" not in options
    with wave.open(io.BytesIO(base64.b64decode(body["inputs"]))) as wav:
        assert wav.getframerate() == 16000 and wav.getnchannels() == 1
    line = result["lines"][0]
    assert line["recognition"]["detected_language"] is None
    assert line["comparison"]["text_match"] is True
    output = history(synthesis_project)["outputs"][0]
    assert output["acceptance"] == "not_assessed" and not output["ready"]
    assert output["qc"]["comparison"]["text_match"] is True
    public = str(
        synthesis_project[0].get(f"/api/projects/{synthesis_project[2]['id']}/events").json()
    )
    assert "這是目標文字" not in public and "hf_test_qc" not in public


def test_review_requires_exact_audio_and_target_and_retains_versions(
    synthesis_project, monkeypatch, tmp_path
):
    from sqlalchemy import select

    from videotranslate.models.voice_qc import AudioReview

    prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, *_ = synthesis_project
    payload = qc_body(synthesis_project)
    row = payload.pop("segments")[0]
    payload |= {k: v for k, v in row.items() if k not in {"id", "selection_revision"}}
    payload["audio_selection_revision"] = row["selection_revision"]
    payload |= {
        "revision": 0,
        "decision": "accepted",
        "note": "Listened to exact audio",
        "qc_evidence_fingerprint": history(synthesis_project)["outputs"][0][
            "qc_evidence_fingerprint"
        ],
    }
    url = path(synthesis_project) + f"/segments/{row['id']}/audio-review"
    response = c.put(url, headers=h, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["acceptance"] == "accepted"
    assert c.put(url, headers=h, json=payload).status_code == 409
    payload.update(revision=1, decision="rejected")
    assert c.put(url, headers=h, json=payload).json()["acceptance"] == "rejected"
    with c.app.state.session_factory() as db:
        assert len(db.scalars(select(AudioReview)).all()) == 2


def edit_target(fixture, text, revision=1, approved=True):
    c, h, _, s, line, *_ = fixture
    response = c.patch(
        path(fixture) + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": revision,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "text": text,
            "approved": approved,
        },
    )
    assert response.status_code == 200, response.text


def test_slow_recognition_keeps_success_but_new_wording_reuses_without_paid_post(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    http.hook = lambda: edit_target(synthesis_project, "改正後的目標。")
    first = enqueue(synthesis_project)
    drain(synthesis_project[0])
    old = detail(synthesis_project, first)["lines"][0]
    assert old["status"] == "succeeded" and not old["current"]
    assert old["recognition"]["segments"][0]["text"] == http.text
    assert old["publication"]["issue"] == "EDITOR_CHANGED"
    http.hook = None
    second = enqueue(synthesis_project, target_revision=2)
    drain(synthesis_project[0])
    current = detail(synthesis_project, second)["lines"][0]
    assert current["status"] == "succeeded" and current["current"], current
    assert not current["comparison"]["text_match"]
    assert len(http.posts) == 1
    selected = history(synthesis_project)["outputs"][0]
    assert selected["stale"] and not selected["ready"]
    assert "NATURAL_AUDIO_STALE" in selected["issues"]


def test_recognition_timeout_requires_explicit_ack_and_preserves_natural_audio(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.execution.worker import Worker
    from videotranslate.models.execution import StageRun

    http = prepared(synthesis_project, monkeypatch, tmp_path)
    original = history(synthesis_project)["selected_output_id"]
    http.fail = True
    request = enqueue(synthesis_project)
    c, h, p, *_ = synthesis_project
    assert Worker(c.app.state.settings).run_once()
    line = detail(synthesis_project, request)["lines"][0]
    run_id = line["run_id"]
    assert line["next_action"] == "acknowledge_uncertain_submission"
    with c.app.state.session_factory() as db:
        run = db.get(StageRun, run_id)
        assert run.remote_state == "submitting" and run.remote_id is None
    assert history(synthesis_project)["selected_output_id"] == original
    assert len(http.posts) == 1
    endpoint = f"/api/runs/{run_id}/retry"
    assert c.post(endpoint, headers=h, json={}).status_code == 409
    http.fail = False
    assert (
        c.post(endpoint, headers=h, json={"acknowledge_uncertain_submission": True}).status_code
        == 200
    )
    drain(c)
    assert detail(synthesis_project, request)["lines"][0]["status"] == "succeeded"
    assert len(http.posts) == 2


def test_invalid_measured_natural_provenance_denies_qc_before_asr(
    synthesis_project, monkeypatch, tmp_path
):
    from sqlalchemy import select

    from videotranslate.models.analysis import PreparedObject

    http = prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, *_ = synthesis_project
    payload = qc_body(synthesis_project)
    with c.app.state.session_factory.begin() as db:
        record = next(
            r
            for r in db.scalars(select(PreparedObject))
            if r.metadata_json.get("kind") == "natural_audio"
        )
        record.metadata_json = record.metadata_json | {"provenance": {"full_decode": True}}
    response = c.post(path(synthesis_project) + "/voice-qc", headers=h, json=payload)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "AUDIO_EVIDENCE_INVALID"
    )
    assert not http.posts


def test_qc_command_proofs_csrf_duplicate_and_generic_run_bypass(
    synthesis_project, monkeypatch, tmp_path
):
    prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, p, *_ = synthesis_project
    endpoint = path(synthesis_project) + "/voice-qc"
    payload = qc_body(synthesis_project)
    assert c.post(endpoint, json=payload).status_code == 403
    for field, value in (
        ("output_id", "foreign"),
        ("selection_revision", 0),
        ("translation_revision", 0),
        ("expected_source_text_fingerprint", "a" * 64),
    ):
        bad = qc_body(synthesis_project)
        bad["segments"][0][field] = value
        assert c.post(endpoint, headers=h, json=bad).status_code in {404, 409}
    bad = qc_body(synthesis_project)
    bad["segments"] *= 2
    assert c.post(endpoint, headers=h, json=bad).status_code == 422
    first = enqueue(synthesis_project)
    assert enqueue(synthesis_project)["id"] == first["id"]
    assert (
        c.post(
            f"/api/projects/{p['id']}/runs",
            headers=h,
            json={
                "stage": "voice_qc",
                "target_language": "zh-Hant",
                "segment_id": synthesis_project[4]["id"],
                "options": {"line_id": first["lines"][0]["id"]},
            },
        ).status_code
        == 422
    )
    assert (
        c.get(path(synthesis_project) + "/voice-qc/" + first["id"] + "?limit=101").status_code
        == 422
    )


def test_review_must_acknowledge_current_qc_evidence(synthesis_project, monkeypatch, tmp_path):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    before = history(synthesis_project)["outputs"][0]
    assert before["qc_evidence_fingerprint"]
    payload = qc_body(synthesis_project)
    row = payload.pop("segments")[0]
    payload |= {k: v for k, v in row.items() if k not in {"id", "selection_revision"}}
    payload |= {
        "audio_selection_revision": row["selection_revision"],
        "revision": 0,
        "decision": "accepted",
        "qc_evidence_fingerprint": before["qc_evidence_fingerprint"],
    }
    request = enqueue(synthesis_project)
    drain(synthesis_project[0])
    c, h, *_ = synthesis_project
    url = path(synthesis_project) + f"/segments/{row['id']}/audio-review"
    assert c.put(url, headers=h, json=payload).status_code == 409
    after = history(synthesis_project)["outputs"][0]
    payload["qc_evidence_fingerprint"] = after["qc_evidence_fingerprint"]
    accepted = c.put(url, headers=h, json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ready"] and accepted.json()["readiness_basis"] == "manual_review"
    assert len(http.posts) == 1
    assert detail(synthesis_project, request)["lines"][0]["comparison"]["text_match"]


def accept_current(fixture, revision=0, target_revision=1):
    c, h, *_ = fixture
    payload = qc_body(fixture, target_revision)
    row = payload.pop("segments")[0]
    payload |= {k: v for k, v in row.items() if k not in {"id", "selection_revision"}}
    payload |= {
        "audio_selection_revision": row["selection_revision"],
        "revision": revision,
        "decision": "accepted",
        "qc_evidence_fingerprint": history(fixture)["outputs"][0]["qc_evidence_fingerprint"],
    }
    response = c.put(path(fixture) + f"/segments/{row['id']}/audio-review", headers=h, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_listening_stays_current_after_benign_qc_but_new_adverse_evidence_needs_ack(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    accepted = accept_current(synthesis_project)
    assert accepted["acceptance"] == "accepted" and accepted["ready"]
    first = enqueue(synthesis_project)
    drain(synthesis_project[0])
    heard = history(synthesis_project)["outputs"][0]
    assert heard["acceptance"] == "accepted" and heard["ready"], heard
    assert heard["qc"]["status"] == "succeeded"
    assert detail(synthesis_project, first)["lines"][0]["current"]
    # A new immutable verification config is a distinct paid identity.
    c, h, *_ = synthesis_project
    configured = c.put(
        "/api/providers/verification",
        headers=h,
        json={
            "revision": 1,
            "adapter": "hf_router",
            "model": "openai/whisper-large-v3",
            "credential_ref": "huggingface",
        },
    )
    assert configured.status_code == 200
    http.text = "Unexpected wrong sentence"
    second = enqueue(synthesis_project)
    drain(c)
    adverse = history(synthesis_project)["outputs"][0]
    assert adverse["acceptance"] == "accepted" and not adverse["ready"]
    assert "QC_ACKNOWLEDGEMENT_REQUIRED" in adverse["issues"]
    assert not detail(synthesis_project, second)["lines"][0]["comparison"]["text_match"]
    override = accept_current(synthesis_project, revision=1)
    assert override["ready"] and override["qc_override"]
    assert override["qc"]["comparison"]["text_match"] is False
    assert len(http.posts) == 2


def test_manual_acceptance_of_stale_selected_bytes_does_not_unblock_natural_readiness(
    synthesis_project, monkeypatch, tmp_path
):
    prepared(synthesis_project, monkeypatch, tmp_path)
    edit_target(synthesis_project, "Updated meaningful words")
    reviewed = accept_current(synthesis_project, target_revision=2)
    assert reviewed["acceptance"] == "accepted" and not reviewed["ready"]
    assert "NATURAL_AUDIO_STALE" in reviewed["issues"]


def test_target_readiness_is_not_inferred_from_one_accepted_page(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import create_line

    prepared(synthesis_project, monkeypatch, tmp_path)
    accept_current(synthesis_project)
    c, h, p, s, *_ = synthesis_project
    created = create_line(
        (c, h, p),
        s,
        "Another source line",
        transcript=synthesis_project[4]["transcript_revision"],
        start_ms=900,
        end_ms=1600,
    )
    assert created["segment"]["id"]
    result = c.get(path(synthesis_project) + "/synthesis?limit=1").json()
    assert result["total"] == 2
    assert not result["ready"] and result["readiness"]["assessed_rows"] == 2
    assert result["readiness"]["ready_rows"] == 1
    assert result["readiness"]["issues"]["AUDIO_MISSING"] == 1


def test_chunk_boundaries_do_not_invent_cjk_spaces_and_retain_raw_quantized_tail(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)

    def chunks(url, body, **kwargs):
        http.posts.append((url, body, kwargs))
        return json.dumps(
            {
                "chunks": [
                    {"text": "這是", "timestamp": [0, 0.2]},
                    {"text": "目標文字。", "timestamp": [0.2, 0.61]},
                ]
            }
        ).encode()

    http.post_json = chunks
    request = enqueue(synthesis_project)
    drain(synthesis_project[0])
    line = detail(synthesis_project, request)["lines"][0]
    assert line["status"] == "succeeded", line
    assert line["comparison"]["text_match"]
    assert line["recognition"]["segments"][-1]["end"] == 0.61
    assert line["recognition"]["working_timings"][-1] == {
        "start_ms": 200,
        "end_ms": 600,
        "flags": ["provider_end_clipped"],
    }


def test_publication_failure_retry_uses_retained_private_recognition(
    synthesis_project, monkeypatch, tmp_path
):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES
    from videotranslate.execution.worker import Worker

    http = prepared(synthesis_project, monkeypatch, tmp_path)
    request = enqueue(synthesis_project)
    c, h, *_ = synthesis_project

    def fail(*args):
        raise RuntimeError("simulated publisher conflict")

    registry = STAGES | {"voice_qc": replace(STAGES["voice_qc"], publish=fail)}
    assert Worker(c.app.state.settings, registry=registry).run_once()
    line = detail(synthesis_project, request)["lines"][0]
    assert line["status"] == "failed"
    assert line["recognition"]["segments"][0]["text"] == http.text
    assert c.post(f"/api/runs/{line['run_id']}/retry", headers=h, json={}).status_code == 200
    drain(c)
    assert detail(synthesis_project, request)["lines"][0]["status"] == "succeeded"
    assert len(http.posts) == 1


def test_same_selected_bytes_new_selection_counter_reuses_asr_and_invalidates_listening(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    first = enqueue(synthesis_project)
    drain(synthesis_project[0])
    accept_current(synthesis_project)
    c, h, _, s, line, *_ = synthesis_project
    output = history(synthesis_project)
    response = c.put(
        path(synthesis_project) + f"/segments/{line['id']}/audio-selection",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": 1,
            "output_id": output["selected_output_id"],
            "translation_revision": 1,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
        },
    )
    assert response.status_code == 200
    assert response.json()["outputs"][0]["acceptance"] == "stale"
    second = enqueue(synthesis_project)
    drain(c)
    assert detail(synthesis_project, first)["lines"][0]["current"] is False
    assert detail(synthesis_project, second)["lines"][0]["current"]
    assert len(http.posts) == 1


def test_local_alias_interruption_resumes_pinned_success_without_asr(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.worker import Worker

    http = prepared(synthesis_project, monkeypatch, tmp_path)
    enqueue(synthesis_project)
    drain(synthesis_project[0])
    edit_target(synthesis_project, "New expected words")
    request = enqueue(synthesis_project, target_revision=2)
    original_cache = Operations.cache

    def interrupt(self, payload, facts):
        if facts.get("reused"):
            raise RuntimeError("interrupt between alias ready and cache")
        return original_cache(self, payload, facts)

    monkeypatch.setattr(Operations, "cache", interrupt)
    c, h, *_ = synthesis_project
    assert Worker(c.app.state.settings).run_once()
    line = detail(synthesis_project, request)["lines"][0]
    assert line["status"] == "failed"
    monkeypatch.setattr(Operations, "cache", original_cache)
    assert c.post(f"/api/runs/{line['run_id']}/retry", headers=h, json={}).status_code == 200
    drain(c)
    result = detail(synthesis_project, request)["lines"][0]
    assert result["status"] == "succeeded", result
    assert len(http.posts) == 1


def test_same_paid_identity_uncertainty_cannot_be_bypassed_by_another_target(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import make_track
    from test_synthesis_domain import body

    from videotranslate.execution.worker import Worker

    http = prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, p, s, line, *_ = synthesis_project
    base = f"/api/projects/{p['id']}"
    make_track(c, h, base, "ja")
    patched = c.patch(
        path(synthesis_project).replace("zh-Hant", "ja") + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": 0,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "text": "別のターゲット",
            "approved": True,
        },
    )
    assert patched.status_code == 200
    assert (
        c.post(
            path(synthesis_project).replace("zh-Hant", "ja") + "/synthesize",
            headers=h,
            json=body(synthesis_project),
        ).status_code
        == 202
    )
    drain(c)
    http.fail = True
    enqueue(synthesis_project)
    assert Worker(c.app.state.settings).run_once()
    payload = qc_body(synthesis_project)
    payload["segments"][0]["output_id"] = c.get(
        path(synthesis_project).replace("zh-Hant", "ja") + f"/segments/{line['id']}/audio-history"
    ).json()["selected_output_id"]
    result = c.post(
        path(synthesis_project).replace("zh-Hant", "ja") + "/voice-qc", headers=h, json=payload
    )
    assert result.status_code == 409 and result.json()["error"]["code"] == "SUBMISSION_UNCERTAIN", (
        result.text
    )
    assert len(http.posts) == 1


def test_unknown_recognition_model_allows_explicit_manual_review(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, *_ = synthesis_project
    response = c.put(
        "/api/providers/verification",
        headers=h,
        json={
            "revision": 1,
            "adapter": "hf_router",
            "model": "organization/unknown-asr",
            "credential_ref": "huggingface",
        },
    )
    assert response.status_code == 200
    queued = c.post(
        path(synthesis_project) + "/voice-qc", headers=h, json=qc_body(synthesis_project)
    )
    assert queued.status_code == 409 and queued.json()["error"]["code"] == "QC_LANGUAGE_UNKNOWN"
    result = accept_current(synthesis_project)
    assert result["ready"] and result["qc_override"]
    assert result["qc"]["status"] == "unknown" and "QC_UNKNOWN" in result["issues"]
    assert not http.posts


def test_raw_recognition_over_comparison_budget_is_visible_and_manual_only(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    http.text = "x" * 5000
    request = enqueue(synthesis_project)
    drain(synthesis_project[0])
    line = detail(synthesis_project, request)["lines"][0]
    assert line["status"] == "succeeded" and len(line["recognition"]["segments"][0]["text"]) == 5000
    assert line["comparison"]["status"] == "unavailable"
    assert line["comparison"]["reason"] == "comparison_length_limit"
    assert not history(synthesis_project)["outputs"][0]["ready"]
    assert accept_current(synthesis_project)["ready"]


def test_private_qc_and_review_details_are_owned_and_bounded(
    synthesis_project, monkeypatch, tmp_path, client_factory, register
):
    prepared(synthesis_project, monkeypatch, tmp_path)
    request = enqueue(synthesis_project)
    drain(synthesis_project[0])
    accept_current(synthesis_project)
    c = synthesis_project[0]
    other = client_factory(database_url=c.app.state.settings.database_url.get_secret_value())
    auth = register(other, "other-qc@example.com")
    h = {"X-CSRF-Token": auth["csrf_token"]}
    urls = [
        path(synthesis_project) + "/voice-qc/" + request["id"],
        path(synthesis_project) + f"/segments/{synthesis_project[4]['id']}/audio-reviews",
    ]
    for url in urls:
        assert other.get(url).status_code == 404
        assert c.get(url + "?limit=101").status_code == 422
    assert (
        other.post(
            path(synthesis_project) + "/voice-qc", headers=h, json=qc_body(synthesis_project)
        ).status_code
        == 404
    )
    history_response = c.get(urls[1]).json()
    assert history_response["total"] == 1 and history_response["items"][0]["current"]
    assert "qc_acknowledgement" in history_response["items"][0]


def test_failed_publication_keeps_prepared_input_in_existing_gc_manifest(
    synthesis_project, monkeypatch, tmp_path
):
    from dataclasses import replace
    from datetime import timedelta

    from videotranslate.execution.prepared import cleanup_orphans
    from videotranslate.execution.registry import STAGES
    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import utcnow

    prepared(synthesis_project, monkeypatch, tmp_path)
    enqueue(synthesis_project)
    c = synthesis_project[0]

    def fail(*args):
        raise RuntimeError("publication interruption")

    registry = STAGES | {"voice_qc": replace(STAGES["voice_qc"], publish=fail)}
    assert Worker(c.app.state.settings, registry=registry).run_once()
    with c.app.state.session_factory() as db:
        from videotranslate.models.core import Project

        project = db.get(Project, synthesis_project[2]["id"])
        workspace_id = project.workspace_id
    count = cleanup_orphans(
        c.app.state.session_factory,
        c.app.state.storage,
        workspace_id=workspace_id,
        before=utcnow() + timedelta(seconds=1),
    )
    assert count == 0


@pytest.mark.parametrize("skewed_clock", [False, True])
def test_same_identity_is_serialized_before_preprocessing_and_reuses_completed_peer(
    synthesis_project, monkeypatch, tmp_path, skewed_clock
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from dubbing_helpers import make_track
    from test_synthesis_domain import body

    from videotranslate.dubbing.analysis import materialize
    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import utcnow
    from videotranslate.models.execution import StageRun

    http = prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, p, s, line, *_ = synthesis_project
    make_track(c, h, f"/api/projects/{p['id']}", "ja")
    ja = path(synthesis_project).replace("zh-Hant", "ja")
    assert (
        c.patch(
            ja + f"/segments/{line['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 0,
                "expected_source_text_fingerprint": line["source_text_fingerprint"],
                "text": "別のターゲット",
                "approved": True,
            },
        ).status_code
        == 200
    )
    assert c.post(ja + "/synthesize", headers=h, json=body(synthesis_project)).status_code == 202
    drain(c)
    first_request = enqueue(synthesis_project)
    if skewed_clock:
        from datetime import timedelta

        from videotranslate.models.voice_qc import VoiceQCLine

        with c.app.state.session_factory.begin() as db:
            db.get(VoiceQCLine, first_request["lines"][0]["id"]).created_at += timedelta(hours=1)
    payload = qc_body(synthesis_project)
    payload["segments"][0]["output_id"] = c.get(
        ja + f"/segments/{line['id']}/audio-history"
    ).json()["selected_output_id"]
    second = c.post(ja + "/voice-qc", headers=h, json=payload).json()
    entered, release = Event(), Event()
    calls = []

    def paused(context, asset, destination, **kwargs):
        calls.append(asset.id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return materialize(context, asset, destination, **kwargs)

    monkeypatch.setattr("videotranslate.dubbing.analysis.materialize", paused)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(Worker(c.app.state.settings).run_once)
            assert entered.wait(5)
            assert Worker(c.app.state.settings).run_once()
            second_line = c.get(ja + "/voice-qc/" + second["id"]).json()["lines"][0]
            assert second_line["status"] == "retry_wait"
            assert len(calls) == 1 and not http.posts
            release.set()
            assert first.result(timeout=5)
    finally:
        release.set()
    with c.app.state.session_factory.begin() as db:
        db.get(StageRun, second_line["run_id"]).due_at = utcnow()
    drain(c)
    assert c.get(ja + "/voice-qc/" + second["id"]).json()["lines"][0]["status"] == "succeeded"
    assert len(http.posts) == 1 and len(calls) == 1


def test_approval_only_revision_preserves_meaning_evidence_and_listening(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    request = enqueue(synthesis_project)
    drain(synthesis_project[0])
    accept_current(synthesis_project)
    edit_target(synthesis_project, "這是目標文字。", approved=False)
    result = history(synthesis_project)["outputs"][0]
    assert result["acceptance"] == "accepted" and result["ready"]
    assert result["qc"]["status"] == "succeeded"
    assert detail(synthesis_project, request)["lines"][0]["current"]
    enqueue(synthesis_project, target_revision=2)
    drain(synthesis_project[0])
    assert len(http.posts) == 1


def test_new_wrong_words_with_equal_error_rate_need_new_acknowledgement(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    http.text = "a" * 12
    enqueue(synthesis_project)
    drain(synthesis_project[0])
    assert accept_current(synthesis_project)["ready"]
    first = history(synthesis_project)["outputs"][0]["qc"]["comparison"]
    c, h, *_ = synthesis_project
    assert (
        c.put(
            "/api/providers/verification",
            headers=h,
            json={
                "revision": 1,
                "adapter": "hf_router",
                "model": "openai/whisper-large-v3",
                "credential_ref": "huggingface",
            },
        ).status_code
        == 200
    )
    http.text = "b" * 12
    enqueue(synthesis_project)
    drain(c)
    result = history(synthesis_project)["outputs"][0]
    assert result["qc"]["comparison"]["character_error_rate"] == first["character_error_rate"]
    assert result["acceptance"] == "accepted" and not result["ready"]
    assert "QC_ACKNOWLEDGEMENT_REQUIRED" in result["issues"]


def test_qc_uses_canonical_owned_track_for_an_accepted_tag_alias(
    synthesis_project, monkeypatch, tmp_path
):
    http = prepared(synthesis_project, monkeypatch, tmp_path)
    c, h, *_ = synthesis_project
    alias = path(synthesis_project).replace("zh-Hant", "zh-hant")
    assert c.get(alias + "/synthesis").status_code == 200
    request = c.post(alias + "/voice-qc", headers=h, json=qc_body(synthesis_project))
    assert request.status_code == 202, request.text
    drain(c)
    assert (
        c.get(alias + "/voice-qc/" + request.json()["id"]).json()["lines"][0]["status"]
        == "succeeded"
    )
    assert len(http.posts) == 1

"""Actual CPU preparation and recording HF HTTP; no external inference."""

# ruff: noqa: F811
import base64
import io
import json
import wave

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


def edit_target(fixture, text, revision=1):
    c, h, _, s, line, *_ = fixture
    response = c.patch(
        path(fixture) + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": revision,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "text": text,
            "approved": True,
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

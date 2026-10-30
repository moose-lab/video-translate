"""Regression evidence for SPEC S1/S2/S3; recording inference only."""

# ruff: noqa: F811
import pytest
from test_synthesis_domain import path, synthesis_project  # noqa: F401
from test_synthesis_operations import history
from test_translation_operations import drain
from test_voice_qc_operations import accept_current, detail, enqueue, prepared


def configure(fixture, revision):
    c, h, *_ = fixture
    response = c.put(
        "/api/providers/verification",
        headers=h,
        json={
            "revision": revision,
            "adapter": "hf_router",
            "model": "openai/whisper-large-v3",
            "credential_ref": "huggingface",
        },
    )
    assert response.status_code == 200, response.text


def force_due(client, run_id):
    from videotranslate.models.core import utcnow
    from videotranslate.models.execution import StageRun

    with client.app.state.session_factory.begin() as db:
        db.get(StageRun, run_id).due_at = utcnow()


@pytest.mark.parametrize(
    "state", ["queued", "running", "retry_wait", "failed", "needs_review", "cancelled", "stale"]
)
def test_inconclusive_work_retains_adverse_evidence(
    synthesis_project, monkeypatch, tmp_path, state
):
    from videotranslate.models.execution import StageRun

    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    assert accept_current(f)["ready"]
    http.text = "unexpected incorrect words"
    first = enqueue(f)
    drain(f[0])
    configure(f, 1)
    second = enqueue(f)
    with f[0].app.state.session_factory.begin() as db:
        db.get(StageRun, second["lines"][0]["run_id"]).status = state
    current = history(f)["outputs"][0]
    assert current["acceptance"] == "accepted" and not current["ready"]
    assert current["qc"]["status"] == state
    assert current["qc"]["evidence"]["request_id"] == first["id"]
    assert current["qc"]["comparison"]["text_match"] is False
    assert "QC_ACKNOWLEDGEMENT_REQUIRED" in current["issues"]


def test_acknowledged_adverse_can_wait_and_new_completed_benign_supersedes(
    synthesis_project, monkeypatch, tmp_path
):
    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    accept_current(f)
    http.text = "wrong words"
    enqueue(f)
    drain(f[0])
    assert accept_current(f, revision=1)["ready"]
    configure(f, 1)
    enqueue(f)
    assert history(f)["outputs"][0]["ready"]
    http.text = "這是目標文字。"
    drain(f[0])
    current = history(f)["outputs"][0]
    assert current["ready"] and current["acceptance"] == "accepted"
    assert current["qc"]["comparison"]["text_match"]
    assert current["qc_risks"] == {}


def test_late_old_completion_cannot_replace_newer_adverse_evidence(
    synthesis_project, monkeypatch, tmp_path
):
    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    accept_current(f)
    older = enqueue(f)
    run = older["lines"][0]["run_id"]
    c, h, *_ = f
    assert c.post(f"/api/runs/{run}/cancel", headers=h, json={}).status_code == 200
    configure(f, 1)
    newer = enqueue(f)
    http.text = "newer incorrect words"
    drain(c)
    http.text = "這是目標文字。"
    assert c.post(f"/api/runs/{run}/retry", headers=h, json={}).status_code == 200
    drain(c)
    assert detail(f, older)["lines"][0]["comparison"]["text_match"]
    assert not detail(f, newer)["lines"][0]["comparison"]["text_match"]
    current = history(f)["outputs"][0]
    assert not current["ready"] and current["acceptance"] == "accepted"
    assert current["qc"]["evidence"]["request_id"] == newer["id"]

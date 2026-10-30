"""Durable local cache aliases never become remote inference after interruption."""
# ruff: noqa: F811

import copy
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from test_synthesis_domain import body, path, synthesis_project  # noqa: F401
from test_synthesis_operations import history, install_clone, queue
from test_translation_operations import drain

from videotranslate.execution.contracts import FailureCode, LeaseLost, StageFailure
from videotranslate.execution.prepared import Operations
from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.core import utcnow
from videotranslate.models.execution import StageRun


def interrupted_alias(fixture, monkeypatch, *, lose_lease=False):
    c, h, *_ = fixture
    request = body(fixture, replace_selected=True)
    request["segments"][0]["selection_revision"] = history(fixture)["selection_revision"]
    queued = c.post(path(fixture) + "/synthesize", headers=h, json=request)
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["lines"][0]["run_id"]
    original = Operations.cache

    def interrupt(self, payload, facts):
        assert facts["reused"] is True
        if lose_lease:
            with c.app.state.session_factory.begin() as db:
                db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
            raise LeaseLost()
        raise StageFailure(FailureCode.TRANSIENT, retryable=True)

    monkeypatch.setattr(Operations, "cache", interrupt)
    assert Worker(c.app.state.settings).run_once()
    monkeypatch.setattr(Operations, "cache", original)
    with c.app.state.session_factory.begin() as db:
        db.get(StageRun, run_id).due_at = utcnow()
        operation = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        assert operation.phase == "ready"
    return queued.json(), run_id, operation.id


def forbid_remote(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError(
            "Local alias recovery must not construct provider transport or credentials"
        )

    monkeypatch.setattr("videotranslate.dubbing.remote_synthesis.make_http", fail)
    monkeypatch.setattr("videotranslate.dubbing.remote_synthesis.credential_token", fail)
    monkeypatch.setattr(Operations, "begin", fail)


@pytest.mark.parametrize("lose_lease", [False, True])
def test_ready_alias_restarts_locally_with_same_generation(
    synthesis_project, monkeypatch, tmp_path, lose_lease
):
    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    first = queue(synthesis_project)
    drain(c)
    _, run_id, operation_id = interrupted_alias(
        synthesis_project, monkeypatch, lose_lease=lose_lease
    )
    with c.app.state.session_factory() as db:
        operation = db.get(PrivateOperation, operation_id)
        generation = operation.generation
        assert operation.request_payload["reuse"]["line_id"] == first["lines"][0]["id"]
        assert operation.request_payload["reuse"]["prepared_sha256"]
    before = (len(http.posts), len(http.uploads), len(http.gets), len(http.downloads))
    forbid_remote(monkeypatch)
    drain(c)
    assert history(synthesis_project)["selection_revision"] == 2
    with c.app.state.session_factory() as db:
        assert db.get(StageRun, run_id).status == "succeeded"
        assert db.get(PrivateOperation, operation_id).generation == generation
    assert before == (len(http.posts), len(http.uploads), len(http.gets), len(http.downloads))


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "request_missing",
        "line_id",
        "operation_id",
        "generation",
        "input_fingerprint",
        "prepared_sha256",
        "provenance_sha256",
        "producer",
    ],
)
def test_ready_alias_invalid_origin_stops_without_provider_fallback(
    synthesis_project, monkeypatch, tmp_path, corruption
):
    c, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    _, run_id, operation_id = interrupted_alias(synthesis_project, monkeypatch)
    with c.app.state.session_factory.begin() as db:
        operation = db.get(PrivateOperation, operation_id)
        request = copy.deepcopy(operation.request_payload)
        if corruption == "request_missing":
            request = None
        elif corruption == "missing":
            request.pop("reuse", None)
        elif corruption == "producer":
            db.get(PrivateOperation, request["reuse"]["operation_id"]).provider = "demucs"
        else:
            request["reuse"][corruption] = (
                "a" * 64
                if corruption.endswith("sha256")
                or corruption in {"input_fingerprint", "generation"}
                else "unowned-id"
            )
        operation.request_payload = request
        flag_modified(operation, "request_payload")
    forbid_remote(monkeypatch)
    drain(c)
    current = c.get("/api/runs/" + run_id).json()
    assert current["status"] == "needs_review"
    assert current["safe_error"]["code"] == "CONFIGURATION"
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 1


def test_multiple_interrupted_aliases_keep_original_producer_and_manual_choice(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, _, source, line, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    original = queue(synthesis_project)
    drain(c)
    original_output = history(synthesis_project)["selected_output_id"]
    _, _, alias_one = interrupted_alias(synthesis_project, monkeypatch)
    drain(c)
    _, run_id, alias_two = interrupted_alias(synthesis_project, monkeypatch)
    with c.app.state.session_factory() as db:
        for identity in (alias_one, alias_two):
            assert (
                db.get(PrivateOperation, identity).request_payload["reuse"]["line_id"]
                == original["lines"][0]["id"]
            )
    chosen = c.put(
        path(synthesis_project) + f"/segments/{line['id']}/audio-selection",
        headers=h,
        json=guard(source, line["transcript_revision"])
        | {
            "revision": 2,
            "output_id": original_output,
            "translation_revision": 1,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
        },
    )
    assert chosen.status_code == 200
    forbid_remote(monkeypatch)
    drain(c)
    result = history(synthesis_project)
    assert len(http.posts) == 1 and result["selection_revision"] == 3
    assert result["selected_output_id"] == original_output and len(result["outputs"]) == 3
    current = c.get("/api/runs/" + run_id).json()
    assert current["status"] == "succeeded"


def test_cancelled_ready_alias_can_be_explicitly_retried_locally(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    _, run_id, _ = interrupted_alias(synthesis_project, monkeypatch)
    assert c.post("/api/runs/" + run_id + "/cancel", headers=h).status_code == 200
    assert c.post("/api/runs/" + run_id + "/retry", headers=h, json={}).status_code == 200
    forbid_remote(monkeypatch)
    drain(c)
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 2


def test_fully_prepared_legacy_alias_keeps_valid_original_proof(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.dubbing.synthesis_cache import cached_payload
    from videotranslate.models.core import Project
    from videotranslate.models.synthesis import SynthesisLine

    c, h, p, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    result = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).json()
    drain(c)
    with c.app.state.session_factory.begin() as db:
        line = db.get(SynthesisLine, result["lines"][0]["id"])
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == line.run_id)
        )
        assert operation.phase == "prepared"
        operation.request_payload = {"input": operation.request_payload["input"]}
    with c.app.state.session_factory() as db:
        cached_payload(db, db.get(Project, p["id"]), db.get(SynthesisLine, line.id))
    assert history(synthesis_project)["outputs"][0]["evidence_status"] == "validated"
    assert len(http.posts) == 1


def test_ready_alias_source_edit_preserves_paid_history_without_reselection(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, p, source, line, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    original_output = history(synthesis_project)["selected_output_id"]
    queued, run_id, _ = interrupted_alias(synthesis_project, monkeypatch)
    edited = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json=guard(source, line["transcript_revision"])
        | {"revision": 1, "text": "Corrected source wording"},
    )
    assert edited.status_code == 200
    forbid_remote(monkeypatch)
    drain(c)
    state = c.get(path(synthesis_project) + "/synthesis/" + queued["id"]).json()
    assert state["lines"][0]["status"] == "succeeded"
    assert state["lines"][0]["publication"]["selected"] is False
    result = history(synthesis_project)
    assert result["selection_revision"] == 1 and result["selected_output_id"] == original_output
    assert len(result["outputs"]) == 2 and all(
        row["evidence_status"] == "validated" for row in result["outputs"]
    )
    assert c.get("/api/runs/" + run_id).json()["result"]["reused"] is True
    assert len(http.posts) == 1

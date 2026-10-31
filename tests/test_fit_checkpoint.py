"""Typed checkpoint integrity must agree across detail, recovery and publication."""
# ruff: noqa: F811

import copy

import pytest
from sqlalchemy import select, update
from test_fit_plans import endpoint, fit_payload, listen, original
from test_synthesis_domain import synthesis_project  # noqa: F401
from test_synthesis_operations import install_clone, queue
from test_translation_operations import drain

from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.finishing import FitPlanResult


@pytest.mark.parametrize(
    "tamper",
    [
        "duration_float",
        "duration_bool",
        "duration_extra",
        "checkpoint_extra",
        "checkpoint_float",
        "checkpoint_float_rehashed",
        "facts_contradiction",
        "facts_bool_count",
        "facts_float_count",
        "facts_int_feasible",
        "facts_extra",
        "binding_extra",
    ],
)
def test_ready_dub_detail_rejects_noncanonical_integrity(
    synthesis_project, monkeypatch, tmp_path, tamper
):
    from videotranslate.execution.inputs import fingerprint

    f = synthesis_project
    c, h, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    listen(f)
    response = c.post(endpoint(f), headers=h, json=fit_payload(f))
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    drain(c)
    assert c.get(endpoint(f) + "/" + identity).json()["render_eligible"]
    with c.app.state.session_factory.begin() as db:
        result = db.scalar(select(FitPlanResult))
        operation = db.get(PrivateOperation, result.operation_id)
        if tamper.startswith("duration_"):
            duration = copy.deepcopy(result.planned_output_duration)
            if tamper == "duration_float":
                duration["numerator"] = float(duration["numerator"])
            elif tamper == "duration_bool":
                duration["denominator"] = True
            else:
                duration["extra"] = 1
            db.execute(
                update(FitPlanResult)
                .where(FitPlanResult.id == result.id)
                .values(planned_output_duration=duration)
            )
        elif tamper.startswith("facts_"):
            facts = copy.deepcopy(operation.public_facts)
            key, value = {
                "facts_contradiction": ("timeline_feasible", False),
                "facts_bool_count": ("included_count", True),
                "facts_float_count": ("count", 1.0),
                "facts_int_feasible": ("timeline_feasible", 1),
                "facts_extra": ("extra", 1),
            }[tamper]
            db.execute(
                update(PrivateOperation)
                .where(PrivateOperation.id == operation.id)
                .values(public_facts=facts | {key: value})
            )
        else:
            payload = copy.deepcopy(operation.prepared_payload)
            if tamper == "binding_extra":
                payload["binding"]["extra"] = 1
            elif tamper == "checkpoint_extra":
                payload["extra"] = 1
            else:
                payload["plan"]["lines"][0]["start_ms"] = 0.0
                if tamper == "checkpoint_float_rehashed":
                    payload["payload_fingerprint"] = fingerprint(payload["plan"])
            db.execute(
                update(PrivateOperation)
                .where(PrivateOperation.id == operation.id)
                .values(prepared_payload=payload)
            )
    state = c.get(endpoint(f) + "/" + identity).json()
    assert state["plan"] is None and state["timeline_feasible"] is None
    assert state["planned_output_duration_ms"] is None and not state["render_eligible"]
    assert "FIT_PLAN_INVALID" in state["issues"]
    if tamper.startswith("duration_"):
        summary = c.get(endpoint(f)).json()["items"][0]
        assert summary["currentness"] == summary["plan_validation"] == "not_assessed"
        assert summary["captured_result"] == {
            "timeline_feasible": None,
            "planned_output_duration_ms": None,
        }


@pytest.mark.parametrize("tamper", ["count_bool", "count_float", "feasible_int"])
def test_prepared_recovery_rejects_equal_valued_facts(dubbing_project, tamper):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES
    from videotranslate.execution.worker import Worker

    c, h, _ = dubbing_project
    queued = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()

    def fail_publication(*args):
        raise RuntimeError("injected publication loss")

    registry = STAGES | {"plan_fit": replace(STAGES["plan_fit"], publish=fail_publication)}
    assert Worker(c.app.state.settings, registry=registry).run_once()
    with c.app.state.session_factory.begin() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == queued["run_id"])
        )
        key, value = {
            "count_bool": ("count", False),
            "count_float": ("count", 0.0),
            "feasible_int": ("timeline_feasible", 1),
        }[tamper]
        db.execute(
            update(PrivateOperation)
            .where(PrivateOperation.id == operation.id)
            .values(public_facts=operation.public_facts | {key: value})
        )
    assert c.post(f"/api/runs/{queued['run_id']}/retry", headers=h, json={}).status_code == 200
    assert Worker(c.app.state.settings).run_once()
    state = c.get(endpoint(dubbing_project) + "/" + queued["id"]).json()
    assert state["status"] == "needs_review" and state["plan"] is None
    with c.app.state.session_factory() as db:
        assert db.scalar(select(FitPlanResult)) is None


@pytest.mark.parametrize("tamper", ["facts_bool", "facts_float", "checkpoint_extra"])
def test_short_publisher_rejects_checkpoint_edit_after_handler(dubbing_project, tamper):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES
    from videotranslate.execution.worker import Worker

    c, h, _ = dubbing_project
    queued = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()
    handle = STAGES["plan_fit"].handle

    def after_validation(context):
        result = handle(context)
        with c.app.state.session_factory.begin() as db:
            operation = db.get(PrivateOperation, result.prepared_id)
            if tamper == "checkpoint_extra":
                values = dict(prepared_payload=operation.prepared_payload | {"extra": 1})
            else:
                values = dict(
                    public_facts=operation.public_facts
                    | {"count": False if tamper == "facts_bool" else 0.0}
                )
            db.execute(
                update(PrivateOperation).where(PrivateOperation.id == operation.id).values(**values)
            )
        return result

    registry = STAGES | {"plan_fit": replace(STAGES["plan_fit"], handle=after_validation)}
    assert Worker(c.app.state.settings, registry=registry).run_once()
    state = c.get(endpoint(dubbing_project) + "/" + queued["id"]).json()
    assert state["status"] == "failed" and state["plan"] is None
    with c.app.state.session_factory() as db:
        assert db.scalar(select(FitPlanResult)) is None

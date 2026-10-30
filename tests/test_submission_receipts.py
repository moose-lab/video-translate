"""Actual-handle receipt fencing without lease or publication transfer."""
# ruff: noqa: F811

from dataclasses import replace
from datetime import timedelta

import pytest
from dubbing_helpers import selected

from videotranslate.execution.context import RunContext
from videotranslate.execution.contracts import LeaseLost, StageFailure
from videotranslate.execution.prepared import Operations
from videotranslate.execution.service import claim_run
from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.core import Project, utcnow
from videotranslate.models.execution import StageRun


@pytest.fixture
def receipt_project(dubbing_project):
    selected(dubbing_project)
    return dubbing_project


def pending(fixture):
    c, h, p = fixture
    response = c.post(f"/api/projects/{p['id']}/runs", headers=h, json={"stage": "extract"})
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
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
    op = operations.prepare(provider="omnivoice", model="OmniVoice")
    return context, operations, op, operations.begin()


@pytest.mark.parametrize(
    "field",
    [
        "operation_id",
        "run_id",
        "project_id",
        "workspace_id",
        "generation",
        "input_fingerprint",
        "provider",
        "model",
    ],
)
def test_forged_receipt_binding_is_rejected(receipt_project, field):
    c, *_ = receipt_project
    _, operations, operation, binding = pending(receipt_project)
    with pytest.raises(LeaseLost):
        operations.accept("recorded-event", binding=replace(binding, **{field: "wrong-binding"}))
    with c.app.state.session_factory() as db:
        assert db.get(PrivateOperation, operation.id).remote_id is None
        assert db.get(StageRun, operation.run_id).remote_id is None


def test_same_generation_new_lease_receipt_is_idempotent_and_cannot_publish(receipt_project):
    c, *_ = receipt_project
    context, operations, operation, binding = pending(receipt_project)
    with c.app.state.session_factory.begin() as db:
        run = db.get(StageRun, operation.run_id)
        run.lease_token, run.lease_owner = "new-lease-token", "new-owner"
        run.lease_expires_at = utcnow() + timedelta(minutes=1)
    operations.accept("recorded-event", binding=binding)
    operations.accept("recorded-event", binding=binding)
    with pytest.raises(StageFailure):
        operations.accept("conflicting-event", binding=binding)
    with pytest.raises(LeaseLost):
        context.check_active()
    with c.app.state.session_factory() as db:
        run = db.get(StageRun, operation.run_id)
        assert run.remote_id == "recorded-event" and run.lease_token == "new-lease-token"
        assert (
            run.status == "running"
            and db.get(PrivateOperation, operation.id).remote_id == "recorded-event"
        )


@pytest.mark.parametrize("state", ["cancelled", "deleted", "source_edited"])
def test_obsolete_or_cancelled_work_keeps_receipt_without_publication(receipt_project, state):
    c, *_ = receipt_project
    _, operations, operation, binding = pending(receipt_project)
    with c.app.state.session_factory.begin() as db:
        run = db.get(StageRun, operation.run_id)
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        if state == "cancelled":
            run.cancel_requested_at = utcnow()
        elif state == "deleted":
            db.get(Project, operation.project_id).deleted_at = utcnow()
        else:
            run.is_stale = True
    operations.accept("recorded-event", binding=binding)
    with c.app.state.session_factory() as db:
        assert db.get(PrivateOperation, operation.id).remote_id == "recorded-event"
        assert db.get(StageRun, operation.run_id).remote_id == "recorded-event"
        from sqlalchemy import select

        from videotranslate.models.core import Asset

        assert db.scalar(select(Asset.id).where(Asset.kind == "natural_audio")) is None


def test_default_acceptance_still_requires_active_lease(receipt_project):
    c, *_ = receipt_project
    _, operations, operation, _ = pending(receipt_project)
    with c.app.state.session_factory.begin() as db:
        db.get(StageRun, operation.run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    with pytest.raises(LeaseLost):
        operations.accept("recorded-event")
    with c.app.state.session_factory() as db:
        assert db.get(PrivateOperation, operation.id).remote_id is None

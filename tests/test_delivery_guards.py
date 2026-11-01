"""Delivery admission and late publication reject stale, foreign and corrupt inputs."""

import copy

import pytest
from sqlalchemy import select
from test_deliveries import base, body, fit_original
from test_translation_operations import drain

from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.core import Asset
from videotranslate.models.delivery import DeliveryCommand
from videotranslate.models.finishing import FitPlanCommand, FitPlanResult


@pytest.mark.parametrize("change", ["run", "purpose", "rate", "gain", "track", "path"])
def test_delivery_request_is_explicit_strict_and_owned(dubbing_project, change):
    c, h, _ = dubbing_project
    request = body(fit_original(dubbing_project))
    if change == "run":
        request["expected_fit_run_id"] = "foreign"
    if change == "purpose":
        request["purpose"] = "dub"
    if change == "rate":
        request["frame_rate"] = {"numerator": 27, "denominator": 1}
    if change == "gain":
        request["background_gain"] = True
    if change == "track":
        request["default_audio_track"] = "zh"
    if change == "path":
        request["source_path"] = "/tmp/foreign.mp4"
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=request)
    assert response.status_code in {409, 422}, response.text
    assert c.get(base(dubbing_project) + "/deliveries").json()["total"] == 0


def test_corrupt_producing_parent_checkpoint_blocks_admission(dubbing_project):
    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    with c.app.state.session_factory.begin() as db:
        result = db.scalar(select(FitPlanResult))
        operation = db.get(PrivateOperation, result.operation_id)
        data = copy.deepcopy(operation.prepared_payload)
        data["binding"]["generation"] = "forged"
        operation.prepared_payload = data
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("change", ["checkpoint", "source_bytes", "source_selection"])
def test_queued_delivery_never_publishes_changed_inputs(dubbing_project, change):
    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    assert response.status_code == 202, response.text
    if change == "source_selection":
        with c.app.state.session_factory() as db:
            parent = db.get(FitPlanCommand, plan["id"])
            state = dict(source_asset_id=parent.source_asset_id)
        state["revision"] = c.get(base(dubbing_project)).json()["revision"]
        response_selection = c.put(
            base(dubbing_project) + "/source-selection",
            headers=h,
            json=dict(
                revision=state["revision"],
                source_asset_id=state["source_asset_id"],
                audio_ordinal=0,
                start_ms=100,
                end_ms=1800,
            ),
        )
        assert response_selection.status_code == 200, response_selection.text
    else:
        with c.app.state.session_factory.begin() as db:
            parent = db.get(FitPlanCommand, plan["id"])
            if change == "checkpoint":
                result = db.scalar(select(FitPlanResult))
                operation = db.get(PrivateOperation, result.operation_id)
                operation.model = "forged"
            else:
                asset = db.get(Asset, parent.source_asset_id)
        if change == "source_bytes":
            import io

            c.app.state.storage.put(asset.storage_key, io.BytesIO(b"changed bytes"), "video/mp4")
    drain(c)
    detail = c.get(base(dubbing_project) + "/deliveries/" + response.json()["id"]).json()
    assert detail["status"] in {"stale", "failed", "cancelled", "needs_review"}, detail
    assert detail["artifacts"] == []
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(Asset).where(Asset.kind == "delivery_movie")).all()


def test_guarded_admission_rechecks_after_external_validation(dubbing_project, monkeypatch):
    from videotranslate.dubbing import deliveries
    from videotranslate.execution.inputs import fingerprint

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    original = deliveries.valid_parent

    def race(db, project, parent):
        captured = original(db, project, parent)
        db.commit()
        with c.app.state.session_factory.begin() as other:
            result = other.scalar(select(FitPlanResult))
            data = copy.deepcopy(result.plan)
            data["source_duration_ms"] = 1999
            result.plan = data
            result.payload_fingerprint = fingerprint(data)
        return captured

    monkeypatch.setattr(deliveries, "valid_parent", race)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    assert response.status_code == 409, response.text
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(DeliveryCommand)).all()


def test_media_and_strict_fit_validation_do_not_hold_sql_transactions(dubbing_project, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from videotranslate.dubbing import fit_snapshot
    from videotranslate.media import delivery_export, fit_audio, fit_video

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    live = set()

    def opened(session, transaction, connection):
        live.add(id(session))

    def closed(session, transaction):
        if transaction.parent is None:
            live.discard(id(session))

    event.listen(Session, "after_begin", opened)
    event.listen(Session, "after_transaction_end", closed)
    seen = []

    def guarded(module, name):
        real = getattr(module, name)

        def wrapper(*args, **kw):
            assert not live, "CPU/decode holds SQL transaction"
            seen.append(name)
            return real(*args, **kw)

        monkeypatch.setattr(module, name, wrapper)

    for module, name in [
        (fit_video, "retime_video"),
        (fit_audio, "retime_audio"),
        (delivery_export, "mux"),
        (fit_snapshot, "validate_plan"),
    ]:
        guarded(module, name)
    try:
        response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
        assert response.status_code == 202, response.text
        drain(c)
        result = c.get(base(dubbing_project) + "/deliveries/" + response.json()["id"]).json()
        assert result["status"] == "succeeded", result
        assert {"retime_video", "retime_audio", "mux", "validate_plan"} <= set(seen)
    finally:
        event.remove(Session, "after_begin", opened)
        event.remove(Session, "after_transaction_end", closed)


def test_cancellation_during_render_has_no_published_delivery(dubbing_project, monkeypatch):
    from videotranslate.media import fit_video

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    intent = response.json()
    original = fit_video.retime_video

    def cancel(*args, **kw):
        cancelled = c.post("/api/runs/" + intent["run_id"] + "/cancel", headers=h)
        assert cancelled.status_code == 200, cancelled.text
        return original(*args, **kw)

    monkeypatch.setattr(fit_video, "retime_video", cancel)
    drain(c)
    detail = c.get(base(dubbing_project) + "/deliveries/" + intent["id"]).json()
    assert detail["status"] == "cancelled" and detail["artifacts"] == []


def test_late_prepared_metadata_mutation_cannot_publish_asset(dubbing_project, monkeypatch):
    from dataclasses import replace

    from videotranslate.execution.prepared import current_operation
    from videotranslate.execution.registry import STAGES
    from videotranslate.models.analysis import PreparedObject

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    original = STAGES["deliver"]

    def corrupt(db, run, result):
        operation = current_operation(db, run)
        item = db.get(PreparedObject, operation.prepared_payload["objects"][0])
        data = dict(item.metadata_json)
        data["sha256"] = "e" * 64
        item.metadata_json = data
        return original.publish(db, run, result)

    monkeypatch.setitem(STAGES, "deliver", replace(original, publish=corrupt))
    drain(c)
    detail = c.get(base(dubbing_project) + "/deliveries/" + response.json()["id"]).json()
    assert detail["status"] == "failed" and detail["artifacts"] == []
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(Asset).where(Asset.kind.like("delivery_%"))).all()

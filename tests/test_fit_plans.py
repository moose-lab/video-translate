"""Guarded owned CPU plans; recording natural providers exist only in fixtures."""
# ruff: noqa: F811

import copy

import pytest
from dubbing_helpers import guard, selected
from sqlalchemy import select
from test_synthesis_domain import synthesis_project  # noqa: F401
from test_synthesis_operations import history, install_clone, queue
from test_translation_operations import drain

from videotranslate.execution.worker import Worker
from videotranslate.models.execution import StageRun


def endpoint(fixture):
    return f"/api/projects/{fixture[2]['id']}/fit-plans"


def original(fixture):
    return guard(selected(fixture)) | dict(settings_revision=0, purpose="original_only", tracks=[])


def test_original_only_is_durable_command_and_computed_identity(dubbing_project):
    c, h, _ = dubbing_project
    payload = original(dubbing_project)
    response = c.post(endpoint(dubbing_project), headers=h, json=payload)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["purpose"] == "original_only" and result["timeline_feasible"] is None
    assert result["plan"] is None and not result["dub_ready"] and not result["reused"]
    again = c.post(endpoint(dubbing_project), headers=h, json=payload)
    assert again.json()["id"] == result["id"] and again.json()["reused"] is True
    assert Worker(c.app.state.settings).run_once()
    detail = c.get(endpoint(dubbing_project) + "/" + result["id"]).json()
    assert detail["status"] == "succeeded", detail
    assert detail["timeline_feasible"] is True and detail["current"] is True
    assert not detail["dub_ready"] and not detail["render_eligible"]
    assert detail["plan"]["lines"] == [] and len(detail["plan"]["pieces"]) == 1
    assert c.get(endpoint(dubbing_project)).json()["items"][0]["id"] == result["id"]
    assert c.post(endpoint(dubbing_project), json=payload).status_code == 403
    assert c.get(endpoint(dubbing_project) + "?limit=101").status_code == 422
    assert (
        c.post(
            f"/api/projects/{dubbing_project[2]['id']}/runs",
            headers=h,
            json={"stage": "plan_fit", "options": {"command_id": result["id"]}},
        ).status_code
        == 422
    )


def fit_payload(fixture, purpose="dub", *, accepted=False):
    c, h, p, s, line, track, *_ = fixture
    audio = history(fixture)
    output = audio["outputs"][0] if audio["outputs"] else None
    return guard(s, line["transcript_revision"]) | dict(
        settings_revision=0,
        purpose=purpose,
        tracks=[
            dict(
                tag=track["tag"],
                segments=[
                    dict(
                        id=line["id"],
                        expected_source_text_fingerprint=line["source_text_fingerprint"],
                        expected_source_revision_id=line["revision_id"],
                        translation_revision=1,
                        selection_revision=audio["selection_revision"],
                        output_id=audio["selected_output_id"],
                        review_revision=output["review_revision"] if output else 0,
                        qc_evidence_fingerprint=output["qc_evidence_fingerprint"]
                        if output
                        else None,
                    )
                ],
            )
        ],
    )


def listen(fixture):
    payload = fit_payload(fixture)["tracks"][0]["segments"][0]
    review = {
        k: v
        for k, v in payload.items()
        if k not in {"id", "selection_revision", "review_revision", "expected_source_revision_id"}
    }
    review.update(
        revision=payload["review_revision"],
        audio_selection_revision=payload["selection_revision"],
        decision="accepted",
    )
    response = fixture[0].put(
        f"/api/projects/{fixture[2]['id']}/language-tracks/{fixture[5]['tag']}/segments/{fixture[4]['id']}/audio-review",
        headers=fixture[1],
        json=guard(fixture[3], fixture[4]["transcript_revision"]) | review,
    )
    assert response.status_code == 200, response.text
    assert response.json()["ready"]


def test_preview_preserves_pending_listening_and_dub_requires_acceptance(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    payload = fit_payload(synthesis_project)
    response = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert response.status_code == 409, response.text
    payload["purpose"] = "incomplete_preview"
    preview = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert preview.status_code == 202, preview.text
    assert preview.json()["lines"][0]["included"]
    assert "LISTENING_NOT_ASSESSED" in preview.json()["lines"][0]["issues"]
    drain(c)
    state = c.get(endpoint(synthesis_project) + "/" + preview.json()["id"]).json()
    assert (
        state["timeline_feasible"]
        and not state["render_eligible"]
        and state["purpose"] == "incomplete_preview"
    )
    listen(synthesis_project)
    assert not c.get(endpoint(synthesis_project) + "/" + preview.json()["id"]).json()["current"]
    accepted = c.post(endpoint(synthesis_project), headers=h, json=fit_payload(synthesis_project))
    assert accepted.status_code == 202, accepted.text
    drain(c)
    complete = c.get(endpoint(synthesis_project) + "/" + accepted.json()["id"]).json()
    assert complete["dub_ready"] and complete["render_eligible"] and complete["timeline_feasible"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("translation_revision", 0),
        ("selection_revision", 0),
        ("review_revision", 9),
        ("expected_source_text_fingerprint", "a" * 64),
        ("qc_evidence_fingerprint", "b" * 64),
        ("output_id", "unowned"),
    ],
)
def test_supplied_cell_proofs_are_cas_and_no_partial_writes(
    synthesis_project, monkeypatch, tmp_path, key, value
):
    c, h, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    payload = fit_payload(synthesis_project, "incomplete_preview")
    payload["tracks"][0]["segments"][0][key] = value
    response = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert response.status_code in {404, 409}, response.text
    assert c.get(endpoint(synthesis_project)).json()["total"] == 0
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(StageRun).where(StageRun.stage == "plan_fit")).all()


def test_missing_preview_is_excluded_and_duplicate_alias_rejected(synthesis_project):
    c, h, *_ = synthesis_project
    payload = fit_payload(synthesis_project, "incomplete_preview")
    result = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert result.status_code == 202, result.text
    assert not result.json()["lines"][0]["included"]
    assert "AUDIO_REQUIRED" in result.json()["lines"][0]["issues"]
    payload["tracks"].append(copy.deepcopy(payload["tracks"][0]))
    assert c.post(endpoint(synthesis_project), headers=h, json=payload).status_code == 422


def test_result_reader_rejects_wrong_producing_operation(dubbing_project):
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.finishing import FitPlanResult

    c, h, _ = dubbing_project
    admitted = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()
    drain(c)
    with c.app.state.session_factory.begin() as db:
        record = db.scalar(select(FitPlanResult))
        operation = db.get(PrivateOperation, record.operation_id)
        operation.model = "unrelated_policy"
    detail = c.get(endpoint(dubbing_project) + "/" + admitted["id"]).json()
    assert detail["plan"] is None and "FIT_PLAN_INVALID" in detail["issues"]


def test_cpu_math_and_restart_validation_run_outside_sql(dubbing_project, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from videotranslate.dubbing import fit_snapshot
    from videotranslate.media import fit_plan

    c, h, _ = dubbing_project
    live = set()

    def opened(session, transaction, connection):
        live.add(id(session))

    def closed(session, transaction):
        if transaction.parent is None:
            live.discard(id(session))

    event.listen(Session, "after_begin", opened)
    event.listen(Session, "after_transaction_end", closed)
    seen = []
    build, validate = fit_plan.build_plan, fit_snapshot.validate_plan

    def outside_build(*args, **kw):
        assert not live, "Full fit calculation holds a SQL transaction"
        seen.append("build")
        return build(*args, **kw)

    def outside_validate(*args, **kw):
        assert not live, "Strict fit validation holds a SQL transaction"
        seen.append("validate")
        return validate(*args, **kw)

    monkeypatch.setattr(fit_plan, "build_plan", outside_build)
    monkeypatch.setattr(fit_snapshot, "validate_plan", outside_validate)
    try:
        response = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project))
        assert response.status_code == 202, response.text
        drain(c)
        result = c.get(endpoint(dubbing_project) + "/" + response.json()["id"]).json()
        assert result["status"] == "succeeded" and result["plan"], result
        assert "build" in seen and "validate" in seen
    finally:
        event.remove(Session, "after_begin", opened)
        event.remove(Session, "after_transaction_end", closed)


@pytest.mark.parametrize("damaged", [False, True])
def test_prepared_success_survives_failed_publication_and_strict_resume(
    dubbing_project, monkeypatch, damaged
):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.finishing import FitPlanResult

    c, h, _ = dubbing_project
    queued = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()

    def fail_publication(*args):
        raise RuntimeError("test injected publication loss")

    registry = STAGES | {"plan_fit": replace(STAGES["plan_fit"], publish=fail_publication)}
    assert Worker(c.app.state.settings, registry=registry).run_once()
    with c.app.state.session_factory.begin() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == queued["run_id"])
        )
        assert operation.phase == "prepared" and operation.prepared_payload["plan"]
        original_operation = operation.id
        assert db.scalar(select(FitPlanResult)) is None
        if damaged:
            payload = copy.deepcopy(operation.prepared_payload)
            payload["plan"]["policy"] = "unrecognized"
            operation.prepared_payload = payload
    retry = c.post(f"/api/runs/{queued['run_id']}/retry", headers=h, json={})
    assert retry.status_code == 200, retry.text
    # Replay does full strict validation, but never another command/operation/remote lifecycle.
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory() as db:
        assert (
            db.scalar(
                select(PrivateOperation).where(PrivateOperation.run_id == queued["run_id"])
            ).id
            == original_operation
        )
        record = db.scalar(select(FitPlanResult))
        assert (record is None) == damaged
    state = c.get(endpoint(dubbing_project) + "/" + queued["id"]).json()
    assert state["status"] == ("needs_review" if damaged else "succeeded"), state


@pytest.mark.parametrize(
    "edit", ["settings", "review", "target", "source", "selection", "cancel", "lease"]
)
def test_mutations_during_calculation_do_not_publish(
    synthesis_project, monkeypatch, tmp_path, edit
):
    from videotranslate.media import fit_plan
    from videotranslate.models.core import utcnow
    from videotranslate.models.finishing import FitPlanResult

    c, h, p, s, line, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    listen(synthesis_project)
    queued = c.post(
        endpoint(synthesis_project), headers=h, json=fit_payload(synthesis_project)
    ).json()
    build = fit_plan.build_plan
    changed = False

    def mutate(*args, **kw):
        nonlocal changed
        plan = build(*args, **kw)
        if not changed:
            changed = True
            if edit == "settings":
                from test_fit_settings import defaults

                settings = defaults() | {"max_borrow_ms": 1}
                assert (
                    c.put(
                        f"/api/projects/{p['id']}/fit-settings",
                        headers=h,
                        json=dict(revision=0, settings=settings),
                    ).status_code
                    == 200
                )
            elif edit == "review":
                listen(synthesis_project)
            elif edit == "target":
                assert (
                    c.patch(
                        f"/api/projects/{p['id']}/language-tracks/zh-Hant/segments/{line['id']}",
                        headers=h,
                        json=guard(s, line["transcript_revision"])
                        | dict(
                            revision=1,
                            expected_source_text_fingerprint=line["source_text_fingerprint"],
                            text="Changed target",
                        ),
                    ).status_code
                    == 200
                )
            elif edit == "source":
                assert (
                    c.patch(
                        f"/api/projects/{p['id']}/segments/{line['id']}",
                        headers=h,
                        json=guard(s, line["transcript_revision"])
                        | dict(revision=line["revision"], end_ms=900),
                    ).status_code
                    == 200
                )
            elif edit == "selection":
                # New immutable natural selection version, even when selecting same validated bytes.
                from videotranslate.models.core import new_id
                from videotranslate.models.synthesis import AudioSelection, AudioSelectionVersion

                with c.app.state.session_factory.begin() as db:
                    root = db.scalar(select(AudioSelection))
                    old = db.get(AudioSelectionVersion, root.current_version_id)
                    version = AudioSelectionVersion(
                        id=new_id(),
                        project_id=root.project_id,
                        workspace_id=root.workspace_id,
                        selection_id=root.id,
                        track_id=root.track_id,
                        segment_id=root.segment_id,
                        output_id=old.output_id,
                        parent_version_id=old.id,
                        revision=root.revision + 1,
                        actor_id=old.actor_id,
                        provenance="manual",
                    )
                    db.add(version)
                    db.flush()
                    root.current_version_id = version.id
                    root.revision = version.revision
            elif edit == "cancel":
                assert c.post(f"/api/runs/{queued['run_id']}/cancel", headers=h).status_code == 200
            else:
                with c.app.state.session_factory.begin() as db:
                    db.get(StageRun, queued["run_id"]).lease_expires_at = utcnow()
        return plan

    monkeypatch.setattr(fit_plan, "build_plan", mutate)
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory() as db:
        assert db.scalar(select(FitPlanResult)) is None
    state = c.get(endpoint(synthesis_project) + "/" + queued["id"]).json()
    assert (
        state["plan"] is None
        and state["timeline_feasible"] is None
        and not state["render_eligible"]
    )


@pytest.mark.parametrize(
    "tamper",
    ["policy", "extra", "missing", "bool", "float", "duplicate", "duration", "cell", "settings"],
)
def test_strict_stored_projection_rejects_tampering(tamper):
    from videotranslate.dubbing.fit_snapshot import validate_stored
    from videotranslate.media.fit_plan import build_plan, plan_json
    from videotranslate.media.fit_types import FitLine

    data = plan_json(build_plan(2000, [FitLine("track", "segment", None, 0, 1000, 800)]))
    snapshot = dict(policy="shared_fit_v1", start_ms=0, end_ms=2000, settings=data["settings"])
    rows = [
        dict(
            included=True,
            track_id="track",
            segment_id="segment",
            role_id=None,
            start_ms=0,
            end_ms=1000,
            natural_duration_ms=800,
        )
    ]
    if tamper == "policy":
        data["policy"] = "foreign"
    elif tamper == "extra":
        data["secret"] = "unallowed"
    elif tamper == "missing":
        del data["pieces"]
    elif tamper == "bool":
        data["lines"][0]["start_ms"] = False
    elif tamper == "float":
        data["output_duration_ms"]["numerator"] = 2000.0
    elif tamper == "duplicate":
        data["lines"] *= 2
    elif tamper == "duration":
        rows[0]["natural_duration_ms"] = 900
    elif tamper == "cell":
        rows[0]["segment_id"] = "other"
    else:
        snapshot["settings"] = snapshot["settings"] | dict(max_borrow_ms=1)
    with pytest.raises(ValueError):
        validate_stored(data, snapshot, rows)


def test_infeasible_plan_is_successful_review_with_null_voice_endpoint(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, p, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    from test_voice_references import wav_bytes

    http.output = wav_bytes(1.5)
    queue(synthesis_project)
    drain(c)
    listen(synthesis_project)
    queued = c.post(endpoint(synthesis_project), headers=h, json=fit_payload(synthesis_project))
    assert queued.status_code == 202, queued.text
    drain(c)
    result = c.get(endpoint(synthesis_project) + "/" + queued.json()["id"]).json()
    assert result["status"] == "succeeded" and result["timeline_feasible"] is False
    assert result["dub_ready"] and not result["render_eligible"]
    assert result["plan"]["issues"][0]["code"] == "LINE_FIT_LIMIT"
    assert result["plan"]["placements"][0]["voice_end_ms"] is None


def test_shared_event_fit_extensions_are_strict_bounded_and_old_facts_survive():
    from videotranslate.execution.events import safe_facts

    assert safe_facts({"count": 2000, "status": "succeeded"}) == {
        "count": 2000,
        "status": "succeeded",
    }
    for bad in (
        {"purpose": []},
        {"purpose": {}},
        {"purpose": True},
        {"included_count": 1001},
        {"planned_output_duration_ms": {"numerator": True, "denominator": 1}},
        {"planned_output_duration_ms": {"numerator": 1, "denominator": 10**20}},
        {"planned_output_duration_ms": {"numerator": 200, "denominator": 2}},
    ):
        with pytest.raises(ValueError):
            safe_facts(bad)


def test_operations_cache_keeps_default_limit_and_bounds_fit_headroom():
    from videotranslate.execution.prepared import Operations

    operations = Operations(None)
    # Oversize rejects before consulting a lease/context, preserving every existing stage's default.
    with pytest.raises(ValueError):
        operations.cache({"payload": "x" * (2 * 1024 * 1024)}, {})
    for limit in (True, 1, 3 * 1024 * 1024):
        with pytest.raises(ValueError):
            operations.cache({}, {}, payload_limit=limit)


def test_two_target_roles_preview_masks_and_display_gain_independence(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import create_line, make_track

    c, h, p, s, line, track, ref = synthesis_project
    base = f"/api/projects/{p['id']}"
    roles = [
        c.post(base + "/speakers", headers=h, json=dict(name=name)).json()
        for name in ("Role A", "Role B")
    ]
    first = c.patch(
        base + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | dict(revision=line["revision"], speaker_id=roles[0]["id"]),
    )
    assert first.status_code == 200, first.text
    line = first.json()
    second = create_line(
        (c, h, p),
        s,
        "Second line",
        transcript=line["transcript_revision"],
        start_ms=1000,
        end_ms=1800,
    )["segment"]
    second = c.patch(
        base + f"/segments/{second['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | dict(revision=second["revision"], speaker_id=roles[1]["id"]),
    ).json()
    make_track(c, h, base, "ja")
    for tag in ("zh-Hant", "ja"):
        for source in (line, second):
            if tag == "zh-Hant" and source["id"] == line["id"]:
                continue
            response = c.patch(
                base + f"/language-tracks/{tag}/segments/{source['id']}",
                headers=h,
                json=guard(s, line["transcript_revision"])
                | dict(
                    revision=0,
                    expected_source_text_fingerprint=source["source_text_fingerprint"],
                    text="Current target",
                    approved=True,
                ),
            )
            assert response.status_code == 200, response.text
    assert (
        c.put(
            base + f"/segments/{second['id']}/reference",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | dict(
                revision=0,
                expected_segment_revision=second["revision"],
                reference_version_id=ref["id"],
            ),
        ).status_code
        == 200
    )
    install_clone(monkeypatch, tmp_path)
    for tag, source in (("zh-Hant", line), ("ja", second)):
        response = c.post(
            base + f"/language-tracks/{tag}/synthesize",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | dict(
                segments=[
                    dict(
                        id=source["id"],
                        translation_revision=1,
                        expected_source_text_fingerprint=source["source_text_fingerprint"],
                        selection_revision=0,
                    )
                ]
            ),
        )
        assert response.status_code == 202, response.text
    drain(c)
    tracks = []
    for tag in ("zh-Hant", "ja"):
        rows = []
        for source in (line, second):
            audio = c.get(
                base + f"/language-tracks/{tag}/segments/{source['id']}/audio-history"
            ).json()
            output = audio["outputs"][0] if audio["outputs"] else None
            rows.append(
                dict(
                    id=source["id"],
                    expected_source_revision_id=source["revision_id"],
                    expected_source_text_fingerprint=source["source_text_fingerprint"],
                    translation_revision=1,
                    selection_revision=audio["selection_revision"],
                    output_id=audio["selected_output_id"],
                    review_revision=output["review_revision"] if output else 0,
                    qc_evidence_fingerprint=output["qc_evidence_fingerprint"] if output else None,
                )
            )
        tracks.append(dict(tag=tag, segments=rows))
    payload = guard(s, line["transcript_revision"]) | dict(
        settings_revision=0, purpose="incomplete_preview", tracks=tracks
    )
    response = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert response.status_code == 202, response.text
    captured = response.json()
    assert {t["tag"]: t["included_segment_ids"] for t in captured["tracks"]} == {
        "zh-Hant": [line["id"]],
        "ja": [second["id"]],
    }
    assert {r["role_id"] for r in captured["lines"]} == {r["id"] for r in roles}
    assert (
        c.patch(
            base + f"/speakers/{roles[0]['id']}",
            headers=h,
            json=dict(revision=1, name="Display renamed"),
        ).status_code
        == 200
    )
    with c.app.state.session_factory.begin() as db:
        from videotranslate.models.core import Project

        db.get(Project, p["id"]).settings = {"gains": {"voice": 0.5}, "subtitles": {"show": True}}
    drain(c)
    detail = c.get(endpoint(synthesis_project) + "/" + captured["id"] + "?limit=1&offset=1").json()
    assert detail["current"] and detail["timeline_feasible"] and len(detail["lines"]) == 1
    assert len(detail["plan"]["lines"]) == 2 and detail["total"] == 4
    # Duplicate aliases resolve before inserts; cross-cell output ID never becomes an omission.
    bad = copy.deepcopy(payload)
    bad["tracks"].append(copy.deepcopy(bad["tracks"][0]))
    bad["tracks"][-1]["tag"] = "ZH-HANT"
    assert c.post(endpoint(synthesis_project), headers=h, json=bad).status_code == 422
    bad = copy.deepcopy(payload)
    bad["tracks"][1]["segments"][0]["output_id"] = bad["tracks"][0]["segments"][0]["output_id"]
    assert c.post(endpoint(synthesis_project), headers=h, json=bad).status_code == 422
    payload["purpose"] = "dub"
    assert c.post(endpoint(synthesis_project), headers=h, json=payload).status_code == 409


def test_valid_thousand_line_projection_over_one_mib_and_explicit_two_mib_limit(monkeypatch):
    from fractions import Fraction
    from uuid import UUID

    from videotranslate.dubbing import fit_snapshot
    from videotranslate.dubbing.fit_plans import json_size
    from videotranslate.media.fit_plan import build_plan, plan_json
    from videotranslate.media.fit_types import FitLine, FitSettings

    lines = [
        FitLine(
            str(UUID(int=1)),
            str(UUID(int=100 + i)),
            str(UUID(int=1200 + i)),
            i * 1800 + 100,
            i * 1800 + 1100,
            1600,
        )
        for i in range(1000)
    ]
    data = plan_json(
        build_plan(1_800_000, lines, FitSettings("smart", Fraction(6, 5), Fraction(2), 113))
    )
    assert len(data["pieces"]) == 3001 and 1024 * 1024 < json_size(data) < fit_snapshot.PLAN_LIMIT
    snapshot = dict(policy="shared_fit_v1", start_ms=0, end_ms=1_800_000, settings=data["settings"])
    rows = [
        dict(
            included=True,
            track_id=r.track_key,
            segment_id=r.segment_key,
            role_id=r.role_key,
            start_ms=r.start_ms,
            end_ms=r.end_ms,
            natural_duration_ms=r.natural_duration_ms,
        )
        for r in lines
    ]
    assert len(fit_snapshot.validate_stored(data, snapshot, rows).lines) == 1000
    monkeypatch.setattr(fit_snapshot, "PLAN_LIMIT", json_size(data) - 1)
    with pytest.raises(ValueError):
        fit_snapshot.validate_stored(data, snapshot, rows)


def test_empty_prepared_checkpoint_is_not_silently_recomputed(dubbing_project, monkeypatch):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.finishing import FitPlanResult

    c, h, _ = dubbing_project
    queued = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()

    def fail(*args):
        raise RuntimeError("injected loss")

    assert Worker(
        c.app.state.settings,
        registry=STAGES | {"plan_fit": replace(STAGES["plan_fit"], publish=fail)},
    ).run_once()
    with c.app.state.session_factory.begin() as db:
        db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == queued["run_id"])
        ).prepared_payload = None
    assert c.post(f"/api/runs/{queued['run_id']}/retry", headers=h, json={}).status_code == 200
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory() as db:
        assert db.scalar(select(FitPlanResult)) is None

    assert c.get(endpoint(dubbing_project) + "/" + queued["id"]).json()["status"] == "needs_review"


def test_summary_projects_no_map_and_does_not_imply_currentness(dubbing_project):
    from sqlalchemy import event

    c, h, _ = dubbing_project
    c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()
    drain(c)
    statements = []

    def observed(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(c.app.state.engine, "before_cursor_execute", observed)
    try:
        response = c.get(endpoint(dubbing_project))
    finally:
        event.remove(c.app.state.engine, "before_cursor_execute", observed)
    item = response.json()["items"][0]
    assert item["currentness"] == "not_assessed" and item["current"] is None
    assert (
        item["plan_validation"] == "not_assessed"
        and item["audio_eligible"] is None
        and item["render_eligible"] is None
    )
    assert item["captured_result"]["timeline_feasible"] is True
    assert not any(
        "fit_plan_results.plan," in query
        or "fit_plan_results.plan " in query
        or "fit_plan_commands.snapshot" in query
        or "fit_plan_lines" in query
        for query in statements
    )


def test_corrupt_owned_capture_column_is_visible_invalid_result(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.models.finishing import FitPlanLine

    c, h, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    queued = c.post(
        endpoint(synthesis_project),
        headers=h,
        json=fit_payload(synthesis_project, "incomplete_preview"),
    ).json()
    drain(c)
    with c.app.state.session_factory.begin() as db:
        db.scalar(select(FitPlanLine)).included = False
    detail = c.get(endpoint(synthesis_project) + "/" + queued["id"]).json()
    assert (
        not detail["current"] and detail["plan"] is None and "FIT_PLAN_INVALID" in detail["issues"]
    )


def test_fit_cache_headroom_is_supported_without_changing_other_stage_defaults(dubbing_project):
    from videotranslate.dubbing.fit_snapshot import OPERATION_LIMIT
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import claim_run

    c, h, _ = dubbing_project
    c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()
    with c.app.state.session_factory.begin() as db:
        run = claim_run(db, "headroom-test")
    context = RunContext(
        c.app.state.session_factory,
        c.app.state.storage,
        c.app.state.settings,
        run.id,
        run.lease_token,
    )
    operations = Operations(context)
    operation = operations.prepare(provider="cpu", model="shared_fit_v1")
    payload = {"payload": "x" * (2 * 1024 * 1024 + 10_000)}
    assert operations.cache(payload, {}, payload_limit=OPERATION_LIMIT).prepared_id == operation.id


def test_command_structure_limits_and_extra_fields_are_strict():
    from pydantic import ValidationError

    from videotranslate.dubbing.fit_contracts import FitPlanCreate

    row = dict(
        id="a",
        expected_source_revision_id="revision",
        expected_source_text_fingerprint="a" * 64,
        translation_revision=0,
        selection_revision=0,
        output_id=None,
        review_revision=0,
        qc_evidence_fingerprint=None,
    )
    base = dict(
        selection_revision=1,
        transcript_revision="t",
        settings_revision=0,
        purpose="incomplete_preview",
        tracks=[dict(tag="ja", segments=[row])],
    )
    for changes in (
        dict(settings_revision=True),
        dict(selection_revision=0),
        dict(tracks=[]),
        dict(purpose="original_only"),
        dict(extra=True),
        dict(tracks=[dict(tag="ja", segments=[])]),
    ):
        with pytest.raises(ValidationError):
            FitPlanCreate.model_validate(base | changes)
    rows = [row | dict(id=str(i)) for i in range(1000)]
    assert (
        len(
            FitPlanCreate.model_validate(base | dict(tracks=[dict(tag="ja", segments=rows)]))
            .tracks[0]
            .segments
        )
        == 1000
    )
    with pytest.raises(ValidationError):
        FitPlanCreate.model_validate(
            base | dict(tracks=[dict(tag="ja", segments=rows), dict(tag="en", segments=[row])])
        )


@pytest.mark.parametrize("edit", ["span", "role"])
def test_source_revision_cas_covers_timing_and_role_before_admission(
    synthesis_project, monkeypatch, tmp_path, edit
):
    c, h, p, s, line, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    payload = fit_payload(synthesis_project, "incomplete_preview")
    assert "expected_source_revision_id" in payload["tracks"][0]["segments"][0]
    response = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert response.status_code == 202, response.text
    fields = dict(end_ms=900)
    if edit == "role":
        role = c.post(
            f"/api/projects/{p['id']}/speakers", headers=h, json=dict(name="New assignment")
        ).json()
        fields = dict(speaker_id=role["id"])
    response = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"]) | dict(revision=line["revision"]) | fields,
    )
    assert response.status_code == 200, response.text
    response = c.post(endpoint(synthesis_project), headers=h, json=payload)
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("field", ["timeline_feasible", "planned_output_duration", "issues"])
def test_result_summary_cannot_contradict_validated_map(dubbing_project, field):
    from videotranslate.models.finishing import FitPlanResult

    c, h, _ = dubbing_project
    queued = c.post(endpoint(dubbing_project), headers=h, json=original(dubbing_project)).json()
    drain(c)
    with c.app.state.session_factory.begin() as db:
        record = db.scalar(select(FitPlanResult))
        setattr(
            record,
            field,
            False
            if field == "timeline_feasible"
            else {"numerator": 1, "denominator": 1}
            if field == "planned_output_duration"
            else [{"code": "LINE_FIT_LIMIT", "track_key": None, "segment_key": None}],
        )
    detail = c.get(endpoint(dubbing_project) + "/" + queued["id"]).json()
    assert (
        detail["plan"] is None
        and detail["timeline_feasible"] is None
        and "FIT_PLAN_INVALID" in detail["issues"]
    )


def test_preview_purpose_remains_explicit_even_when_current_audio_is_eligible(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    listen(synthesis_project)
    queued = c.post(
        endpoint(synthesis_project),
        headers=h,
        json=fit_payload(synthesis_project, "incomplete_preview"),
    ).json()
    drain(c)
    detail = c.get(endpoint(synthesis_project) + "/" + queued["id"]).json()
    assert detail["audio_eligible"] and detail["purpose"] == "incomplete_preview"
    assert not detail["dub_ready"] and not detail["render_eligible"]

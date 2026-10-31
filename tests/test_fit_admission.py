"""Atomic fit admission releases its write lock before authoritative detail reads."""
# ruff: noqa: F811

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from dubbing_helpers import create_line, guard, make_track, selected
from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session
from test_fit_plans import endpoint, fit_payload, listen
from test_synthesis_domain import synthesis_project  # noqa: F401
from test_synthesis_operations import install_clone, queue
from test_translation_operations import drain

from videotranslate.dubbing import fit_plans
from videotranslate.execution.inputs import fingerprint
from videotranslate.models.core import Project
from videotranslate.models.dubbing import Segment, SegmentRevision, TranscriptRevision
from videotranslate.models.execution import ProjectEvent
from videotranslate.models.finishing import FitPlanCommand, FitPlanLine


def admission_phases(monkeypatch):
    command, capture = fit_plans.command, fit_plans.capture_row
    phases = []

    def marked(db, *args, **kwargs):
        db.info["observed_fit_phase"] = "admission"
        result = command(db, *args, **kwargs)
        # Retain identities deliberately: expire_on_commit=False must not hide a
        # concurrent source revision behind a previously loaded Segment object.
        db.info["retained_fit_segments"] = db.scalars(select(Segment)).all()
        return result

    def observed(db, *args, **kwargs):
        phases.append(db.info.get("observed_fit_phase"))
        return capture(db, *args, **kwargs)

    def committed(db):
        if "observed_fit_phase" in db.info:
            db.info["observed_fit_phase"] = "committed"

    monkeypatch.setattr(fit_plans, "command", marked)
    monkeypatch.setattr(fit_plans, "capture_row", observed)
    event.listen(Session, "after_commit", committed)
    return phases, committed


@pytest.mark.parametrize("existing", ["new", "pending", "published"])
def test_each_cell_is_captured_only_once_under_admission_lock(
    synthesis_project, monkeypatch, existing
):
    f = synthesis_project
    c, h, *_ = f
    payload = fit_payload(f, "incomplete_preview")
    if existing != "new":
        assert c.post(endpoint(f), headers=h, json=payload).status_code == 202
        if existing == "published":
            drain(c)
    phases, committed = admission_phases(monkeypatch)
    try:
        response = c.post(endpoint(f), headers=h, json=payload)
    finally:
        event.remove(Session, "after_commit", committed)
    assert response.status_code == 202, response.text
    assert response.json()["reused"] == (existing != "new")
    assert phases == ["admission", "committed"]


@pytest.mark.parametrize("edit", ["settings", "source", "review"])
def test_duplicate_published_response_reloads_current_proofs_after_commit(
    synthesis_project, monkeypatch, tmp_path, edit
):
    f = synthesis_project
    c, h, p, s, line, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    listen(f)
    payload = fit_payload(f)
    first = c.post(endpoint(f), headers=h, json=payload).json()
    drain(c)
    assert c.get(endpoint(f) + "/" + first["id"]).json()["render_eligible"]
    phases, committed = admission_phases(monkeypatch)
    detail = fit_plans.detail
    edited = False

    def after_commit(db, *args, **kwargs):
        nonlocal edited
        assert db.info.get("observed_fit_phase") == "committed"
        assert all(inspect(row).expired for row in db.info["retained_fit_segments"])
        if not edited:
            edited = True
            base = f"/api/projects/{p['id']}"
            if edit == "settings":
                result = c.put(
                    base + "/fit-settings", headers=h, json={"revision": 0, "settings": {}}
                )
                assert result.status_code == 200, result.text
            elif edit == "source":
                result = c.patch(
                    base + f"/segments/{line['id']}",
                    headers=h,
                    json=guard(s, line["transcript_revision"])
                    | dict(revision=line["revision"], end_ms=900),
                )
                assert result.status_code == 200, result.text
            else:
                listen(f)
        return detail(db, *args, **kwargs)

    monkeypatch.setattr(fit_plans, "detail", after_commit)
    try:
        response = c.post(endpoint(f), headers=h, json=payload)
    finally:
        event.remove(Session, "after_commit", committed)
    assert response.status_code == 202, response.text
    state = response.json()
    assert edited and state["id"] == first["id"] and state["reused"]
    assert state["plan"] and state["timeline_feasible"]
    assert not state["current"] and state["stale"] and not state["render_eligible"]
    with c.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FitPlanCommand)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProjectEvent)
                .where(ProjectEvent.kind.in_(["finishing.plan_queued", "finishing.plan_published"]))
            )
            == 2
        )


def test_supported_thousand_cell_capture_allows_competing_settings_write(
    dubbing_project, monkeypatch
):
    from videotranslate.dubbing.segments import insert_segment

    c, h, p = dubbing_project
    s = selected(dubbing_project)
    first = create_line(dubbing_project, s, text="Line", start_ms=0, end_ms=1)["segment"]
    base = f"/api/projects/{p['id']}"
    track = make_track(c, h, base, "ja")

    def proof(segment_id, revision_id):
        return dict(
            id=segment_id,
            expected_source_revision_id=revision_id,
            expected_source_text_fingerprint=fingerprint("Line"),
            translation_revision=0,
            selection_revision=0,
            output_id=None,
            review_revision=0,
            qc_evidence_fingerprint=None,
        )

    rows = [proof(first["id"], first["revision_id"])]
    with c.app.state.session_factory.begin() as db:
        project = db.get(Project, p["id"])
        transcript = db.get(TranscriptRevision, first["transcript_revision"])
        actor = db.get(SegmentRevision, first["revision_id"]).actor_id
        facets = {}
        for index in range(1, 1000):
            segment = insert_segment(
                db,
                project,
                transcript,
                dict(text="Line", start_ms=index, end_ms=index + 1, speaker_id=None),
                actor,
                input_facets=facets,
                original_index=index,
            )
            rows.append(proof(segment.id, segment.current_revision_id))
    payload = guard(s, first["transcript_revision"]) | dict(
        settings_revision=0,
        purpose="incomplete_preview",
        tracks=[dict(tag=track["tag"], segments=rows)],
    )
    entered = threading.Event()
    capture = fit_plans.capture_row
    errors = []

    def observed(*args, **kwargs):
        entered.set()
        return capture(*args, **kwargs)

    def database_error(context):
        errors.append(type(context.original_exception).__name__)

    monkeypatch.setattr(fit_plans, "capture_row", observed)
    event.listen(c.app.state.engine, "handle_error", database_error)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            start = time.monotonic()
            pending = pool.submit(c.post, endpoint(dubbing_project), headers=h, json=payload)
            assert entered.wait(20)
            competing = c.put(
                base + "/fit-settings", headers=h, json={"revision": 0, "settings": {}}
            )
            admitted = pending.result(timeout=120)
        print(f"1000-cell admission+detail and concurrent write: {time.monotonic() - start:.3f}s")
    finally:
        event.remove(c.app.state.engine, "handle_error", database_error)
    assert admitted.status_code == 202, admitted.text
    assert competing.status_code == 200, competing.text
    assert not errors
    with c.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(FitPlanCommand)) == 1
        assert db.scalar(select(func.count()).select_from(FitPlanLine)) == 1000

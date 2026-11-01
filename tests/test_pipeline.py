"""Full coordinator uses durable local jobs and the existing guarded domains."""

# ruff: noqa: F811
from sqlalchemy import select
from test_translation_operations import (  # noqa: F401
    drain,
    install_chat,
    translation_project,
    view,
)

from videotranslate.execution.worker import Worker
from videotranslate.models.execution import StageRun


def endpoint(f):
    return f"/api/projects/{f[2]['id']}/pipeline"


def start(f, **overrides):
    c, h, p, _, _, track = f[:6]
    timeline = c.get(f"/api/projects/{p['id']}/timeline").json()
    response = c.post(
        endpoint(f),
        headers=h,
        json=dict(
            expected_editor_fingerprint=timeline["editor_fingerprint"],
            source_mode="use_current",
            target_track_ids=[track["id"]],
            delivery_track_ids=[track["id"]],
        )
        | overrides,
    )
    assert response.status_code == 202, response.text
    return response.json()


def proceed(f, detail, kind="source", **extra):
    c, h, *_ = f
    response = c.post(
        endpoint(f) + "/" + detail["id"] + "/continue",
        headers=h,
        json=dict(
            revision=detail["revision"],
            kind=kind,
            guard=detail["source_guard"] if kind == "source" else detail["targets"][0]["guard"],
            track_id=None if kind == "source" else detail["targets"][0]["track_id"],
            **extra,
        ),
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_start_pauses_owned_current_source_and_is_discoverable_and_idempotent(translation_project):
    f = translation_project
    c, h, p, *_ = f
    first = start(f)
    second = start(f)
    assert second["id"] == first["id"]
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["id"] == first["id"]
    assert detail["status"] == "review" and detail["next_action"] == "source_and_cast_review"
    assert c.get(endpoint(f)).json()["total"] == 1
    with c.app.state.session_factory() as db:
        stages = db.scalars(select(StageRun.stage)).all()
    assert "transcribe" not in stages and "translation_draft" not in stages
    assert stages.count("workflow_continue") == 1
    assert c.get(endpoint(f) + "/" + first["id"]).json() == detail


def test_source_continue_survives_worker_restart_and_translation_pauses_without_approval(
    translation_project,
    monkeypatch,
):
    f = translation_project
    c, h, p, *_ = f
    chat = install_chat(monkeypatch)
    detail = start(f)
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    proceed(f, detail)
    # A new worker instance finds the persisted dirty marker, no browser loop.
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["targets"][0]["next_action"] == "translation_review", detail
    assert [phase for phase, _ in chat.calls] == ["draft"]
    assert not view(c, p, f[4])["approved"]
    proceed(f, detail, "translation")
    drain(c)
    assert len(chat.calls) == 1
    assert c.get(endpoint(f) + "/current").json()["targets"][0]["issue"] == "REFERENCE_REQUIRED"


def test_stale_checkpoint_rejected_and_target_edit_does_not_reapprove_source(
    translation_project,
    monkeypatch,
):
    f = translation_project
    c, h, p, s, line, *_ = f
    install_chat(monkeypatch)
    start(f)
    drain(c)
    old = c.get(endpoint(f) + "/current").json()
    result = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json=dict(
            selection_revision=s["revision"],
            transcript_revision=line["transcript_revision"],
            revision=line["revision"],
            text="Changed source",
        ),
    )
    assert result.status_code == 200, result.text
    response = c.post(
        endpoint(f) + "/" + old["id"] + "/continue",
        headers=h,
        json=dict(revision=old["revision"], kind="source", guard=old["source_guard"]),
    )
    assert response.status_code == 409
    drain(c)
    new = c.get(endpoint(f) + "/current").json()
    assert new["source_guard"] != old["source_guard"]
    assert new["next_action"] == "source_and_cast_review"


def test_cancel_blocks_future_cinematic_phases_and_resume_never_resubmits_unknown(
    translation_project,
    monkeypatch,
):
    from videotranslate.models.translation import TranslationPhase

    f = translation_project
    c, h, p, _, _, track = f
    changed = c.patch(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant",
        headers=h,
        json={"revision": track["revision"], "mode": "Cinematic"},
    )
    assert changed.status_code == 200
    chat = install_chat(monkeypatch)
    start(f)
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    proceed(f, detail)
    # One control job admits context; cancel before provider execution.
    assert Worker(c.app.state.settings).run_once()
    detail = c.get(endpoint(f) + "/current").json()
    response = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert response.status_code == 202, response.text
    drain(c)
    assert chat.calls == []
    with c.app.state.session_factory() as db:
        phases = db.scalars(select(TranslationPhase)).all()
        assert len(phases) == 1
        run = db.get(StageRun, phases[0].run_id)
        assert run.status == "cancelled"
    result = c.get(endpoint(f) + "/current").json()
    assert result["status"] == "cancelled"


def test_auto_policy_uses_separate_authorization_never_human_target_or_audio_acceptance(
    synthesis_project,
    monkeypatch,
    tmp_path,
):
    from test_synthesis_operations import install_clone

    from videotranslate.models.analysis import ReferenceVersion
    from videotranslate.models.dubbing import TranslationRevision
    from videotranslate.models.pipeline import PipelineCheckpoint
    from videotranslate.models.synthesis import SynthesisLine
    from videotranslate.models.voice_qc import AudioReview

    f = synthesis_project
    c, h, p, s, line, *_ = f
    # Test-only provider publication provenance; no real inference is represented.
    with c.app.state.session_factory.begin() as db:
        revision = db.scalar(select(TranslationRevision))
        revision.approved, revision.provenance = False, "cloud_draft"
        db.scalar(select(ReferenceVersion)).flags = ["short"]
    install_clone(monkeypatch, tmp_path)
    start(f, auto_advance=True)
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    # Manual source remains a real gate even with automatic target policy.
    assert detail["next_action"] == "source_and_cast_review"
    proceed(f, detail)
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    # This short reference requires explicit warning acknowledgement; auto mode stops.
    assert detail["targets"][0]["issue"] == "REFERENCE_REVIEW_REQUIRED", detail
    with c.app.state.session_factory() as db:
        assert not db.scalar(select(TranslationRevision)).approved
        assert not db.scalars(select(AudioReview)).all()
        records = db.scalars(select(PipelineCheckpoint)).all()
        assert {r.provenance for r in records} == {"human", "automatic_policy"}
        assert not db.scalars(select(SynthesisLine)).all()


def test_full_workflow_reuses_listened_audio_and_finishes_shared_map_without_browser(
    synthesis_project,
    monkeypatch,
    tmp_path,
):
    from test_deliveries import prepare_test_media
    from test_fit_plans import listen
    from test_synthesis_operations import install_clone, queue

    from videotranslate.models.finishing import FitPlanCommand

    f = synthesis_project
    c, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    prepare_test_media(f, monkeypatch)
    listen(f)
    start(f)
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    proceed(f, detail)
    drain(c, limit=40)
    result = c.get(endpoint(f) + "/current").json()
    assert result["status"] == "completed", result
    assert result["finish"]["purpose"] == "dub"
    assert result["finish"]["artifact_ids"]
    with c.app.state.session_factory() as db:
        assert len(db.scalars(select(FitPlanCommand)).all()) == 1
        controls = db.scalars(select(StageRun).where(StageRun.stage == "workflow_continue")).all()
        assert all(r.status == "succeeded" for r in controls)
        assert all(set(r.result) == {"workflow_id"} for r in controls)
    assert Worker(c.app.state.settings).run_once() is False


from test_synthesis_domain import synthesis_project  # noqa: E402,F401


def test_unknown_translation_resume_keeps_original_phase_and_never_reposts(
    translation_project, monkeypatch
):
    from videotranslate.models.translation import TranslationPhase

    f = translation_project
    c, h, *_ = f
    chat = install_chat(monkeypatch)
    chat.fail = "draft"
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["targets"][0]["issue"] == "SUBMISSION_UNCERTAIN"
    with c.app.state.session_factory() as db:
        phase = db.scalar(select(TranslationPhase))
        original_id = phase.run_id
    stopped = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert stopped.status_code == 202
    resumed = c.post(
        endpoint(f) + "/" + detail["id"] + "/resume",
        headers=h,
        json={"revision": stopped.json()["revision"]},
    )
    assert resumed.status_code == 202
    drain(c)
    assert len(chat.calls) == 1
    with c.app.state.session_factory() as db:
        assert [r.run_id for r in db.scalars(select(TranslationPhase))] == [original_id]
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["targets"][0]["next_action"] == "acknowledge_uncertain_submission"


def test_full_cancel_leaves_independently_consumed_translation_alive(
    translation_project, monkeypatch
):
    from test_translation_operations import request_body

    from videotranslate.models.translation import TranslationCommand, TranslationPhase

    f = translation_project
    c, h, p, s, line, track = f
    chat = install_chat(monkeypatch)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    assert Worker(c.app.state.settings).run_once()
    # An explicit standalone consumer adopts this exact queued command.
    manual = c.post(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate",
        headers=h,
        json=request_body(s, line, track),
    )
    assert manual.status_code == 202, manual.text
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["commands"][0]["exclusively_owned"] is False
    cancelled = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert cancelled.status_code == 202
    drain(c)
    assert len(chat.calls) == 1
    with c.app.state.session_factory() as db:
        assert not db.scalar(select(TranslationCommand)).continuation_stopped
        assert db.get(StageRun, db.scalar(select(TranslationPhase)).run_id).status == "succeeded"


def test_explicit_resume_allows_original_cancelled_phase_retry_then_descendants(
    translation_project, monkeypatch
):
    from videotranslate.models.translation import TranslationPhase

    f = translation_project
    c, h, p, _, _, track = f
    changed = c.patch(
        f"/api/projects/{p['id']}/language-tracks/zh-Hant",
        headers=h,
        json={"revision": track["revision"], "mode": "Cinematic"},
    )
    assert changed.status_code == 200
    chat = install_chat(monkeypatch)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    assert Worker(c.app.state.settings).run_once()
    detail = c.get(endpoint(f) + "/current").json()
    stopped = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    ).json()
    resumed = c.post(
        endpoint(f) + "/" + detail["id"] + "/resume",
        headers=h,
        json={"revision": stopped["revision"]},
    )
    assert resumed.status_code == 202
    drain(c)
    assert chat.calls == []
    with c.app.state.session_factory() as db:
        original = db.scalar(select(TranslationPhase)).run_id
    retry = c.post(f"/api/runs/{original}/retry", headers=h, json={})
    assert retry.status_code == 200, retry.text
    drain(c)
    assert [phase for phase, _ in chat.calls] == ["context", "draft", "critique", "rewrite"]


def test_stopped_source_intent_cannot_reopen_internal_chain_on_individual_retry(dubbing_project):
    from dubbing_helpers import make_track, selected

    from videotranslate.models.analysis import WorkflowChild, WorkflowIntent

    c, h, project = dubbing_project
    selection = selected(dubbing_project)
    track = make_track(c, h, f"/api/projects/{project['id']}", "zh-Hant")
    f = (c, h, project, selection, None, track)
    start(f, source_mode="automatic")
    assert Worker(c.app.state.settings).run_once()
    detail = c.get(endpoint(f) + "/current").json()
    result = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert result.status_code == 202, result.text
    with c.app.state.session_factory() as db:
        original = db.scalar(select(WorkflowChild)).run_id
    retry = c.post(f"/api/runs/{original}/retry", headers=h, json={})
    assert retry.status_code == 200, retry.text
    drain(c)
    with c.app.state.session_factory() as db:
        source = db.scalar(select(WorkflowIntent))
        assert source.status == "cancelled"
        assert db.scalars(select(StageRun).where(StageRun.stage == "separate")).all() == []


def test_auto_source_never_accepts_current_analysis_flags(translation_project, monkeypatch):
    from videotranslate.models.dubbing import Segment, TranscriptRevision

    f = translation_project
    c, h, p, s, line, *_ = f
    role = c.post(f"/api/projects/{p['id']}/speakers", headers=h, json={"name": "Role"}).json()
    edited = c.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=h,
        json={
            "selection_revision": s["revision"],
            "transcript_revision": line["transcript_revision"],
            "revision": line["revision"],
            "speaker_id": role["id"],
        },
    )
    assert edited.status_code == 200
    with c.app.state.session_factory.begin() as db:
        transcript = db.scalar(select(TranscriptRevision))
        transcript.provenance = "provider"
        transcript.run_id = db.scalar(select(StageRun).where(StageRun.stage == "probe")).id
        db.scalar(select(Segment)).source_analysis_flags = ["timing_clipped"]
    start(f, auto_advance=True)
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["next_action"] == "source_and_cast_review", detail


def test_current_import_is_not_retranscribed_even_with_automatic_source_mode(dubbing_project):
    from dubbing_helpers import guard, make_track, selected

    c, h, project = dubbing_project
    selection = selected(dubbing_project)
    base = f"/api/projects/{project['id']}"
    body = guard(selection) | {
        "format": "srt",
        "content": "1\n00:00:00,000 --> 00:00:00,500\nImported words",
    }
    preview = c.post(base + "/source/import/preview", headers=h, json=body).json()
    applied = c.post(
        base + "/source/import/apply",
        headers=h,
        json=body
        | {
            "digest": preview["digest"],
            "mode": "new_transcript",
            "mapping": [{"cue_id": preview["cues"][0]["id"], "speaker_id": None}],
        },
    )
    assert applied.status_code == 201
    before = c.get(base + "/timeline").json()
    track = make_track(c, h, base, "zh-Hant")
    f = (c, h, project, selection, None, track)
    start(f, source_mode="automatic")
    drain(c)
    after = c.get(base + "/timeline").json()
    assert before["transcript"] == after["transcript"]
    assert after["transcript"]["provenance"] == "import"
    assert after["segments"][0]["text"] == "Imported words"
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(StageRun).where(StageRun.stage == "transcribe")).all()


def test_current_source_can_prepare_missing_media_without_running_asr(
    synthesis_project, monkeypatch, tmp_path
):
    from test_analysis_workflow import configure_remote, recording_provider
    from test_fit_plans import listen
    from test_synthesis_operations import install_clone, queue

    f = synthesis_project
    c, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    listen(f)
    configure_remote(f[:3])
    recording_provider(monkeypatch, c)
    before = c.get(f"/api/projects/{f[2]['id']}/timeline").json()["transcript"]
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    drain(c, limit=50)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["status"] == "completed", detail
    after = c.get(f"/api/projects/{f[2]['id']}/timeline").json()["transcript"]
    assert before == after
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(StageRun).where(StageRun.stage == "transcribe")).all()
        assert len(db.scalars(select(StageRun).where(StageRun.stage == "separate")).all()) == 1


def test_manual_source_run_consumer_is_not_cancelled_with_its_pipeline(dubbing_project):
    from dubbing_helpers import make_track, selected

    c, h, project = dubbing_project
    selection = selected(dubbing_project)
    track = make_track(c, h, f"/api/projects/{project['id']}", "zh-Hant")
    f = (c, h, project, selection, None, track)
    start(f, source_mode="automatic")
    assert Worker(c.app.state.settings).run_once()
    manual = c.post(f"/api/projects/{project['id']}/runs", headers=h, json={"stage": "extract"})
    assert manual.status_code == 201
    detail = c.get(endpoint(f) + "/current").json()
    cancelled = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert cancelled.status_code == 202
    drain(c)
    assert c.get("/api/runs/" + manual.json()["id"]).json()["status"] == "succeeded"


def test_control_crash_rolls_back_atomic_command_and_link_then_explicit_retry_reuses_once(
    translation_project,
    monkeypatch,
):
    from dataclasses import replace

    from videotranslate.execution.registry import STAGES
    from videotranslate.models.pipeline import PipelineCommand
    from videotranslate.models.translation import TranslationCommand

    f = translation_project
    c, h, *_ = f
    chat = install_chat(monkeypatch)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    original = STAGES["workflow_continue"]

    def crash_after_admission(db, run, result):
        original.publish(db, run, result)
        raise RuntimeError("test-only publication crash")

    monkeypatch.setitem(
        STAGES, "workflow_continue", replace(original, publish=crash_after_admission)
    )
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory() as db:
        assert not db.scalars(select(TranslationCommand)).all()
        assert not db.scalars(select(PipelineCommand)).all()
        control = db.scalar(
            select(StageRun).where(
                StageRun.stage == "workflow_continue", StageRun.status == "failed"
            )
        )
        run_id = control.id
    assert chat.calls == []
    monkeypatch.setitem(STAGES, "workflow_continue", original)
    retried = c.post("/api/runs/" + run_id + "/retry", headers=h, json={})
    assert retried.status_code == 200, retried.text
    drain(c)
    assert len(chat.calls) == 1
    with c.app.state.session_factory() as db:
        assert len(db.scalars(select(TranslationCommand)).all()) == 1
        assert len(db.scalars(select(PipelineCommand)).all()) == 1


def test_delivery_preparation_is_outside_sql_and_policy_race_admits_nothing(
    synthesis_project,
    monkeypatch,
    tmp_path,
):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from test_deliveries import prepare_test_media
    from test_fit_plans import listen
    from test_synthesis_operations import install_clone, queue

    from videotranslate.dubbing import deliveries, fit_snapshot
    from videotranslate.models.delivery import DeliveryCommand

    f = synthesis_project
    c, h, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    prepare_test_media(f, monkeypatch)
    listen(f)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    live, validated = set(), []

    def opened(session, transaction, connection):
        live.add(id(session))

    def closed(session, transaction):
        if transaction.parent is None:
            live.discard(id(session))

    event.listen(Session, "after_begin", opened)
    event.listen(Session, "after_transaction_end", closed)
    original_validation = fit_snapshot.validate_plan

    def validate(*args, **kwargs):
        assert not live, "Strict fit validation holds a SQL transaction"
        validated.append(True)
        return original_validation(*args, **kwargs)

    monkeypatch.setattr(fit_snapshot, "validate_plan", validate)
    original_prepare = deliveries.valid_parent
    raced = []

    def prepare(db, project, parent):
        candidate = original_prepare(db, project, parent)
        assert not db.in_transaction()
        detail = c.get(endpoint(f) + "/current").json()
        result = c.post(
            endpoint(f) + "/" + detail["id"] + "/policy",
            headers=h,
            json={"revision": detail["revision"], "auto_advance": True},
        )
        assert result.status_code == 202
        raced.append(True)
        return candidate

    monkeypatch.setattr(deliveries, "valid_parent", prepare)
    try:
        worker = Worker(c.app.state.settings)
        for _ in range(15):
            worker.run_once()
            if raced:
                break
        assert raced and validated
        with c.app.state.session_factory() as db:
            assert not db.scalars(select(DeliveryCommand)).all()
        detail = c.get(endpoint(f) + "/current").json()
        assert detail["dirty"]
        monkeypatch.setattr(deliveries, "valid_parent", original_prepare)
        drain(c, limit=30)
        assert c.get(endpoint(f) + "/current").json()["status"] == "completed"
        with c.app.state.session_factory() as db:
            assert len(db.scalars(select(DeliveryCommand)).all()) == 1
    finally:
        event.remove(Session, "after_begin", opened)
        event.remove(Session, "after_transaction_end", closed)


def test_changed_provider_repairs_failed_admission_without_retrying_original_paid_input(
    translation_project, monkeypatch
):
    from videotranslate.models.translation import TranslationPhase

    f = translation_project
    c, h, *_ = f
    chat = install_chat(monkeypatch)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    assert Worker(c.app.state.settings).run_once()
    with c.app.state.session_factory.begin() as db:
        phase = db.scalar(select(TranslationPhase))
        run = db.get(StageRun, phase.run_id)
        run.status = "failed"
        run.safe_error = {"code": "CONFIGURATION", "retryable": False}
    changed = c.put(
        "/api/providers/translation",
        headers=h,
        json={
            "revision": 1,
            "adapter": "openai_compatible",
            "endpoint": "https://translator.example/v1",
            "model": "replacement-test-model",
            "credential_ref": None,
        },
    )
    assert changed.status_code == 200, changed.text
    drain(c)
    assert len(chat.calls) == 1
    with c.app.state.session_factory() as db:
        assert len(db.scalars(select(TranslationPhase)).all()) == 2


def test_policy_authorization_synthesizes_without_forging_translation_or_listening_acceptance(
    synthesis_project,
    monkeypatch,
    tmp_path,
):
    from test_synthesis_operations import install_clone

    from videotranslate.models.dubbing import TranslationRevision
    from videotranslate.models.synthesis import SynthesisLine
    from videotranslate.models.voice_qc import AudioReview

    f = synthesis_project
    c, *_ = f
    with c.app.state.session_factory.begin() as db:
        target = db.scalar(select(TranslationRevision))
        target.approved, target.provenance = False, "cloud_draft"
    http = install_clone(monkeypatch, tmp_path)
    start(f, auto_advance=True)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["targets"][0]["next_action"] == "listening_review", detail
    assert len(http.posts) == 1
    with c.app.state.session_factory() as db:
        line = db.scalar(select(SynthesisLine))
        assert line.authorization_checkpoint_id and line.review_translation_revision is None
        assert not db.scalar(select(TranslationRevision)).approved
        assert not db.scalars(select(AudioReview)).all()


def test_supported_independent_qc_is_admitted_then_waits_for_real_listening(
    synthesis_project,
    monkeypatch,
    tmp_path,
):
    from test_voice_qc_operations import prepared

    from videotranslate.models.voice_qc import AudioReview, VoiceQCCommand

    f = synthesis_project
    c, *_ = f
    http = prepared(f, monkeypatch, tmp_path)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["targets"][0]["next_action"] == "listening_review", detail
    assert len(http.posts) == 1
    with c.app.state.session_factory() as db:
        assert len(db.scalars(select(VoiceQCCommand)).all()) == 1
        assert not db.scalars(select(AudioReview)).all()


def test_target_jobs_remain_independent_and_do_not_retranslate_current_other_target(
    translation_project, monkeypatch
):
    from dubbing_helpers import make_track
    from test_translation_operations import target_edit

    f = translation_project
    c, h, p, s, line, track = f
    chat = install_chat(monkeypatch)
    ja = make_track(c, h, f"/api/projects/{p['id']}", "ja")
    start(f, target_track_ids=[track["id"], ja["id"]], delivery_track_ids=[track["id"], ja["id"]])
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    drain(c)
    detail = c.get(endpoint(f) + "/current").json()
    assert len(chat.calls) == 2
    assert all(t["next_action"] == "translation_review" for t in detail["targets"])
    before_source = detail["source_guard"]
    changed = target_edit(c, h, p, s, line, revision=1, text="Human correction")
    assert changed.status_code == 200
    drain(c)
    later = c.get(endpoint(f) + "/current").json()
    assert later["source_guard"] == before_source
    assert len(chat.calls) == 2
    ja_before = next(t for t in detail["targets"] if t["track_id"] == ja["id"])
    ja_after = next(t for t in later["targets"] if t["track_id"] == ja["id"])
    assert ja_before["guard"] == ja_after["guard"]
    assert ja_after["next_action"] == "translation_review"


def test_guarded_manual_fit_consumer_survives_pipeline_cancellation(
    synthesis_project, monkeypatch, tmp_path
):
    from test_deliveries import prepare_test_media
    from test_fit_plans import fit_payload, listen
    from test_synthesis_operations import install_clone, queue

    f = synthesis_project
    c, h, p, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    prepare_test_media(f, monkeypatch)
    listen(f)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    assert Worker(c.app.state.settings).run_once()
    detail = c.get(endpoint(f) + "/current").json()
    assert detail["finish"]["fit_id"]
    manual = c.post(f"/api/projects/{p['id']}/fit-plans", headers=h, json=fit_payload(f))
    assert manual.status_code == 202 and manual.json()["reused"]
    cancelled = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert cancelled.status_code == 202
    drain(c)
    assert c.get("/api/runs/" + manual.json()["run_id"]).json()["status"] == "succeeded"


def test_guarded_manual_delivery_consumer_survives_pipeline_cancellation(
    synthesis_project, monkeypatch, tmp_path
):
    from test_deliveries import body, prepare_test_media
    from test_fit_plans import listen
    from test_synthesis_operations import install_clone, queue

    f = synthesis_project
    c, h, p, *_ = f
    base = f"/api/projects/{p['id']}"
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    prepare_test_media(f, monkeypatch)
    listen(f)
    start(f)
    drain(c)
    proceed(f, c.get(endpoint(f) + "/current").json())
    worker = Worker(c.app.state.settings)
    for _ in range(10):
        worker.run_once()
        detail = c.get(endpoint(f) + "/current").json()
        if detail["finish"].get("delivery_id"):
            break
    assert detail["finish"].get("delivery_id"), detail
    plan = c.get(base + "/fit-plans/" + detail["finish"]["fit_id"]).json()
    request = body(plan) | {"default_audio_track": "zh-Hant"}
    manual = c.post(base + "/deliveries", headers=h, json=request)
    assert manual.status_code == 202, manual.text
    assert manual.json()["id"] == detail["finish"]["delivery_id"]
    cancelled = c.post(
        endpoint(f) + "/" + detail["id"] + "/cancel",
        headers=h,
        json={"revision": detail["revision"]},
    )
    assert cancelled.status_code == 202
    drain(c)
    assert c.get("/api/runs/" + manual.json()["run_id"]).json()["status"] == "succeeded"

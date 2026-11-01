"""Bounded local continuation on the existing StageRun worker.

Only the handler prepares heavy delivery proofs (outside SQL); its publisher
admits existing guarded commands under the project lock, never remote requests.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import or_, select

from ..errors import APIError
from ..execution.contracts import RunCreate, StageResult
from ..execution.inputs import fingerprint, is_current, lock_project
from ..models.analysis import WorkflowIntent
from ..models.core import Project
from ..models.delivery import DeliveryCommand
from ..models.dubbing import LanguageTrack, SegmentRevision, TranscriptRevision, TranslationRevision
from ..models.execution import StageRun
from ..models.finishing import FitPlanCommand
from ..models.pipeline import PipelineCommand, PipelineWorkflow
from ..models.synthesis import AudioSelectionVersion, NaturalOutput
from . import pipeline as p
from .editor import editor_fingerprint
from .ownership import owned, scope
from .pipeline_contracts import ControlOptions
from .source import current_selection, source_state
from .translations import translation_state


def options(value):
    return ControlOptions.model_validate(value).model_dump()


def command_scope(request):
    return request.options["workflow_id"]


def inputs(db, project, request):
    owned(db, PipelineWorkflow, project, request.options["workflow_id"])
    return {}


def schedule_dirty(db, limit=2):
    """Bounded persistent wake pump; no callbacks and no second scheduler."""
    from ..execution.service import create_run

    ids = db.scalars(
        select(PipelineWorkflow.id)
        .join(Project, Project.id == PipelineWorkflow.project_id)
        .outerjoin(StageRun, StageRun.id == PipelineWorkflow.control_run_id)
        .where(
            Project.deleted_at.is_(None),
            or_(
                PipelineWorkflow.stop_requested.is_(False), PipelineWorkflow.status == "cancelling"
            ),
            or_(StageRun.id.is_(None), ~StageRun.status.in_([*p.ACTIVE, "failed", "needs_review"])),
            PipelineWorkflow.wake_revision > PipelineWorkflow.reconciled_revision,
        )
        .order_by(PipelineWorkflow.created_at, PipelineWorkflow.id)
        .limit(limit)
    ).all()
    for wid in ids:
        workflow = db.get(PipelineWorkflow, wid)
        project = lock_project(db, db.get(Project, workflow.project_id))
        db.refresh(workflow)
        if (
            workflow.stop_requested and workflow.status != "cancelling"
        ) or workflow.wake_revision <= workflow.reconciled_revision:
            continue
        active = db.get(StageRun, workflow.control_run_id) if workflow.control_run_id else None
        if active and active.status in p.ACTIVE:
            continue
        # Failed control jobs retain explicit retry semantics, like all StageRuns.
        if active and active.status in {"failed", "needs_review"}:
            continue
        run = create_run(
            db,
            project.workspace_id,
            project.id,
            RunCreate(
                stage="workflow_continue",
                options=dict(
                    workflow_id=workflow.id,
                    generation=workflow.generation,
                    wake_revision=workflow.wake_revision,
                ),
            ),
            guarded_command=True,
            idempotency_key=f"pipeline:{workflow.id}:{workflow.generation}:{workflow.wake_revision}",
        )
        workflow.control_run_id = run.id


@dataclass(frozen=True)
class ControlResult(StageResult):
    binding: dict | None = None
    validated_delivery: dict | None = None
    delivery_detail: dict | None = None
    prepare_error: str | None = None
    runtime: object = None


def handler(context):
    """Capture/validate finish proofs without holding the coordinator write lock."""
    from . import deliveries

    with context.session_factory() as db:
        run = db.get(StageRun, context.run_id)
        project = db.get(Project, run.project_id)
        workflow = owned(db, PipelineWorkflow, project, run.options["workflow_id"])
        binding = dict(
            generation=workflow.generation,
            revision=workflow.revision,
            scope_revision=workflow.scope_revision,
            policy_revision=workflow.policy_revision,
            wake_revision=workflow.wake_revision,
        )
        finish = dict(workflow.finish_state)
        candidate, detail, error = None, None, None
        if not workflow.stop_requested and finish.get("fit_id"):
            fit = owned(db, FitPlanCommand, project, finish["fit_id"])
            fit_run = owned(db, StageRun, project, fit.run_id)
            if fit_run.status == "succeeded" and not fit_run.is_stale:
                try:
                    # valid_parent closes its read before the strict CPU map/checkpoint validation.
                    candidate = deliveries.valid_parent(db, project, fit)
                    if finish.get("delivery_id"):
                        delivery = owned(db, DeliveryCommand, project, finish["delivery_id"])
                        detail = deliveries.detail(db, project, delivery)
                    db.commit()
                except (APIError, ValueError, KeyError, TypeError, AttributeError):
                    error = "DELIVERY_INPUT_CHANGED"
        return ControlResult(
            {"workflow_id": workflow.id},
            binding=binding,
            validated_delivery=candidate,
            delivery_detail=detail,
            prepare_error=error,
            runtime=context.settings,
        )


def command_link(db, project, workflow, scope_key, kind, dispatch, admit):
    """Domain admission and typed association commit together; signatures remain authoritative."""
    existing = db.scalar(
        scope(PipelineCommand, project).where(
            PipelineCommand.workflow_id == workflow.id, PipelineCommand.dispatch_key == dispatch
        )
    )
    if existing:
        return existing
    with db.begin_nested():
        result = admit()
        command_id = result["id"] if isinstance(result, dict) else result.id
        if command_id is None:
            return None
        reused = result.get("reused", False) if isinstance(result, dict) else result.reused
        return p.attach(db, project, workflow, scope_key, kind, command_id, dispatch, not reused)


def blocked_runs(db, project, link):
    """Original phase jobs are the only retry target; uncertainty never authorizes a new call."""
    runs = p.command_runs(db, project, link)
    if any(r.remote_state == "submitting" and not r.remote_id for r in runs):
        return dict(
            status="review",
            next_action="acknowledge_uncertain_submission",
            issue="SUBMISSION_UNCERTAIN",
        )
    if any(r.status in p.ACTIVE for r in runs):
        return dict(status="running", next_action=None)
    broken = [r for r in runs if r.status in {"failed", "needs_review", "cancelled", "stale"}]
    if broken:
        return dict(
            status="review",
            next_action="review_run",
            issue=(broken[0].safe_error or {}).get("code", broken[0].status.upper()),
        )
    return None


def provider_revision(db, project, slot):
    from .workflow import connection

    config = connection(db, project, slot)
    return config.revision if config else None


def source_branch(db, project, workflow, rows):
    state = source_state(db, project)
    # Existing/imported transcript is never silently replaced by ASR.
    if not state or not state.transcript_id:
        if workflow.source_mode != "automatic":
            return dict(status="review", next_action="import_source")
        from .workflow import command

        body = SimpleNamespace(
            action="analyse",
            expected_editor_fingerprint=editor_fingerprint(db, project),
            auto_advance=False,
        )
        dispatch = fingerprint(
            dict(
                kind="source",
                selection=workflow.selection_id,
                editor=body.expected_editor_fingerprint,
                providers={
                    slot: provider_revision(db, project, slot)
                    for slot in ("separation", "transcription")
                },
            )
        )
        link = command_link(
            db,
            project,
            workflow,
            "source",
            "source",
            dispatch,
            lambda: command(db, project, body, workflow.actor_id, pipeline_call=True),
        )
        issue = blocked_runs(db, project, link)
        if issue:
            return issue
        intent = owned(db, WorkflowIntent, project, link.source_id)
        return dict(status=intent.status, next_action=intent.next_action)
    if not rows:
        return dict(status="review", next_action="import_source", issue="SOURCE_ROWS_REQUIRED")
    guard = p.source_guard(db, project)
    if p.checkpoint(db, project, workflow, "source", guard):
        return None
    if p.policy_for(db, project, workflow).auto_advance:
        transcript = owned(db, TranscriptRevision, project, state.transcript_id)
        source_run = db.get(StageRun, transcript.run_id) if transcript.run_id else None
        issues = (source_run.result or {}).get("issues", []) if source_run else []
        # Automatic progression cannot accept missing/uncertain cast or imported prose.
        roles_complete = all(
            owned(db, SegmentRevision, project, r.current_revision_id).speaker_id for r in rows
        )
        if (
            transcript.provenance == "provider"
            and source_run
            and not issues
            and roles_complete
            and not any(row.source_analysis_flags for row in rows)
        ):
            p.save_checkpoint(
                db, project, workflow, "source", guard, workflow.actor_id, "automatic_policy"
            )
            return None
    return dict(status="review", next_action="source_and_cast_review")


def target_branch(db, project, workflow, track, rows, runtime):
    from . import synthesis, translation_workflow, voice_qc
    from .synthesis_contracts import Synthesize
    from .translation_contracts import TranslateCommand
    from .voice_qc_contracts import VoiceQC

    selection = current_selection(db, project)
    state = source_state(db, project)
    guard = dict(selection_revision=selection.revision, transcript_revision=state.transcript_id)
    scope_key = "target:" + track.id
    if track.archived:
        return dict(status="review", next_action="review_target", issue="TARGET_ARCHIVED")
    if not rows:
        return dict(status="review", next_action="import_source", total=0)
    # Preserve current human/imported text; translate only missing/stale unprotected rows.
    missing, current, approved, generated = [], [], 0, True
    for row in rows:
        source = owned(db, SegmentRevision, project, row.current_revision_id)
        cell = translation_state(db, project, track, row)
        target = owned(db, TranslationRevision, project, cell.current_revision_id) if cell else None
        valid = bool(
            cell
            and not cell.stale
            and target.text.strip()
            and target.source_text_fingerprint == fingerprint(source.text)
        )
        if not valid:
            if cell and (
                cell.locked or target.approved or target.provenance in {"manual", "import"}
            ):
                return dict(
                    status="review", next_action="review_translation_changes", issue="TARGET_STALE"
                )
            actual = translation_workflow.row_guard(db, project, track, row)
            missing.append(
                dict(id=row.id, expected_source_text_fingerprint=fingerprint(source.text), **actual)
            )
        else:
            current.append((row, cell, target, source))
            approved += bool(target.approved)
            generated &= target.provenance in {"cloud_draft", "cloud_rewrite"} and not cell.locked
    if missing:
        body = TranslateCommand(**guard, track_revision=track.revision, segments=missing)
        dispatch = fingerprint(
            dict(
                kind="translation",
                track=track.id,
                body=body.model_dump(),
                context=track.context_revision_id,
                provider_revision=provider_revision(db, project, "translation"),
            )
        )
        link = command_link(
            db,
            project,
            workflow,
            scope_key,
            "translation",
            dispatch,
            lambda: translation_workflow.command(
                db, project, track.tag, body, workflow.actor_id, runtime, pipeline_call=True
            ),
        )
        result = blocked_runs(db, project, link) or dict(
            status="review", next_action="translation_review"
        )
        return dict(total=len(rows), translated_rows=len(current), **result)
    # Finish every internal phase before target authorization, including uncertain shortening.
    for link in reversed(p.links(db, project, workflow)):
        if link.scope_key == scope_key and link.translation_id:
            phases = p.command_runs(db, project, link)
            relevant = [r for r in phases if is_current(db, project, r.dependency_snapshot)]
            if relevant:
                block = blocked_runs(db, project, link)
                if block:
                    return dict(total=len(rows), translated_rows=len(current), **block)
                break
    token = p.target_guard(db, project, track, rows)
    permit = p.checkpoint(db, project, workflow, scope_key, token)
    if not permit and approved != len(rows):
        if (
            p.policy_for(db, project, workflow).auto_advance
            and generated
            and track.mode != "Autofit"
        ):
            permit = p.save_checkpoint(
                db, project, workflow, scope_key, token, workflow.actor_id, "automatic_policy"
            )
        else:
            return dict(
                status="review",
                next_action="translation_review",
                total=len(rows),
                translated_rows=len(current),
            )
    synth_rows, qc_rows, assessments = [], [], []
    for row, cell, _target, source in current:
        audio = synthesis.selection_for(db, project, track, row)
        if not audio or not audio.current_version_id:
            synth_rows.append(
                dict(
                    id=row.id,
                    translation_revision=cell.revision,
                    expected_source_text_fingerprint=fingerprint(source.text),
                    selection_revision=0,
                )
            )
            continue
        selected = owned(db, AudioSelectionVersion, project, audio.current_version_id)
        output = owned(db, NaturalOutput, project, selected.output_id)
        assessment = voice_qc.output_assessment(db, project, track, row, output)
        assessments.append(assessment)
        if "NATURAL_AUDIO_STALE" in assessment["issues"]:
            return dict(
                status="review", next_action="replace_selected_audio", issue="NATURAL_AUDIO_STALE"
            )
        if assessment["qc"]["status"] in {
            "unassessed",
            "unconfigured",
            "unsupported",
            "unknown",
            "stale",
        }:
            qc_rows.append(
                dict(
                    id=row.id,
                    translation_revision=cell.revision,
                    expected_source_text_fingerprint=fingerprint(source.text),
                    selection_revision=audio.revision,
                    output_id=output.id,
                )
            )
    if synth_rows:
        body = Synthesize(**guard, segments=synth_rows)
        dispatch = fingerprint(
            dict(
                kind="synthesis",
                track=track.id,
                body=body.model_dump(),
                target_guard=token,
                inference=[
                    fingerprint(synthesis.inference_inputs(db, project, track, row)[0])
                    for row, *_ in current
                    if row.id in {r["id"] for r in synth_rows}
                ],
            )
        )
        link = command_link(
            db,
            project,
            workflow,
            scope_key,
            "synthesis",
            dispatch,
            lambda: synthesis.command(
                db,
                project,
                track.tag,
                body,
                workflow.actor_id,
                pipeline_call=True,
                authorization_checkpoint_id=permit.id if permit else None,
            ),
        )
        result = blocked_runs(db, project, link) if link else None
        return dict(
            total=len(rows),
            translated_rows=len(current),
            **(result or dict(status="review", next_action="review_audio")),
        )
    if qc_rows:
        body = VoiceQC(**guard, segments=qc_rows)
        dispatch = fingerprint(
            dict(
                kind="qc",
                track=track.id,
                body=body.model_dump(),
                provider_revision=provider_revision(db, project, "verification"),
            )
        )
        try:
            with db.begin_nested():
                link = command_link(
                    db,
                    project,
                    workflow,
                    scope_key,
                    "qc",
                    dispatch,
                    lambda: voice_qc.command(
                        db, project, track.tag, body, workflow.actor_id, pipeline_call=True
                    ),
                )
                result = blocked_runs(db, project, link)
            if result:
                return dict(total=len(rows), **result)
        except APIError as error:
            if error.code not in {
                "PROVIDER_REQUIRED",
                "QC_LANGUAGE_UNKNOWN",
                "QC_LANGUAGE_UNSUPPORTED",
            }:
                raise
            # Unsupported/unknown recognition can be explicitly acknowledged only by listening.
            if not all(a["ready"] for a in assessments):
                return dict(
                    status="review",
                    next_action="listening_review",
                    issue=error.code,
                    total=len(rows),
                    ready_rows=sum(a["ready"] for a in assessments),
                )
    ready = sum(a["ready"] for a in assessments)
    return dict(
        status="ready" if ready == len(rows) else "review",
        next_action=None if ready == len(rows) else "listening_review",
        total=len(rows),
        translated_rows=len(current),
        audio_rows=len(assessments),
        ready_rows=ready,
    )


def fit_body(db, project, workflow, rows):
    from . import fit_settings, synthesis, voice_qc
    from .fit_contracts import FitPlanCreate

    selection = current_selection(db, project)
    state = source_state(db, project)
    settings, _ = fit_settings.current(db, project)
    tracks = []
    for tid in workflow.delivery_track_ids:
        track = owned(db, LanguageTrack, project, tid)
        cells = []
        for row in rows:
            source = owned(db, SegmentRevision, project, row.current_revision_id)
            target = translation_state(db, project, track, row)
            audio = synthesis.selection_for(db, project, track, row)
            version = (
                owned(db, AudioSelectionVersion, project, audio.current_version_id)
                if audio and audio.current_version_id
                else None
            )
            output = owned(db, NaturalOutput, project, version.output_id) if version else None
            assessment = (
                voice_qc.output_assessment(db, project, track, row, output) if output else None
            )
            cells.append(
                dict(
                    id=row.id,
                    expected_source_revision_id=source.id,
                    expected_source_text_fingerprint=fingerprint(source.text),
                    translation_revision=target.revision if target else 0,
                    selection_revision=audio.revision if audio else 0,
                    output_id=output.id if output else None,
                    review_revision=assessment["review_revision"] if assessment else 0,
                    qc_evidence_fingerprint=assessment["qc_evidence_fingerprint"]
                    if assessment
                    else None,
                )
            )
        tracks.append(dict(tag=track.tag, segments=cells))
    return FitPlanCreate(
        selection_revision=selection.revision,
        transcript_revision=state.transcript_id,
        settings_revision=settings.revision if settings else 0,
        purpose=workflow.purpose,
        tracks=tracks,
    )


def ensure_finish_media(db, project, workflow):
    from .analysis import media_for
    from .workflow import command, connection

    try:
        media_for(db, project, "extract")
        media_for(db, project, "separate")
        return None
    except APIError:
        pass
    config = connection(db, project, "separation")
    body = SimpleNamespace(
        action="prepare_media",
        expected_editor_fingerprint=editor_fingerprint(db, project),
        auto_advance=False,
    )
    dispatch = fingerprint(
        dict(
            kind="media",
            selection=workflow.selection_id,
            editor=body.expected_editor_fingerprint,
            provider_revision=config.revision if config else None,
        )
    )
    link = command_link(
        db,
        project,
        workflow,
        "source",
        "source",
        dispatch,
        lambda: command(db, project, body, workflow.actor_id, pipeline_call=True),
    )
    block = blocked_runs(db, project, link)
    intent = owned(db, WorkflowIntent, project, link.source_id)
    return block or dict(status=intent.status, next_action=intent.next_action)


def finish_branch(db, project, workflow, rows, result):
    from . import deliveries, fit_plans
    from .delivery_contracts import DeliveryCreate

    media = ensure_finish_media(db, project, workflow)
    if media:
        return dict(purpose=workflow.purpose, **media)
    body = fit_body(db, project, workflow, rows)
    dispatch = fingerprint(
        dict(kind="fit", scope=workflow.delivery_track_ids, body=body.model_dump())
    )
    link = command_link(
        db,
        project,
        workflow,
        "finish",
        "fit",
        dispatch,
        lambda: fit_plans.command(db, project, body, workflow.actor_id, pipeline_call=True),
    )
    block = blocked_runs(db, project, link)
    if block:
        return dict(fit_id=link.fit_id, purpose=workflow.purpose, **block)
    parent = owned(db, FitPlanCommand, project, link.fit_id)
    if result.prepare_error:
        return dict(
            fit_id=parent.id, status="review", next_action="review_fit", issue=result.prepare_error
        )
    if not result.validated_delivery or result.validated_delivery["fit_plan_id"] != parent.id:
        # Another bounded pass performs CPU proof validation, after this admission commits.
        workflow.wake_revision += 1
        return dict(fit_id=parent.id, status="running", next_action=None)
    choices = dict(workflow.delivery_options)
    if choices["default_audio_track"] is None:
        choices["default_audio_track"] = owned(
            db, LanguageTrack, project, workflow.delivery_track_ids[0]
        ).tag
    delivery = DeliveryCreate(
        fit_plan_id=parent.id,
        expected_fit_run_id=parent.run_id,
        purpose=workflow.purpose,
        **choices,
    )
    dispatch = fingerprint(
        dict(kind="delivery", fit_id=parent.id, body=delivery.model_dump(exclude_none=True))
    )
    link = command_link(
        db,
        project,
        workflow,
        "finish",
        "delivery",
        dispatch,
        lambda: deliveries.admit(
            db, project, delivery, workflow.actor_id, result.validated_delivery, admission_only=True
        ),
    )
    block = blocked_runs(db, project, link)
    finish = dict(fit_id=parent.id, delivery_id=link.delivery_id, purpose=workflow.purpose)
    if block:
        return finish | block
    if result.delivery_detail and result.delivery_detail["id"] == link.delivery_id:
        valid = (
            result.delivery_detail["status"] == "succeeded"
            and result.delivery_detail["current"]
            and result.delivery_detail["manifest_valid"]
            and bool(result.delivery_detail["artifacts"])
        )
        if valid:
            return finish | dict(
                status="completed",
                next_action=None,
                artifact_ids=[a["asset_id"] for a in result.delivery_detail["artifacts"]],
            )
        return finish | dict(
            status="review", next_action="review_delivery", issue="DELIVERY_INPUT_CHANGED"
        )
    workflow.wake_revision += 1
    return finish | dict(status="running", next_action=None)


def publish(db, run, result):
    if not isinstance(result, ControlResult):
        raise ValueError("Expected private pipeline preparation")
    project = db.get(Project, run.project_id)
    workflow = owned(db, PipelineWorkflow, project, run.options["workflow_id"])
    expected = result.binding
    if run.options["generation"] != workflow.generation or any(
        getattr(workflow, k) != v for k, v in expected.items()
    ):
        # Keep newer dirty intent for the next pass; never admit a stale preparation.
        return
    if workflow.stop_requested:
        p.settle_cancel(db, project, workflow)
        workflow.reconciled_revision = max(workflow.reconciled_revision, expected["wake_revision"])
        return
    before = (
        workflow.status,
        workflow.stage,
        workflow.next_action,
        workflow.target_states,
        workflow.finish_state,
    )
    try:
        selection = current_selection(db, project)
        if selection.id != workflow.selection_id:
            workflow.status, workflow.next_action = "stale", "review_source"
        else:
            rows = p.rows_for(db, project)
            source = source_branch(db, project, workflow, rows)
            if source:
                workflow.status, workflow.stage = source["status"], "source"
                workflow.next_action = source["next_action"]
            else:
                states = {}
                for tid in workflow.target_track_ids:
                    track = owned(db, LanguageTrack, project, tid)
                    try:
                        states[tid] = target_branch(
                            db, project, workflow, track, rows, result.runtime
                        )
                    except APIError as error:
                        states[tid] = dict(
                            status="review", next_action="review_target", issue=error.code
                        )
                workflow.target_states = states
                workflow.stage = "targets"
                workflow.status = (
                    "running"
                    if any(s["status"] == "running" for s in states.values())
                    else "review"
                )
                workflow.next_action = None if workflow.status == "running" else "review_targets"
                finish_ready = all(
                    states[tid]["status"] == "ready" for tid in workflow.delivery_track_ids
                )
                if workflow.purpose == "incomplete_preview":
                    # Explicit preview purpose permits omissions, without satisfying dub readiness.
                    finish_ready = not any(
                        states[tid]["status"] == "running" for tid in workflow.delivery_track_ids
                    )
                if finish_ready:
                    try:
                        with db.begin_nested():
                            finish = finish_branch(db, project, workflow, rows, result)
                    except APIError as error:
                        finish = dict(
                            status="review",
                            next_action="review_fit",
                            issue=error.code,
                            purpose=workflow.purpose,
                        )
                    workflow.finish_state = finish
                    workflow.stage, workflow.status = "finish", finish["status"]
                    workflow.next_action = finish["next_action"]
    except APIError as error:
        workflow.status, workflow.next_action = "review", "review_source"
        workflow.finish_state = dict(issue=error.code)
    workflow.reconciled_revision = max(workflow.reconciled_revision, expected["wake_revision"])
    after = (
        workflow.status,
        workflow.stage,
        workflow.next_action,
        workflow.target_states,
        workflow.finish_state,
    )
    if after != before:
        workflow.revision += 1
        from ..execution.events import append_event

        append_event(
            db,
            project,
            "pipeline.completed" if workflow.status == "completed" else "pipeline.updated",
            facts=dict(workflow_id=workflow.id, status=workflow.status, stage=workflow.stage),
        )
    db.flush()

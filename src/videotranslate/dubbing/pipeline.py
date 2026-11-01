"""Owned full workflow commands and pure bounded discovery projections.

This is an association/authorization layer. Existing domain commands own work,
StageRun owns leases/retries, and no GET or event callback dispatches work.
"""

from sqlalchemy import func, or_, select, update

from ..errors import APIError
from ..execution.events import append_event
from ..execution.inputs import fingerprint
from ..models.core import new_id
from ..models.dubbing import LanguageTrack, SegmentRevision, TranscriptRevision, TranslationRevision
from ..models.pipeline import PipelineCheckpoint, PipelineCommand, PipelinePolicy, PipelineWorkflow
from .editor import editor_fingerprint
from .ownership import conflict, owned, owner, scope
from .segments import active_segments_query
from .source import current_selection, source_state
from .translations import translation_state

ACTIVE = {"queued", "running", "retry_wait", "cancelling"}


def mark_dirty(db, project):
    """Coalesced durable wake only; safe inside domain transactions, never dispatch."""
    db.execute(
        update(PipelineWorkflow)
        .where(
            PipelineWorkflow.project_id == project.id,
            PipelineWorkflow.workspace_id == project.workspace_id,
            or_(
                PipelineWorkflow.stop_requested.is_(False), PipelineWorkflow.status == "cancelling"
            ),
        )
        .values(wake_revision=PipelineWorkflow.wake_revision + 1)
    )


def rows_for(db, project):
    state = source_state(db, project)
    if not state or not state.transcript_id:
        return []
    rows = db.scalars(active_segments_query(project, state.transcript_id).limit(1001)).all()
    if len(rows) > 1000:
        raise APIError(422, "PIPELINE_ROW_LIMIT", "At most 1000 current source rows are supported")
    return rows


def source_guard(db, project):
    return fingerprint(
        dict(
            editor=editor_fingerprint(db, project),
            issues=[[row.id, row.source_analysis_flags] for row in rows_for(db, project)],
        )
    )


def target_guard(db, project, track, rows=None):
    rows = rows_for(db, project) if rows is None else rows
    state = source_state(db, project)
    heads = []
    for row in rows:
        source = owned(db, SegmentRevision, project, row.current_revision_id)
        target = translation_state(db, project, track, row)
        heads.append(
            [
                row.id,
                fingerprint(source.text),
                target.revision if target else 0,
                target.current_revision_id if target else None,
                target.locked if target else False,
                target.stale if target else False,
            ]
        )
    return fingerprint(
        dict(
            selection=state.selection_id if state else None,
            transcript=state.transcript_id if state else None,
            language=project.source_language,
            track=[track.id, track.revision, track.mode, track.context_revision_id, track.archived],
            heads=heads,
        )
    )


def policy_for(db, project, workflow):
    return db.scalar(
        scope(PipelinePolicy, project).where(
            PipelinePolicy.workflow_id == workflow.id,
            PipelinePolicy.revision == workflow.policy_revision,
        )
    )


def checkpoint(db, project, workflow, scope_key, guard, provenance=None):
    query = scope(PipelineCheckpoint, project).where(
        PipelineCheckpoint.workflow_id == workflow.id,
        PipelineCheckpoint.scope_key == scope_key,
        PipelineCheckpoint.guard == guard,
    )
    if provenance:
        query = query.where(PipelineCheckpoint.provenance == provenance)
    records = db.scalars(query.order_by(PipelineCheckpoint.created_at.desc())).all()
    return next(
        (
            r
            for r in records
            if r.provenance == "human"
            or (
                r.policy_revision == workflow.policy_revision
                and policy_for(db, project, workflow).auto_advance
            )
        ),
        None,
    )


def save_checkpoint(db, project, workflow, scope_key, guard, actor, provenance="human"):
    existing = checkpoint(db, project, workflow, scope_key, guard, provenance)
    if existing:
        return existing
    row = PipelineCheckpoint(
        id=new_id(),
        **owner(project),
        workflow_id=workflow.id,
        scope_key=scope_key,
        guard=guard,
        provenance=provenance,
        policy_revision=workflow.policy_revision,
        actor_id=actor,
    )
    db.add(row)
    db.flush()
    append_event(
        db,
        project,
        "pipeline.checkpoint",
        facts=dict(workflow_id=workflow.id, provenance=provenance, fingerprint=guard),
    )
    return row


def validate_authorization(db, project, track, checkpoint_id):
    record = owned(db, PipelineCheckpoint, project, checkpoint_id)
    workflow = owned(db, PipelineWorkflow, project, record.workflow_id)
    if (
        workflow.stop_requested
        or track.id not in workflow.target_track_ids
        or record.scope_key != "target:" + track.id
        or record.guard != target_guard(db, project, track)
        or not checkpoint(db, project, workflow, record.scope_key, record.guard)
        or not checkpoint(db, project, workflow, "source", source_guard(db, project))
    ):
        conflict()
    return record


def ensure_scope(db, project, targets, finish):
    for track_id in targets:
        if owned(db, LanguageTrack, project, track_id).archived:
            raise APIError(409, "TARGET_ARCHIVED", "Choose active language tracks")
    if not set(finish) <= set(targets):
        conflict()
    if len(rows_for(db, project)) * len(targets) > 1000:
        raise APIError(422, "PIPELINE_CELL_LIMIT", "Workflow supports at most 1000 target cells")


def start(db, project, body, actor):
    selection = current_selection(db, project)
    digest = editor_fingerprint(db, project)
    if body.expected_editor_fingerprint != digest:
        conflict()
    state = source_state(db, project)
    if body.source_mode in {"use_current", "manual_import"} and not state.transcript_id:
        raise APIError(409, "TRANSCRIPT_REQUIRED", "Import or edit source text before continuing")
    if body.source_mode == "manual_import":
        transcript = owned(db, TranscriptRevision, project, state.transcript_id)
        if transcript.provenance != "import":
            raise APIError(409, "SOURCE_IMPORT_REQUIRED", "Choose an imported current transcript")
    ensure_scope(db, project, body.target_track_ids, body.delivery_track_ids)
    signature = fingerprint(body.model_dump() | {"selection_id": selection.id})
    prior = db.scalar(
        scope(PipelineWorkflow, project).where(PipelineWorkflow.signature == signature)
    )
    if prior:
        return detail(db, project, prior)
    workflow = PipelineWorkflow(
        id=new_id(),
        **owner(project),
        selection_id=selection.id,
        signature=signature,
        actor_id=actor,
        source_mode=body.source_mode,
        purpose=body.purpose,
        target_track_ids=body.target_track_ids,
        delivery_track_ids=body.delivery_track_ids,
        delivery_options=body.delivery_options.model_dump(),
    )
    db.add(workflow)
    db.flush()
    db.add(
        PipelinePolicy(
            **owner(project),
            workflow_id=workflow.id,
            revision=1,
            auto_advance=body.auto_advance,
            actor_id=actor,
        )
    )
    db.flush()
    append_event(db, project, "pipeline.started", facts={"workflow_id": workflow.id})
    return detail(db, project, workflow)


def cas(workflow, body):
    if workflow.revision != body.revision:
        conflict()


def touch(db, project, workflow, kind):
    workflow.revision += 1
    workflow.wake_revision += 1
    append_event(
        db, project, kind, facts={"workflow_id": workflow.id, "revision": workflow.revision}
    )
    db.flush()


def continue_workflow(db, project, workflow, body, actor):
    cas(workflow, body)
    if workflow.stop_requested:
        raise APIError(409, "PIPELINE_STOPPED", "Resume this workflow explicitly first")
    if body.kind == "source":
        if body.track_id is not None or body.guard != source_guard(db, project):
            conflict()
        if not rows_for(db, project):
            raise APIError(409, "TRANSCRIPT_REQUIRED", "Current source rows are required")
        save_checkpoint(db, project, workflow, "source", body.guard, actor)
    elif body.kind == "translation":
        if body.track_id not in workflow.target_track_ids:
            conflict()
        track = owned(db, LanguageTrack, project, body.track_id)
        rows = rows_for(db, project)
        if body.guard != target_guard(db, project, track, rows):
            conflict()
        for row in rows:
            state = translation_state(db, project, track, row)
            if not state or state.stale:
                raise APIError(
                    409, "TARGET_STALE", "Every current source row needs current target text"
                )
            revision = owned(db, TranslationRevision, project, state.current_revision_id)
            if not revision.text.strip() or (state.locked and not revision.approved):
                raise APIError(
                    409, "TARGET_LOCKED_REVIEW_REQUIRED", "Review locked text in its editor first"
                )
        save_checkpoint(db, project, workflow, "target:" + track.id, body.guard, actor)
    elif body.guard != source_guard(db, project):
        conflict()
    touch(db, project, workflow, "pipeline.continued")
    return detail(db, project, workflow)


def change_policy(db, project, workflow, body, actor):
    cas(workflow, body)
    if policy_for(db, project, workflow).auto_advance != body.auto_advance:
        workflow.policy_revision += 1
        db.add(
            PipelinePolicy(
                **owner(project),
                workflow_id=workflow.id,
                revision=workflow.policy_revision,
                auto_advance=body.auto_advance,
                actor_id=actor,
            )
        )
        touch(db, project, workflow, "pipeline.policy_changed")
    return detail(db, project, workflow)


def change_scope(db, project, workflow, body):
    cas(workflow, body)
    ensure_scope(db, project, body.target_track_ids, body.delivery_track_ids)
    if (
        workflow.target_track_ids != body.target_track_ids
        or workflow.delivery_track_ids != body.delivery_track_ids
    ):
        removed = set(workflow.target_track_ids) - set(body.target_track_ids)
        stop_links(db, project, workflow, scopes={"target:" + tid for tid in removed})
        workflow.target_track_ids, workflow.delivery_track_ids = (
            body.target_track_ids,
            body.delivery_track_ids,
        )
        workflow.scope_revision += 1
        workflow.generation += 1
        touch(db, project, workflow, "pipeline.scope_changed")
    return detail(db, project, workflow)


def links(db, project, workflow):
    return db.scalars(
        scope(PipelineCommand, project)
        .where(PipelineCommand.workflow_id == workflow.id)
        .order_by(PipelineCommand.created_at, PipelineCommand.id)
    ).all()


def command_identity(link):
    for kind in ("source", "translation", "synthesis", "qc", "fit", "delivery"):
        if value := getattr(link, kind + "_id"):
            return kind, value
    raise ValueError("Invalid pipeline command association")


def command_runs(db, project, link):
    from ..models.analysis import WorkflowChild
    from ..models.delivery import DeliveryCommand
    from ..models.execution import StageRun
    from ..models.finishing import FitPlanCommand
    from ..models.synthesis import SynthesisLine
    from ..models.translation import TranslationPhase
    from ..models.voice_qc import VoiceQCLine

    kind, value = command_identity(link)
    if kind in {"fit", "delivery"}:
        model = FitPlanCommand if kind == "fit" else DeliveryCommand
        run_ids = [owned(db, model, project, value).run_id]
    else:
        model, column = {
            "source": (WorkflowChild, WorkflowChild.workflow_id),
            "translation": (TranslationPhase, TranslationPhase.command_id),
            "synthesis": (SynthesisLine, SynthesisLine.command_id),
            "qc": (VoiceQCLine, VoiceQCLine.command_id),
        }[kind]
        run_ids = db.scalars(
            scope(model, project).where(column == value).with_only_columns(model.run_id)
        ).all()
    return [owned(db, StageRun, project, rid) for rid in run_ids if rid]


def mark_shared(db, project, kind, command_id):
    """An explicit independent domain consumer revokes exclusive cancellation ownership."""
    db.execute(
        update(PipelineCommand)
        .where(
            PipelineCommand.project_id == project.id,
            PipelineCommand.workspace_id == project.workspace_id,
            getattr(PipelineCommand, kind + "_id") == command_id,
        )
        .values(exclusively_owned=False)
    )


def attach(db, project, workflow, scope_key, kind, command_id, dispatch_key, created):
    prior = db.scalar(
        scope(PipelineCommand, project).where(
            PipelineCommand.workflow_id == workflow.id, PipelineCommand.dispatch_key == dispatch_key
        )
    )
    if prior:
        return prior
    consumers = db.scalars(
        scope(PipelineCommand, project).where(getattr(PipelineCommand, kind + "_id") == command_id)
    ).all()
    if consumers:
        for row in consumers:
            row.exclusively_owned = False
    link = PipelineCommand(
        id=new_id(),
        **owner(project),
        workflow_id=workflow.id,
        scope_key=scope_key,
        generation=workflow.generation,
        dispatch_key=dispatch_key,
        exclusively_owned=created and not consumers,
        **{kind + "_id": command_id},
    )
    db.add(link)
    db.flush()
    return link


def stop_links(db, project, workflow, scopes=None):
    from ..execution.service import cancel_run
    from ..models.analysis import WorkflowIntent
    from ..models.translation import TranslationCommand

    for link in links(db, project, workflow):
        if scopes is not None and link.scope_key not in scopes:
            continue
        if not link.exclusively_owned:
            continue
        kind, value = command_identity(link)
        if kind == "translation":
            owned(db, TranslationCommand, project, value).continuation_stopped = True
        if kind == "source":
            intent = owned(db, WorkflowIntent, project, value)
            intent.continuation_stopped = True
            intent.status, intent.next_action = "cancelled", "review_source"
        db.flush()  # stop barrier is visible to the same publication transaction
        for run in command_runs(db, project, link):
            cancel_run(db, project.workspace_id, run.id)


def unresolved_work(db, project, workflow):
    pending = []
    for link in links(db, project, workflow):
        for run in command_runs(db, project, link):
            if run.remote_state == "submitting" or (
                run.remote_id and run.remote_state != "completed"
            ):
                pending.append(
                    dict(
                        run_id=run.id,
                        status=run.status,
                        exclusively_owned=link.exclusively_owned,
                        submission_uncertain=run.remote_state == "submitting",
                    )
                )
    return pending


def settle_cancel(db, project, workflow):
    pending = unresolved_work(db, project, workflow)
    owns_pending = any(row["exclusively_owned"] for row in pending)
    workflow.status = "cancelling" if owns_pending else "cancelled"
    workflow.next_action = "review_run" if owns_pending else "resume_workflow"


def cancel(db, project, workflow, body):
    cas(workflow, body)
    if not workflow.stop_requested:
        workflow.stop_requested = True
        workflow.generation += 1
        stop_links(db, project, workflow)
        settle_cancel(db, project, workflow)
        touch(db, project, workflow, "pipeline.cancelled")
    return detail(db, project, workflow)


def resume(db, project, workflow, body):
    cas(workflow, body)
    current_selection(db, project)
    workflow.stop_requested = False
    workflow.generation += 1
    workflow.status, workflow.next_action = "running", None
    touch(db, project, workflow, "pipeline.resumed")
    from ..models.analysis import WorkflowIntent
    from ..models.translation import TranslationCommand

    for link in links(db, project, workflow):
        if not link.exclusively_owned or link.scope_key not in {
            "source",
            *("target:" + tid for tid in workflow.target_track_ids),
        }:
            continue
        if link.translation_id:
            owned(db, TranslationCommand, project, link.translation_id).continuation_stopped = False
        if link.source_id:
            owned(db, WorkflowIntent, project, link.source_id).continuation_stopped = False
    # Existing cancelled/unknown phase jobs are deliberately not retried here.
    return detail(db, project, workflow)


def detail(db, project, workflow):
    targets = []
    for tid in workflow.target_track_ids:
        track = owned(db, LanguageTrack, project, tid)
        targets.append(
            dict(
                track_id=tid,
                tag=track.tag,
                guard=target_guard(db, project, track),
                **workflow.target_states.get(tid, {"status": "pending", "next_action": None}),
            )
        )
    query = scope(PipelineCommand, project).where(PipelineCommand.workflow_id == workflow.id)
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    commands = db.scalars(
        query.order_by(PipelineCommand.created_at.desc(), PipelineCommand.id).limit(100)
    ).all()
    checkpoints = db.scalars(
        scope(PipelineCheckpoint, project)
        .where(PipelineCheckpoint.workflow_id == workflow.id)
        .order_by(PipelineCheckpoint.created_at.desc(), PipelineCheckpoint.id)
        .limit(100)
    ).all()
    return dict(
        id=workflow.id,
        revision=workflow.revision,
        generation=workflow.generation,
        policy_revision=workflow.policy_revision,
        scope_revision=workflow.scope_revision,
        status=workflow.status,
        stage=workflow.stage,
        next_action=workflow.next_action,
        source_mode=workflow.source_mode,
        source_guard=source_guard(db, project),
        source_selection_id=workflow.selection_id,
        auto_advance=policy_for(db, project, workflow).auto_advance,
        purpose=workflow.purpose,
        target_track_ids=workflow.target_track_ids,
        delivery_track_ids=workflow.delivery_track_ids,
        delivery_options=workflow.delivery_options,
        dirty=workflow.wake_revision > workflow.reconciled_revision,
        stop_requested=workflow.stop_requested,
        control_run_id=workflow.control_run_id,
        event_cursor=project.event_sequence,
        targets=targets,
        finish=workflow.finish_state,
        unresolved_remote=unresolved_work(db, project, workflow)[:100],
        commands_total=count,
        commands=[
            dict(
                id=link.id,
                kind=command_identity(link)[0],
                command_id=command_identity(link)[1],
                scope=link.scope_key,
                exclusively_owned=link.exclusively_owned,
                run_ids=[r.id for r in command_runs(db, project, link)],
            )
            for link in commands
        ],
        checkpoints=[
            dict(
                id=r.id,
                scope=r.scope_key,
                guard=r.guard,
                provenance=r.provenance,
                policy_revision=r.policy_revision,
            )
            for r in checkpoints
        ],
    )


def list_workflows(db, project, limit=20, offset=0):
    query = scope(PipelineWorkflow, project)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(PipelineWorkflow.created_at.desc(), PipelineWorkflow.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return dict(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            dict(
                id=r.id,
                revision=r.revision,
                status=r.status,
                stage=r.stage,
                next_action=r.next_action,
                purpose=r.purpose,
                dirty=r.wake_revision > r.reconciled_revision,
            )
            for r in rows
        ],
    )

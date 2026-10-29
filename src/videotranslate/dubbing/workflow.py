"""Database-backed analysis intents; only fresh successful publications advance."""

from sqlalchemy import select

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.events import append_event
from ..execution.inputs import fingerprint
from ..execution.service import create_run
from ..models.analysis import WorkflowChild, WorkflowIntent
from ..models.core import Project, new_id
from ..models.providers import ProviderConnection
from .editor import editor_fingerprint
from .ownership import conflict, owned, owner, scope
from .source import current_selection


def safe_workflow(db, project, intent):
    children = db.scalars(
        scope(WorkflowChild, project)
        .where(WorkflowChild.workflow_id == intent.id)
        .order_by(WorkflowChild.created_at, WorkflowChild.id)
    ).all()
    from ..models.execution import StageRun

    for child in children:
        child_run = owned(db, StageRun, project, child.run_id)
        if child_run.stage == intent.stage:
            sync_run_state(db, child_run)
    return {
        "id": intent.id,
        "action": intent.action,
        "status": intent.status,
        "stage": intent.stage,
        "next_action": intent.next_action,
        "auto_advance": intent.auto_advance,
        "run_ids": [child.run_id for child in children],
    }


def connection(db, project, slot):
    return db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == project.workspace_id, ProviderConnection.slot == slot
        )
    )


def queue_child(db, project, intent, stage):
    shared = stage in {"extract", "separate"}
    run = None
    if stage == "transcribe":
        from ..execution.inputs import is_current
        from ..execution.prepared import has_prepared
        from ..models.execution import StageRun

        candidates = db.scalars(
            scope(StageRun, project).where(
                StageRun.stage == stage,
                StageRun.is_stale.is_(False),
                StageRun.status.in_(
                    ["queued", "running", "retry_wait", "failed", "needs_review", "cancelling"]
                ),
            )
        )
        for candidate in candidates:
            prior_intents = db.scalars(
                scope(WorkflowIntent, project)
                .join(WorkflowChild, WorkflowChild.workflow_id == WorkflowIntent.id)
                .where(WorkflowChild.run_id == candidate.id)
            ).all()
            if (
                prior_intents
                and all(
                    prior.editor_fingerprint == intent.editor_fingerprint for prior in prior_intents
                )
                and is_current(db, project, candidate.dependency_snapshot)
                and (
                    candidate.status in {"queued", "running", "retry_wait", "cancelling"}
                    or candidate.remote_state == "submitting"
                    or has_prepared(db, candidate)
                )
            ):
                run = candidate
                break
    run = run or create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(stage=stage),
        idempotency_key=None if shared else f"workflow:{intent.id}:{stage}",
        reuse_active=shared,
    )
    db.add(WorkflowChild(**owner(project), workflow_id=intent.id, run_id=run.id))
    intent.stage, intent.status, intent.next_action = stage, "running", None
    db.flush()
    if run.status == "succeeded":
        advance_for_run(db, run)
    else:
        sync_run_state(db, run)


def command(db, project, body, actor):
    selection = current_selection(db, project)
    digest = editor_fingerprint(db, project)
    if body.expected_editor_fingerprint != digest:
        conflict()
    providers = {slot: connection(db, project, slot) for slot in ("separation", "transcription")}
    signature = fingerprint(
        {
            "action": body.action,
            "selection": selection.id,
            "editor": digest if body.action == "analyse" else None,
            "auto_advance": body.auto_advance,
            "providers": {
                slot: row.revision if row else None
                for slot, row in providers.items()
                if body.action == "analyse" or slot == "separation"
            },
        }
    )
    prior = db.scalar(
        scope(WorkflowIntent, project).where(WorkflowIntent.command_fingerprint == signature)
    )
    if prior:
        return safe_workflow(db, project, prior)
    if body.action == "analyse":
        from ..models.execution import StageRun

        unresolved = db.scalar(
            scope(StageRun, project)
            .where(StageRun.stage == "transcribe", StageRun.remote_state == "submitting")
            .limit(1)
        )
        if unresolved:
            raise APIError(
                409,
                "SUBMISSION_UNCERTAIN",
                "Resolve the current source model operation before starting another analysis",
            )
    intent = WorkflowIntent(
        id=new_id(),
        **owner(project),
        selection_id=selection.id,
        command_fingerprint=signature,
        editor_fingerprint=digest,
        action=body.action,
        actor_id=actor,
        auto_advance=body.auto_advance,
    )
    db.add(intent)
    db.flush()
    queue_child(db, project, intent, "extract")
    append_event(
        db, project, "workflow.queued", facts={"workflow_id": intent.id, "action": intent.action}
    )
    return safe_workflow(db, project, intent)


def publication_current(db, run):
    project = db.get(Project, run.project_id)
    children = db.scalars(scope(WorkflowChild, project).where(WorkflowChild.run_id == run.id)).all()
    # Transcription must originate from an explicit guarded analysis command.
    if not children:
        return False
    return all(
        owned(db, WorkflowIntent, project, child.workflow_id).editor_fingerprint
        == editor_fingerprint(db, project)
        for child in children
    )


def advance_for_run(db, run):
    project = db.get(Project, run.project_id)
    for child in db.scalars(scope(WorkflowChild, project).where(WorkflowChild.run_id == run.id)):
        intent = owned(db, WorkflowIntent, project, child.workflow_id)
        if intent.status != "running" or intent.stage != run.stage:
            continue
        if run.status != "succeeded":
            if run.status in {"stale", "failed", "needs_review", "cancelled"}:
                intent.status = (
                    "stale"
                    if run.is_stale
                    else ("cancelled" if run.status == "cancelled" else "failed")
                )
                intent.next_action = "review_run"
            continue
        selection = current_selection(db, project, required=False)
        if not selection or selection.id != intent.selection_id:
            intent.status, intent.next_action = "stale", "review_source"
            continue
        if (
            run.stage != "transcribe"
            and intent.action == "analyse"
            and intent.editor_fingerprint != editor_fingerprint(db, project)
        ):
            intent.status, intent.next_action = "stale", "review_source"
        elif run.stage == "extract":
            if connection(db, project, "separation"):
                queue_child(db, project, intent, "separate")
            else:
                intent.status, intent.next_action = "paused", "configure_separation"
        elif run.stage == "separate":
            if intent.action == "prepare_media":
                intent.status, intent.next_action = "review", "source_and_reference_review"
            elif connection(db, project, "transcription"):
                try:
                    queue_child(db, project, intent, "transcribe")
                except APIError:
                    intent.status, intent.next_action = "paused", "configure_transcription"
            else:
                intent.status, intent.next_action = "paused", "configure_transcription"
        elif run.stage == "transcribe":
            # Translation/TTS/export are deliberately unavailable in this increment.
            intent.status, intent.next_action = "review", "source_and_cast_review"
        append_event(
            db,
            project,
            "workflow.updated",
            facts={"workflow_id": intent.id, "status": intent.status, "stage": intent.stage},
        )


def sync_run_state(db, run):
    """Mirror persisted child lifecycle changes, including retry/cancel/recovery."""
    if run.status == "succeeded":
        return
    project = db.get(Project, run.project_id)
    for child in db.scalars(scope(WorkflowChild, project).where(WorkflowChild.run_id == run.id)):
        intent = owned(db, WorkflowIntent, project, child.workflow_id)
        if intent.stage != run.stage:
            continue
        if run.status in {"queued", "running", "retry_wait", "cancelling"}:
            intent.status, intent.next_action = "running", None
        elif run.status in {"failed", "needs_review", "stale", "cancelled"}:
            intent.status = (
                "stale"
                if run.is_stale
                else ("cancelled" if run.status == "cancelled" else "failed")
            )
            intent.next_action = "review_run"

"""Append-only safe facts, sequenced by the project row in the caller transaction."""

import re

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models.core import Project
from ..models.execution import ProjectEvent, StageRun

_NUMBERS = {
    "revision",
    "byte_size",
    "audio_ordinal",
    "duration_ms",
    "count",
    "attempt",
    "delay_seconds",
    "elapsed_ms",
}
_IDS = {
    "asset_id",
    "code",
    "provider",
    "model",
    "remote_id",
    "fingerprint",
    "recovery",
    "segment_id",
    "speaker_id",
    "track_id",
    "selection_id",
    "transcript_id",
    "target_language",
    "provenance",
    "merged_into_id",
    "workflow_id",
    "action",
    "status",
    "stage",
    "reference_id",
}


def safe_facts(facts: dict) -> dict:
    if not isinstance(facts, dict) or len(facts) > 20:
        raise ValueError("Invalid event facts")
    result = {}
    for key, value in facts.items():
        if key in _NUMBERS and type(value) is int and 0 <= value <= 2**63 - 1:
            result[key] = value
        elif (
            key in _IDS
            and isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,199}", value)
            and ".." not in value
            and "://" not in value
        ):
            result[key] = value
        else:
            raise ValueError("Unsafe event facts")
    return result


def append_event(
    db: Session,
    project: Project,
    kind: str,
    *,
    run: StageRun | None = None,
    facts: dict | None = None,
) -> ProjectEvent:
    if not re.fullmatch(r"[a-z][a-z0-9_.]{0,59}", kind):
        raise ValueError("Invalid event kind")
    facts = safe_facts(facts or {})
    sequence = db.scalar(
        update(Project)
        .where(Project.id == project.id, Project.workspace_id == project.workspace_id)
        .values(event_sequence=Project.event_sequence + 1)
        .returning(Project.event_sequence)
    )
    event = ProjectEvent(
        workspace_id=project.workspace_id,
        project_id=project.id,
        sequence=sequence,
        kind=kind,
        facts=facts,
        run_id=run.id if run else None,
        stage=run.stage if run else None,
        segment_id=run.segment_id if run else None,
        target_language=run.target_language if run else None,
        attempt=run.attempt_count if run else None,
    )
    db.add(event)
    if run:
        from ..dubbing.workflow import sync_run_state

        sync_run_state(db, run)
    return event


def event_json(event: ProjectEvent) -> dict:
    return {
        key: getattr(event, key)
        for key in (
            "sequence",
            "kind",
            "run_id",
            "stage",
            "segment_id",
            "target_language",
            "attempt",
            "facts",
            "created_at",
        )
    }

"""Named fingerprints: revision is lineage, exact dependencies decide freshness."""

import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..errors import APIError
from ..models.core import Asset, Project
from ..models.execution import InputState, StageRun


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def lock_project(db: Session, project: Project) -> Project:
    # A write precedes snapshot reads even on SQLite. PostgreSQL obtains its project
    # row lock first; every execution mutation uses this order before touching runs.
    found = db.scalar(
        update(Project)
        .where(
            Project.id == project.id,
            Project.workspace_id == project.workspace_id,
            Project.deleted_at.is_(None),
        )
        .values(event_sequence=Project.event_sequence)
        .returning(Project.id)
    )
    if found is None:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    db.refresh(project)
    return project


def input_rows(db, project):
    return db.scalars(
        select(InputState).where(
            InputState.project_id == project.id, InputState.workspace_id == project.workspace_id
        )
    ).all()


def set_inputs(db: Session, project: Project, values: dict) -> None:
    lock_project(db, project)
    states = {row.key: row for row in input_rows(db, project)}
    changed = set()
    for key, value in values.items():
        if not key or len(key) > 200:
            raise ValueError("Invalid input key")
        digest = fingerprint(value)
        row = states.get(key)
        if row is None:
            row = InputState(
                workspace_id=project.workspace_id,
                project_id=project.id,
                key=key,
                fingerprint=digest,
            )
            db.add(row)
            states[key] = row
            changed.add(key)
        elif row.fingerprint != digest:
            row.fingerprint = digest
            changed.add(key)
    if not changed:
        return
    # Fixed point traversal handles target/segment-specific downstream consumers.
    runs = db.scalars(
        select(StageRun).where(
            StageRun.project_id == project.id, StageRun.workspace_id == project.workspace_id
        )
    ).all()
    while changed:
        downstream = set()
        for run in runs:
            if run.is_stale or not changed.intersection(run.dependency_snapshot):
                continue
            if all(
                states.get(k) and states[k].fingerprint == v
                for k, v in run.dependency_snapshot.items()
            ):
                continue
            run.is_stale = True
            # An accepted remote job remains pollable after its inputs change.
            # The stale marker suppresses publication when the job completes.
            pending_remote = (
                run.remote_id is not None
                and run.remote_state == "submitted"
                and run.status in {"queued", "retry_wait", "failed", "needs_review", "stale"}
            )
            if run.status not in {"running", "cancelling"} and not pending_remote:
                run.status = "stale"
            output = states.pop(run.output_key, None)
            if output is not None:
                db.delete(output)
            downstream.add(run.output_key)
        changed = downstream
    db.flush()


def initialize_inputs(db: Session, project: Project) -> None:
    states = {row.key for row in input_rows(db, project)}
    values = {
        "source.audio_track": project.source_track_index,
        "source.language": project.source_language,
    }
    from ..models.providers import ProviderConnection

    connections = db.scalars(
        select(ProviderConnection).where(ProviderConnection.workspace_id == project.workspace_id)
    ).all()
    values.update(
        {"provider." + connection.slot: connection.settings for connection in connections}
    )
    asset = db.get(Asset, project.source_asset_id) if project.source_asset_id else None
    if asset and asset.workspace_id == project.workspace_id and asset.project_id == project.id:
        values["source.video"] = {"asset_id": asset.id, "sha256": asset.sha256}
    set_inputs(db, project, {k: v for k, v in values.items() if k not in states})


def capture_inputs(db: Session, project: Project, keys: list[str]) -> dict[str, str]:
    states = {row.key: row.fingerprint for row in input_rows(db, project)}
    if any(key not in states for key in keys):
        raise APIError(409, "INPUT_REQUIRED", "Required stage input is unavailable")
    return {key: states[key] for key in sorted(keys)}


def is_current(db: Session, project: Project, snapshot: dict[str, str]) -> bool:
    states = {row.key: row.fingerprint for row in input_rows(db, project)}
    return all(states.get(key) == value for key, value in snapshot.items())

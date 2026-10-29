"""All domain access is scoped through an active owned project, then project-first lock."""

from sqlalchemy import select, update

from ..errors import APIError
from ..execution.events import append_event
from ..execution.inputs import lock_project
from ..models.core import Project, utcnow
from ..routes.projects import owned_project


def not_found():
    raise APIError(404, "NOT_FOUND", "Resource not found")


def conflict():
    raise APIError(
        409, "REVISION_CONFLICT", "Resource changed; reload and try again", retryable=True
    )


def invalid():
    raise APIError(422, "INVALID_EDIT", "Invalid edit")


def scope(model, project):
    return select(model).where(
        model.project_id == project.id, model.workspace_id == project.workspace_id
    )


def owned(db, model, project, row_id):
    row = db.scalar(scope(model, project).where(model.id == row_id))
    if row is None:
        not_found()
    return row


def project_for(db, identity, project_id, *, write=False):
    project = owned_project(db, identity.workspace.id, project_id)
    return lock_project(db, project) if write else project


def owner(project):
    return {"project_id": project.id, "workspace_id": project.workspace_id}


def changed(db, project, kind, *, run=None, **facts):
    db.execute(
        update(Project)
        .where(Project.id == project.id)
        .values(revision=Project.revision + 1, updated_at=utcnow())
    )
    append_event(db, project, kind, run=run, facts=facts)
    db.flush()


def check_revision(row, expected):
    if row.revision != expected:
        conflict()

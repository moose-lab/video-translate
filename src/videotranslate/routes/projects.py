"""Workspace-scoped project operations with optimistic compare-and-swap updates."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import APIError
from ..models.core import Project, utcnow
from ..security import Identity, require_csrf, require_identity

router = APIRouter(prefix="/projects", tags=["projects"])
Language = Annotated[str, Field(min_length=2, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9-]+$")]
ProjectName = Annotated[str, Field(min_length=1, max_length=200)]


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_advance: bool | None = None


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ProjectName
    source_language: Language = "auto"
    target_languages: list[Language] = Field(
        default_factory=lambda: ["en"], min_length=1, max_length=20
    )
    source_track_index: int = Field(default=0, ge=0, le=100)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("Name required")
        return value.strip()

    @field_validator("target_languages")
    @classmethod
    def target_languages_unique(cls, values):
        if len(set(values)) != len(values) or "auto" in values:
            raise ValueError("Target languages must be explicit and unique")
        return values


class ProjectPatch(ProjectCreate):
    name: ProjectName | None = None
    source_language: Language | None = None
    target_languages: list[Language] | None = Field(default=None, min_length=1, max_length=20)
    source_track_index: int | None = Field(default=None, ge=0, le=100)
    settings: ProjectSettings | None = None
    revision: int | None = Field(default=None, ge=1)

    @field_validator(
        "name",
        "source_language",
        "target_languages",
        "source_track_index",
        "settings",
        "revision",
        mode="before",
    )
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value


def project_query(workspace_id: str):
    return select(Project).where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))


def owned_project(db: Session, workspace_id: str, project_id: str) -> Project:
    project = db.scalar(project_query(workspace_id).where(Project.id == project_id))
    if project is None:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    return project


def project_json(project: Project) -> dict:
    fields = (
        "id",
        "name",
        "status",
        "revision",
        "source_language",
        "target_languages",
        "source_asset_id",
        "source_track_index",
        "settings",
        "created_at",
        "updated_at",
    )
    return {name: getattr(project, name) for name in fields}


def update_project(
    db: Session, project: Project, changes: dict, expected_revision: int | None = None
) -> Project:
    """Join caller's transaction; caller commits project + related writes atomically."""
    expected = project.revision if expected_revision is None else expected_revision
    result = db.execute(
        update(Project)
        .where(
            Project.id == project.id,
            Project.workspace_id == project.workspace_id,
            Project.deleted_at.is_(None),
            Project.revision == expected,
        )
        .values(**changes, revision=Project.revision + 1, updated_at=utcnow())
    )
    if result.rowcount != 1:
        db.rollback()
        raise APIError(
            409, "REVISION_CONFLICT", "Project changed; reload and try again", retryable=True
        )
    db.refresh(project)
    return project


@router.get("")
def list_projects(identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    projects = db.scalars(
        project_query(identity.workspace.id).order_by(Project.created_at.desc())
    ).all()
    return {"items": [project_json(project) for project in projects], "total": len(projects)}


@router.post("", status_code=201)
def create_project(
    body: ProjectCreate, identity: Identity = Depends(require_csrf), db: Session = Depends(get_db)
):
    values = body.model_dump()
    values["settings"] = body.settings.model_dump(exclude_unset=True)
    project = Project(workspace_id=identity.workspace.id, **values)
    db.add(project)
    db.commit()
    return project_json(project)


@router.get("/{project_id}")
def get_project(
    project_id: str, identity: Identity = Depends(require_identity), db: Session = Depends(get_db)
):
    return project_json(owned_project(db, identity.workspace.id, project_id))


@router.patch("/{project_id}")
def patch_project(
    project_id: str,
    body: ProjectPatch,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = owned_project(db, identity.workspace.id, project_id)
    changes = body.model_dump(exclude_unset=True)
    expected = changes.pop("revision", None)
    project = update_project(db, project, changes, expected)
    db.commit()
    return project_json(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, identity: Identity = Depends(require_csrf), db: Session = Depends(get_db)
):
    project = owned_project(db, identity.workspace.id, project_id)
    update_project(db, project, {"deleted_at": utcnow()})
    db.commit()
    return Response(status_code=204)

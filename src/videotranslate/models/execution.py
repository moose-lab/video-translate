"""Private queue, immutable attempt history and transactional project event journal."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import UTCDateTime, new_id, utcnow


class StageRun(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        UniqueConstraint("id", "project_id", "workspace_id", name="uq_run_owner"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_run_project_owner",
        ),
        CheckConstraint("attempt_count >= 0 AND auto_failures >= 0", name="ck_run_counts"),
        CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','needs_review','failed','stale','cancelling','cancelled')",
            name="ck_run_status",
        ),
        CheckConstraint(
            "remote_state IN ('not_submitted','submitting','submitted','completed')",
            name="ck_remote_state",
        ),
        Index("ix_runs_queue", "status", "due_at", "created_at"),
        Index("ix_runs_project", "workspace_id", "project_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    stage: Mapped[str] = mapped_column(String(40))
    scope_key: Mapped[str] = mapped_column(String(160))
    target_language: Mapped[str | None] = mapped_column(String(40))
    segment_id: Mapped[str | None] = mapped_column(String(36))
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    input_project_revision: Mapped[int] = mapped_column(Integer)
    dependency_fingerprint: Mapped[str] = mapped_column(String(64))
    dependency_snapshot: Mapped[dict] = mapped_column(JSON)
    output_key: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_failures: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result: Mapped[dict | None] = mapped_column(JSON)
    safe_error: Mapped[dict | None] = mapped_column(JSON)
    provider: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(120))
    request_key: Mapped[str | None] = mapped_column(String(64))
    remote_id: Mapped[str | None] = mapped_column(String(200))
    remote_state: Mapped[str] = mapped_column(String(20), default="not_submitted")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RunAttempt(Base):
    __tablename__ = "run_attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "number"),
        CheckConstraint("number > 0", name="ck_attempt_number"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    outcome: Mapped[str | None] = mapped_column(String(40))
    safe_error: Mapped[dict | None] = mapped_column(JSON)


class InputState(Base):
    __tablename__ = "input_states"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "key"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_input_project_owner",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))


class ProjectEvent(Base):
    __tablename__ = "project_events"
    __table_args__ = (
        UniqueConstraint("project_id", "sequence"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_event_project_owner",
        ),
        ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_event_run_owner",
        ),
        CheckConstraint("sequence > 0", name="ck_event_sequence"),
        Index("ix_events_project", "workspace_id", "project_id", "sequence"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(60))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("stage_runs.id"))
    stage: Mapped[str | None] = mapped_column(String(40))
    segment_id: Mapped[str | None] = mapped_column(String(36))
    target_language: Mapped[str | None] = mapped_column(String(40))
    attempt: Mapped[int | None] = mapped_column(Integer)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RunRequestKey(Base):
    """Immutable request aliases can share one run without sharing key identity."""

    __tablename__ = "run_request_keys"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_run_request_key"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_request_key_project",
        ),
        ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_request_key_run",
        ),
        Index("ix_request_keys_run", "run_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36))
    workspace_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

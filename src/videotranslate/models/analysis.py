"""Private analysis recovery state. Never serialize these rows to public run facts."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import UTCDateTime
from .dubbing import Owned, owned_fk, owner_constraints


class PrivateOperation(Owned, Base):
    __tablename__ = "private_operations"
    __table_args__ = owner_constraints("private_operation") + (
        owned_fk("run_id", "stage_runs", "fk_operation_run"),
        UniqueConstraint("run_id", "generation", name="uq_operation_generation"),
        CheckConstraint(
            "phase IN ('ready','submitting','accepted','terminal','prepared','failed')",
            name="ck_operation_phase",
        ),
        CheckConstraint("connection_revision >= 0", name="ck_operation_revision"),
    )
    run_id: Mapped[str] = mapped_column(String(36))
    generation: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    connection_revision: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(120))
    host: Mapped[str] = mapped_column(String(300))
    prefix: Mapped[str] = mapped_column(String(100))
    phase: Mapped[str] = mapped_column(String(20), default="ready")
    remote_id: Mapped[str | None] = mapped_column(String(200))
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    terminal_payload: Mapped[dict | None] = mapped_column(JSON)
    prepared_payload: Mapped[dict | None] = mapped_column(JSON)
    public_facts: Mapped[dict | None] = mapped_column(JSON)


class PreparedObject(Owned, Base):
    __tablename__ = "prepared_objects"
    __table_args__ = owner_constraints("prepared_object") + (
        owned_fk("operation_id", "private_operations", "fk_prepared_operation"),
        owned_fk("asset_id", "assets", "fk_prepared_asset"),
        UniqueConstraint("storage_key", name="uq_prepared_storage"),
        Index("ix_prepared_gc", "workspace_id", "state", "created_at"),
        CheckConstraint(
            "state IN ('writing','orphan','published','deleting','deleted')",
            name="ck_prepared_state",
        ),
    )
    operation_id: Mapped[str] = mapped_column(String(36))
    storage_key: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(20), default="writing")
    asset_id: Mapped[str | None] = mapped_column(String(36))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reservation_token: Mapped[str | None] = mapped_column(String(64))
    write_settled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    delete_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    gc_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AnalysisMedia(Owned, Base):
    __tablename__ = "analysis_media"
    __table_args__ = owner_constraints("analysis_media") + (
        owned_fk("run_id", "stage_runs", "fk_analysis_media_run"),
        owned_fk("selection_id", "source_selections", "fk_analysis_media_selection"),
        owned_fk("working_asset_id", "assets", "fk_analysis_working_asset"),
        owned_fk("asr_asset_id", "assets", "fk_analysis_asr_asset"),
        owned_fk("vocals_asset_id", "assets", "fk_analysis_vocals_asset"),
        owned_fk("instrumental_asset_id", "assets", "fk_analysis_instrumental_asset"),
        UniqueConstraint("run_id", name="uq_analysis_media_run"),
    )
    run_id: Mapped[str] = mapped_column(String(36))
    selection_id: Mapped[str] = mapped_column(String(36))
    working_asset_id: Mapped[str | None] = mapped_column(String(36))
    asr_asset_id: Mapped[str | None] = mapped_column(String(36))
    vocals_asset_id: Mapped[str | None] = mapped_column(String(36))
    instrumental_asset_id: Mapped[str | None] = mapped_column(String(36))


class WorkflowIntent(Owned, Base):
    __tablename__ = "workflow_intents"
    __table_args__ = owner_constraints("workflow_intent") + (
        owned_fk("selection_id", "source_selections", "fk_workflow_selection"),
        UniqueConstraint("project_id", "command_fingerprint", name="uq_workflow_command"),
        CheckConstraint("action IN ('analyse','prepare_media')", name="ck_workflow_action"),
        CheckConstraint(
            "status IN ('running','paused','review','stale','failed','cancelled')",
            name="ck_workflow_status",
        ),
    )
    selection_id: Mapped[str] = mapped_column(String(36))
    command_fingerprint: Mapped[str] = mapped_column(String(64))
    editor_fingerprint: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="running")
    stage: Mapped[str] = mapped_column(String(40), default="extract")
    next_action: Mapped[str | None] = mapped_column(String(60))
    auto_advance: Mapped[bool] = mapped_column(default=False)
    continuation_stopped: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )


class WorkflowChild(Owned, Base):
    __tablename__ = "workflow_children"
    __table_args__ = owner_constraints("workflow_child") + (
        owned_fk("workflow_id", "workflow_intents", "fk_child_workflow"),
        owned_fk("run_id", "stage_runs", "fk_child_run"),
        UniqueConstraint("workflow_id", "run_id", name="uq_workflow_child"),
    )
    workflow_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))


class ReferenceRequest(Owned, Base):
    __tablename__ = "reference_requests"
    __table_args__ = owner_constraints("reference_request") + (
        owned_fk("run_id", "stage_runs", "fk_reference_request_run"),
        CheckConstraint(
            "origin IN ('uploaded','source','vocals')", name="ck_reference_request_origin"
        ),
        Index("ix_reference_upload_gc", "workspace_id", "upload_state", "created_at"),
    )
    run_id: Mapped[str | None] = mapped_column(String(36))
    origin: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON)
    dependency_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    upload_key: Mapped[str | None] = mapped_column(String(255))
    upload_size: Mapped[int | None] = mapped_column(Integer)
    upload_sha256: Mapped[str | None] = mapped_column(String(64))
    upload_state: Mapped[str | None] = mapped_column(String(20))
    upload_token: Mapped[str | None] = mapped_column(String(64))
    upload_lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    upload_write_settled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    upload_gc_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class VoiceReference(Owned, Base):
    __tablename__ = "voice_references"
    __table_args__ = owner_constraints("voice_reference")
    origin: Mapped[str] = mapped_column(String(20))


class ReferenceVersion(Owned, Base):
    __tablename__ = "reference_versions"
    __table_args__ = owner_constraints("reference_version") + (
        owned_fk("reference_id", "voice_references", "fk_reference_version_root"),
        UniqueConstraint(
            "id", "reference_id", "project_id", "workspace_id", name="uq_reference_version_family"
        ),
        ForeignKeyConstraint(
            ["parent_version_id", "reference_id", "project_id", "workspace_id"],
            [
                "reference_versions.id",
                "reference_versions.reference_id",
                "reference_versions.project_id",
                "reference_versions.workspace_id",
            ],
            name="fk_reference_version_parent",
        ),
        owned_fk("audio_asset_id", "assets", "fk_reference_audio"),
        owned_fk("source_asset_id", "assets", "fk_reference_source_asset"),
        owned_fk("source_track_id", "source_tracks", "fk_reference_source_track"),
        owned_fk("selection_id", "source_selections", "fk_reference_selection"),
        owned_fk("source_segment_id", "segments", "fk_reference_segment"),
        ForeignKeyConstraint(
            ["source_revision_id", "source_segment_id", "project_id", "workspace_id"],
            [
                "segment_revisions.id",
                "segment_revisions.segment_id",
                "segment_revisions.project_id",
                "segment_revisions.workspace_id",
            ],
            name="fk_reference_source_revision",
        ),
        owned_fk("speaker_id", "speakers", "fk_reference_speaker"),
        owned_fk("run_id", "stage_runs", "fk_reference_run"),
        CheckConstraint("duration_ms > 0", name="ck_reference_duration"),
    )
    reference_id: Mapped[str] = mapped_column(String(36))
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    audio_asset_id: Mapped[str] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(String(10000))
    language: Mapped[str] = mapped_column(String(40))
    duration_ms: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    flags: Mapped[list] = mapped_column(JSON, default=list)
    actor_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    source_asset_id: Mapped[str | None] = mapped_column(String(36))
    source_track_id: Mapped[str | None] = mapped_column(String(36))
    selection_id: Mapped[str | None] = mapped_column(String(36))
    source_segment_id: Mapped[str | None] = mapped_column(String(36))
    source_revision_id: Mapped[str | None] = mapped_column(String(36))
    speaker_id: Mapped[str | None] = mapped_column(String(36))
    absolute_start_ms: Mapped[int | None] = mapped_column(Integer)
    absolute_end_ms: Mapped[int | None] = mapped_column(Integer)
    relative_start_ms: Mapped[int | None] = mapped_column(Integer)
    relative_end_ms: Mapped[int | None] = mapped_column(Integer)
    dependency_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class VoiceBinding(Owned, Base):
    __tablename__ = "voice_bindings"
    __table_args__ = owner_constraints("voice_binding") + (
        UniqueConstraint("project_id", "scope_key", name="uq_voice_binding_scope"),
        owned_fk("speaker_id", "speakers", "fk_voice_binding_speaker"),
        owned_fk("segment_id", "segments", "fk_voice_binding_segment"),
        ForeignKeyConstraint(
            ["current_version_id", "id", "project_id", "workspace_id"],
            [
                "voice_binding_versions.id",
                "voice_binding_versions.binding_id",
                "voice_binding_versions.project_id",
                "voice_binding_versions.workspace_id",
            ],
            name="fk_voice_binding_current",
            use_alter=True,
        ),
        CheckConstraint("revision >= 0", name="ck_voice_binding_revision"),
        CheckConstraint(
            "(speaker_id IS NULL) != (segment_id IS NULL)", name="ck_voice_binding_scope"
        ),
    )
    scope_key: Mapped[str] = mapped_column(String(100))
    speaker_id: Mapped[str | None] = mapped_column(String(36))
    segment_id: Mapped[str | None] = mapped_column(String(36))
    current_version_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=0)


class VoiceBindingVersion(Owned, Base):
    __tablename__ = "voice_binding_versions"
    __table_args__ = owner_constraints("voice_binding_version") + (
        owned_fk("binding_id", "voice_bindings", "fk_binding_version_root"),
        UniqueConstraint(
            "id", "binding_id", "project_id", "workspace_id", name="uq_binding_version_family"
        ),
        UniqueConstraint("binding_id", "revision", name="uq_binding_version_revision"),
        ForeignKeyConstraint(
            ["parent_version_id", "binding_id", "project_id", "workspace_id"],
            [
                "voice_binding_versions.id",
                "voice_binding_versions.binding_id",
                "voice_binding_versions.project_id",
                "voice_binding_versions.workspace_id",
            ],
            name="fk_binding_version_parent",
        ),
        owned_fk("reference_version_id", "reference_versions", "fk_binding_reference_version"),
    )
    binding_id: Mapped[str] = mapped_column(String(36))
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    reference_version_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))

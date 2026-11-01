"""Small owned coordinator; domains and StageRun remain execution authorities."""

from sqlalchemy import JSON, Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


class PipelineWorkflow(Owned, Base):
    __tablename__ = "pipeline_workflows"
    __table_args__ = owner_constraints("pipeline") + (
        owned_fk("selection_id", "source_selections", "fk_pipeline_selection"),
        owned_fk("control_run_id", "stage_runs", "fk_pipeline_control"),
        UniqueConstraint("project_id", "signature", name="uq_pipeline_signature"),
        CheckConstraint(
            "status IN ('running','review','paused','failed','stale','cancelling','cancelled','completed')",
            name="ck_pipeline_status",
        ),
        CheckConstraint(
            "source_mode IN ('automatic','use_current','manual_import')", name="ck_pipeline_source"
        ),
        CheckConstraint("purpose IN ('dub','incomplete_preview')", name="ck_pipeline_purpose"),
        CheckConstraint(
            "revision > 0 AND generation > 0 AND policy_revision > 0 AND scope_revision > 0 AND wake_revision >= reconciled_revision",
            name="ck_pipeline_revisions",
        ),
    )
    selection_id: Mapped[str] = mapped_column(String(36))
    signature: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(36))
    source_mode: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20), default="running")
    stage: Mapped[str] = mapped_column(String(40), default="source")
    next_action: Mapped[str | None] = mapped_column(String(60))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    policy_revision: Mapped[int] = mapped_column(Integer, default=1)
    scope_revision: Mapped[int] = mapped_column(Integer, default=1)
    target_track_ids: Mapped[list] = mapped_column(JSON)
    delivery_track_ids: Mapped[list] = mapped_column(JSON)
    delivery_options: Mapped[dict] = mapped_column(JSON)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    wake_revision: Mapped[int] = mapped_column(Integer, default=1)
    reconciled_revision: Mapped[int] = mapped_column(Integer, default=0)
    control_run_id: Mapped[str | None] = mapped_column(String(36))
    target_states: Mapped[dict] = mapped_column(JSON, default=dict)
    finish_state: Mapped[dict] = mapped_column(JSON, default=dict)


class PipelinePolicy(Owned, Base):
    __tablename__ = "pipeline_policies"
    __table_args__ = owner_constraints("pipeline_policy") + (
        owned_fk("workflow_id", "pipeline_workflows", "fk_pipeline_policy_workflow"),
        UniqueConstraint("workflow_id", "revision", name="uq_pipeline_policy_revision"),
    )
    workflow_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    auto_advance: Mapped[bool] = mapped_column(Boolean)
    actor_id: Mapped[str] = mapped_column(String(36))


class PipelineCheckpoint(Owned, Base):
    __tablename__ = "pipeline_checkpoints"
    __table_args__ = owner_constraints("pipeline_checkpoint") + (
        owned_fk("workflow_id", "pipeline_workflows", "fk_pipeline_checkpoint_workflow"),
        UniqueConstraint(
            "workflow_id",
            "scope_key",
            "guard",
            "provenance",
            "policy_revision",
            name="uq_pipeline_checkpoint",
        ),
        CheckConstraint(
            "provenance IN ('human','automatic_policy')", name="ck_pipeline_checkpoint_provenance"
        ),
    )
    workflow_id: Mapped[str] = mapped_column(String(36))
    scope_key: Mapped[str] = mapped_column(String(80))
    guard: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(String(24))
    policy_revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))


COMMAND_TABLES = {
    "source": "workflow_intents",
    "translation": "translation_commands",
    "synthesis": "synthesis_commands",
    "qc": "voice_qc_commands",
    "fit": "fit_plan_commands",
    "delivery": "delivery_commands",
}


class PipelineCommand(Owned, Base):
    __tablename__ = "pipeline_commands"
    __table_args__ = owner_constraints("pipeline_command") + (
        owned_fk("workflow_id", "pipeline_workflows", "fk_pipeline_command_workflow"),
        *(owned_fk(k + "_id", table, "fk_pipeline_" + k) for k, table in COMMAND_TABLES.items()),
        UniqueConstraint("workflow_id", "dispatch_key", name="uq_pipeline_dispatch"),
        CheckConstraint(
            " + ".join(
                "CASE WHEN " + k + "_id IS NOT NULL THEN 1 ELSE 0 END" for k in COMMAND_TABLES
            )
            + " = 1",
            name="ck_pipeline_command_one",
        ),
    )
    workflow_id: Mapped[str] = mapped_column(String(36))
    scope_key: Mapped[str] = mapped_column(String(80))
    dispatch_key: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer)
    exclusively_owned: Mapped[bool] = mapped_column(Boolean)
    source_id: Mapped[str | None] = mapped_column(String(36))
    translation_id: Mapped[str | None] = mapped_column(String(36))
    synthesis_id: Mapped[str | None] = mapped_column(String(36))
    qc_id: Mapped[str | None] = mapped_column(String(36))
    fit_id: Mapped[str | None] = mapped_column(String(36))
    delivery_id: Mapped[str | None] = mapped_column(String(36))

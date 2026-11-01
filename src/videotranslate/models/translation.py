"""Target command proofs and independently recoverable translation phases."""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


class TranslationCommand(Owned, Base):
    __tablename__ = "translation_commands"
    __table_args__ = owner_constraints("translation_command") + (
        owned_fk("track_id", "language_tracks", "fk_translation_command_track"),
        owned_fk("selection_id", "source_selections", "fk_translation_command_selection"),
        owned_fk("transcript_id", "transcript_revisions", "fk_translation_command_transcript"),
        UniqueConstraint("project_id", "signature", name="uq_translation_command_signature"),
        ForeignKeyConstraint(
            ["generated_context_id", "track_id", "project_id", "workspace_id"],
            [
                "context_revisions.id",
                "context_revisions.track_id",
                "context_revisions.project_id",
                "context_revisions.workspace_id",
            ],
            name="fk_translation_command_generated_context",
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    selection_id: Mapped[str] = mapped_column(String(36))
    transcript_id: Mapped[str] = mapped_column(String(36))
    signature: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON)
    row_heads: Mapped[dict] = mapped_column(JSON)
    continuation_stopped: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    generated_context_id: Mapped[str | None] = mapped_column(String(36))


class TranslationPhase(Owned, Base):
    __tablename__ = "translation_phases"
    __table_args__ = owner_constraints("translation_phase") + (
        owned_fk("command_id", "translation_commands", "fk_translation_phase_command"),
        owned_fk("run_id", "stage_runs", "fk_translation_phase_run"),
        owned_fk("parent_phase_id", "translation_phases", "fk_translation_phase_parent"),
        UniqueConstraint("run_id", name="uq_translation_phase_run"),
        UniqueConstraint("command_id", "batch_index", "phase", name="uq_translation_phase_batch"),
        CheckConstraint(
            "batch_index >= 0 AND phase IN ('context','draft','critique','rewrite','shorten')",
            name="ck_translation_phase",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    parent_phase_id: Mapped[str | None] = mapped_column(String(36))
    batch_index: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(20))
    input_payload: Mapped[dict] = mapped_column(JSON)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    dependency_snapshot: Mapped[dict] = mapped_column(JSON)
    guard_snapshot: Mapped[dict] = mapped_column(JSON)
    publication: Mapped[dict] = mapped_column(JSON, default=dict)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)

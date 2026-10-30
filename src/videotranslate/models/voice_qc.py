"""Owned immutable independent recognition, captured comparisons and listening history."""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints
from .synthesis import cell_fk, cell_unique


class VoiceQCCommand(Owned, Base):
    __tablename__ = "voice_qc_commands"
    __table_args__ = owner_constraints("voice_qc_command") + (
        owned_fk("track_id", "language_tracks", "fk_voice_qc_command_track"),
        UniqueConstraint("project_id", "signature", name="uq_voice_qc_command_signature"),
        CheckConstraint("admission_sequence >= 0", name="ck_voice_qc_admission"),
        UniqueConstraint(
            "id", "track_id", "project_id", "workspace_id", name="uq_voice_qc_command_track"
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    signature: Mapped[str] = mapped_column(String(64))
    admission_sequence: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))


class VoiceQCLine(Owned, Base):
    __tablename__ = "voice_qc_lines"
    __table_args__ = owner_constraints("voice_qc_line") + (
        ForeignKeyConstraint(
            ["command_id", "track_id", "project_id", "workspace_id"],
            ["voice_qc_commands." + k for k in ("id", "track_id", "project_id", "workspace_id")],
            name="fk_voice_qc_line_command",
        ),
        owned_fk("segment_id", "segments", "fk_voice_qc_line_segment"),
        owned_fk("run_id", "stage_runs", "fk_voice_qc_line_run"),
        cell_fk("output_id", "natural_outputs", "fk_voice_qc_line_output"),
        cell_fk("translation_revision_id", "translation_revisions", "fk_voice_qc_line_translation"),
        owned_fk("source_selection_id", "source_selections", "fk_voice_qc_line_source"),
        owned_fk("transcript_id", "transcript_revisions", "fk_voice_qc_line_transcript"),
        UniqueConstraint("run_id", name="uq_voice_qc_line_run"),
        UniqueConstraint("command_id", "segment_id", name="uq_voice_qc_line_command_cell"),
        cell_unique("uq_voice_qc_line_cell"),
    )
    command_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    output_id: Mapped[str] = mapped_column(String(36))
    translation_revision_id: Mapped[str] = mapped_column(String(36))
    source_selection_id: Mapped[str] = mapped_column(String(36))
    transcript_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    recognition_identity: Mapped[str] = mapped_column(String(64), index=True)
    recognition_input: Mapped[dict] = mapped_column(JSON)
    comparison_input: Mapped[dict] = mapped_column(JSON)
    guard_snapshot: Mapped[dict] = mapped_column(JSON)
    publication: Mapped[dict] = mapped_column(JSON, default=dict)


class VoiceQCResult(Owned, Base):
    __tablename__ = "voice_qc_results"
    __table_args__ = owner_constraints("voice_qc_result") + (
        cell_fk("line_id", "voice_qc_lines", "fk_voice_qc_result_line"),
        owned_fk("operation_id", "private_operations", "fk_voice_qc_result_operation"),
        UniqueConstraint("line_id", name="uq_voice_qc_result_line"),
        cell_unique("uq_voice_qc_result_cell"),
    )
    line_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    operation_id: Mapped[str] = mapped_column(String(36))
    recognition_identity: Mapped[str] = mapped_column(String(64), index=True)
    recognition: Mapped[dict] = mapped_column(JSON)
    comparison: Mapped[dict] = mapped_column(JSON)


class AudioReview(Owned, Base):
    __tablename__ = "audio_reviews"
    __table_args__ = owner_constraints("audio_review") + (
        cell_fk("output_id", "natural_outputs", "fk_audio_review_output"),
        cell_fk("translation_revision_id", "translation_revisions", "fk_audio_review_translation"),
        owned_fk("segment_id", "segments", "fk_audio_review_segment"),
        owned_fk("track_id", "language_tracks", "fk_audio_review_track"),
        owned_fk("source_selection_id", "source_selections", "fk_audio_review_source"),
        owned_fk("transcript_id", "transcript_revisions", "fk_audio_review_transcript"),
        UniqueConstraint("track_id", "segment_id", "revision", name="uq_audio_review_revision"),
        CheckConstraint(
            "revision > 0 AND decision IN ('accepted','rejected')", name="ck_audio_review_decision"
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    output_id: Mapped[str] = mapped_column(String(36))
    translation_revision_id: Mapped[str] = mapped_column(String(36))
    source_selection_id: Mapped[str] = mapped_column(String(36))
    transcript_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))
    decision: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text)
    qc_evidence_fingerprint: Mapped[str] = mapped_column(String(64))
    qc_acknowledgement: Mapped[dict] = mapped_column(JSON)
    guard_snapshot: Mapped[dict] = mapped_column(JSON)

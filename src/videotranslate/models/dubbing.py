"""Owned dubbing records: mutable pointers, immutable source and edit history."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import UTCDateTime, new_id, utcnow


def owner_constraints(table):
    return (
        UniqueConstraint("id", "project_id", "workspace_id", name=f"uq_{table}_owner"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name=f"fk_{table}_project",
        ),
    )


def owned_fk(column, table, name):
    return ForeignKeyConstraint(
        [column, "project_id", "workspace_id"],
        [f"{table}.id", f"{table}.project_id", f"{table}.workspace_id"],
        name=name,
    )


class Owned:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SourceTrack(Owned, Base):
    __tablename__ = "source_tracks"
    __table_args__ = owner_constraints("source_track") + (
        owned_fk("source_asset_id", "assets", "fk_source_track_asset"),
        owned_fk("probe_run_id", "stage_runs", "fk_source_track_probe"),
        CheckConstraint(
            "audio_ordinal >= 0 AND stream_index >= 0 AND duration_ms > 0 AND channels >= 0 AND sample_rate >= 0",
            name="ck_source_track_facts",
        ),
    )
    source_asset_id: Mapped[str] = mapped_column(String(36))
    probe_run_id: Mapped[str] = mapped_column(String(36))
    audio_ordinal: Mapped[int] = mapped_column(Integer)
    stream_index: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(40))
    channels: Mapped[int] = mapped_column(Integer)
    sample_rate: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)


class SourceSelection(Owned, Base):
    __tablename__ = "source_selections"
    __table_args__ = owner_constraints("source_selection") + (
        owned_fk("track_id", "source_tracks", "fk_selection_track"),
        UniqueConstraint("project_id", "revision", name="uq_selection_revision"),
        CheckConstraint(
            "revision > 0 AND start_ms >= 0 AND end_ms > start_ms", name="ck_selection_window"
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))


class TranscriptRevision(Owned, Base):
    __tablename__ = "transcript_revisions"
    __table_args__ = owner_constraints("transcript") + (
        owned_fk("selection_id", "source_selections", "fk_transcript_selection"),
        owned_fk("parent_revision_id", "transcript_revisions", "fk_transcript_parent"),
        owned_fk("run_id", "stage_runs", "fk_transcript_run"),
    )
    selection_id: Mapped[str] = mapped_column(String(36))
    parent_revision_id: Mapped[str | None] = mapped_column(String(36))
    provenance: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    provider: Mapped[str | None] = mapped_column(String(80))
    detected_language: Mapped[str | None] = mapped_column(String(40))
    original_segments: Mapped[list] = mapped_column(JSON, default=list)


class SourceState(Owned, Base):
    __tablename__ = "source_states"
    __table_args__ = owner_constraints("source_state") + (
        UniqueConstraint("project_id", name="uq_source_state_project"),
        owned_fk("selection_id", "source_selections", "fk_source_state_selection"),
        owned_fk("transcript_id", "transcript_revisions", "fk_source_state_transcript"),
    )
    selection_id: Mapped[str] = mapped_column(String(36))
    transcript_id: Mapped[str | None] = mapped_column(String(36))


class Speaker(Owned, Base):
    __tablename__ = "speakers"
    __table_args__ = owner_constraints("speaker") + (
        owned_fk("merged_into_id", "speakers", "fk_speaker_merge"),
        owned_fk("selection_id", "source_selections", "fk_speaker_selection"),
    )
    selection_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_id: Mapped[str | None] = mapped_column(String(36))


class SpeakerRevision(Owned, Base):
    __tablename__ = "speaker_revisions"
    __table_args__ = owner_constraints("speaker_revision") + (
        owned_fk("speaker_id", "speakers", "fk_speaker_revision_speaker"),
        owned_fk("merged_into_id", "speakers", "fk_speaker_revision_merged_into"),
        UniqueConstraint("speaker_id", "revision", name="uq_speaker_revision"),
    )
    speaker_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000))
    archived: Mapped[bool] = mapped_column(Boolean)
    merged_into_id: Mapped[str | None] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))


class Segment(Owned, Base):
    __tablename__ = "segments"
    __table_args__ = owner_constraints("segment") + (
        owned_fk("transcript_id", "transcript_revisions", "fk_segment_transcript"),
        ForeignKeyConstraint(
            ["current_revision_id", "id", "project_id", "workspace_id"],
            [
                "segment_revisions.id",
                "segment_revisions.segment_id",
                "segment_revisions.project_id",
                "segment_revisions.workspace_id",
            ],
            name="fk_segment_current",
            use_alter=True,
        ),
        UniqueConstraint("transcript_id", "display_index", name="uq_segment_order"),
        CheckConstraint("revision >= 0 AND display_index >= 0", name="ck_segment_revision"),
    )
    transcript_id: Mapped[str] = mapped_column(String(36))
    display_index: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text)
    original_speaker_label: Mapped[str | None] = mapped_column(String(100))
    source_analysis_flags: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class SegmentRevision(Owned, Base):
    __tablename__ = "segment_revisions"
    __table_args__ = owner_constraints("segment_revision") + (
        owned_fk("segment_id", "segments", "fk_segment_revision_segment"),
        owned_fk("speaker_id", "speakers", "fk_segment_revision_speaker"),
        ForeignKeyConstraint(
            ["parent_revision_id", "segment_id", "project_id", "workspace_id"],
            [
                "segment_revisions.id",
                "segment_revisions.segment_id",
                "segment_revisions.project_id",
                "segment_revisions.workspace_id",
            ],
            name="fk_segment_revision_parent",
        ),
        UniqueConstraint(
            "id", "segment_id", "project_id", "workspace_id", name="uq_segment_revision_cell"
        ),
        CheckConstraint("start_ms >= 0 AND end_ms > start_ms", name="ck_segment_revision_timing"),
    )
    segment_id: Mapped[str] = mapped_column(String(36))
    parent_revision_id: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str | None] = mapped_column(String(36))
    provenance: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str] = mapped_column(String(36))


class SegmentParent(Owned, Base):
    __tablename__ = "segment_parents"
    __table_args__ = owner_constraints("segment_parent") + (
        owned_fk("segment_id", "segments", "fk_segment_parent_child"),
        owned_fk("parent_segment_id", "segments", "fk_segment_parent_parent"),
        UniqueConstraint("segment_id", "parent_segment_id", name="uq_segment_parent"),
    )
    segment_id: Mapped[str] = mapped_column(String(36))
    parent_segment_id: Mapped[str] = mapped_column(String(36))


class LanguageTrack(Owned, Base):
    __tablename__ = "language_tracks"
    __table_args__ = owner_constraints("language_track") + (
        UniqueConstraint("project_id", "tag", name="uq_language_track_tag"),
        ForeignKeyConstraint(
            ["context_revision_id", "id", "project_id", "workspace_id"],
            [
                "context_revisions.id",
                "context_revisions.track_id",
                "context_revisions.project_id",
                "context_revisions.workspace_id",
            ],
            name="fk_track_context",
            use_alter=True,
        ),
        CheckConstraint(
            "mode IN ('Fast','Cinematic','Autofit') AND revision > 0", name="ck_track_mode"
        ),
    )
    tag: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(20), default="Fast")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    context_revision_id: Mapped[str | None] = mapped_column(String(36))


class ContextRevision(Owned, Base):
    __tablename__ = "context_revisions"
    __table_args__ = owner_constraints("context_revision") + (
        owned_fk("track_id", "language_tracks", "fk_context_track"),
        UniqueConstraint("id", "track_id", "project_id", "workspace_id", name="uq_context_track"),
        ForeignKeyConstraint(
            ["parent_revision_id", "track_id", "project_id", "workspace_id"],
            [
                "context_revisions.id",
                "context_revisions.track_id",
                "context_revisions.project_id",
                "context_revisions.workspace_id",
            ],
            name="fk_context_parent",
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    parent_revision_id: Mapped[str | None] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(Text, default="")
    glossary: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[str] = mapped_column(String(30), default="supplied")
    actor_id: Mapped[str] = mapped_column(String(36))


class TranslationRevision(Owned, Base):
    __tablename__ = "translation_revisions"
    __table_args__ = owner_constraints("translation_revision") + (
        owned_fk("segment_id", "segments", "fk_translation_segment"),
        owned_fk("track_id", "language_tracks", "fk_translation_track"),
        ForeignKeyConstraint(
            ["context_revision_id", "track_id", "project_id", "workspace_id"],
            [
                "context_revisions.id",
                "context_revisions.track_id",
                "context_revisions.project_id",
                "context_revisions.workspace_id",
            ],
            name="fk_translation_context",
        ),
        UniqueConstraint(
            "id",
            "segment_id",
            "track_id",
            "project_id",
            "workspace_id",
            name="uq_translation_revision_cell",
        ),
        ForeignKeyConstraint(
            ["parent_revision_id", "segment_id", "track_id", "project_id", "workspace_id"],
            [
                "translation_revisions.id",
                "translation_revisions.segment_id",
                "translation_revisions.track_id",
                "translation_revisions.project_id",
                "translation_revisions.workspace_id",
            ],
            name="fk_translation_parent",
        ),
    )
    segment_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    context_revision_id: Mapped[str] = mapped_column(String(36))
    parent_revision_id: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(Text)
    source_text_fingerprint: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(20))
    provenance: Mapped[str] = mapped_column(String(30))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    actor_id: Mapped[str] = mapped_column(String(36))


class TranslationState(Owned, Base):
    __tablename__ = "translation_states"
    __table_args__ = owner_constraints("translation_state") + (
        owned_fk("segment_id", "segments", "fk_translation_state_segment"),
        owned_fk("track_id", "language_tracks", "fk_translation_state_track"),
        UniqueConstraint("segment_id", "track_id", name="uq_translation_state_cell"),
        ForeignKeyConstraint(
            ["current_revision_id", "segment_id", "track_id", "project_id", "workspace_id"],
            [
                "translation_revisions.id",
                "translation_revisions.segment_id",
                "translation_revisions.track_id",
                "translation_revisions.project_id",
                "translation_revisions.workspace_id",
            ],
            name="fk_translation_state_current",
        ),
        CheckConstraint("revision > 0", name="ck_translation_state_revision"),
    )
    segment_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    current_revision_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)

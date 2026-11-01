"""Owned immutable natural inference, controls and explicit audio selections."""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


def cell_fk(column, table, name):
    return ForeignKeyConstraint(
        [column, "track_id", "segment_id", "project_id", "workspace_id"],
        [
            f"{table}.{key}"
            for key in ("id", "track_id", "segment_id", "project_id", "workspace_id")
        ],
        name=name,
    )


def cell_unique(name):
    return UniqueConstraint("id", "track_id", "segment_id", "project_id", "workspace_id", name=name)


class VoiceSettings(Owned, Base):
    __tablename__ = "voice_settings"
    __table_args__ = owner_constraints("voice_settings") + (
        owned_fk("track_id", "language_tracks", "fk_voice_settings_track"),
        owned_fk("segment_id", "segments", "fk_voice_settings_segment"),
        UniqueConstraint("track_id", "scope_key", name="uq_voice_settings_scope"),
        UniqueConstraint(
            "id", "track_id", "project_id", "workspace_id", name="uq_voice_settings_track"
        ),
        ForeignKeyConstraint(
            ["current_version_id", "id", "track_id", "project_id", "workspace_id"],
            [
                "voice_settings_versions.id",
                "voice_settings_versions.settings_id",
                "voice_settings_versions.track_id",
                "voice_settings_versions.project_id",
                "voice_settings_versions.workspace_id",
            ],
            name="fk_voice_settings_current",
            use_alter=True,
        ),
        CheckConstraint("revision >= 0", name="ck_voice_settings_revision"),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str | None] = mapped_column(String(36))
    scope_key: Mapped[str] = mapped_column(String(50))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    current_version_id: Mapped[str | None] = mapped_column(String(36))


class VoiceSettingsVersion(Owned, Base):
    __tablename__ = "voice_settings_versions"
    __table_args__ = owner_constraints("voice_settings_version") + (
        ForeignKeyConstraint(
            ["settings_id", "track_id", "project_id", "workspace_id"],
            [
                "voice_settings.id",
                "voice_settings.track_id",
                "voice_settings.project_id",
                "voice_settings.workspace_id",
            ],
            name="fk_voice_settings_version_root",
        ),
        UniqueConstraint(
            "id",
            "settings_id",
            "track_id",
            "project_id",
            "workspace_id",
            name="uq_voice_settings_version_root",
        ),
        ForeignKeyConstraint(
            ["parent_version_id", "settings_id", "track_id", "project_id", "workspace_id"],
            [
                "voice_settings_versions.id",
                "voice_settings_versions.settings_id",
                "voice_settings_versions.track_id",
                "voice_settings_versions.project_id",
                "voice_settings_versions.workspace_id",
            ],
            name="fk_voice_settings_version_parent",
        ),
        UniqueConstraint("settings_id", "revision", name="uq_voice_settings_version_revision"),
        CheckConstraint(
            "revision > 0 AND ns BETWEEN 4 AND 64 AND gs BETWEEN 0 AND 4 AND sp BETWEEN 0.5 AND 1.5 AND (du IS NULL OR du BETWEEN 0.01 AND 10000)",
            name="ck_voice_settings_controls",
        ),
    )
    settings_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    override: Mapped[bool] = mapped_column(Boolean)
    ns: Mapped[int] = mapped_column(Integer)
    gs: Mapped[float] = mapped_column(Float)
    dn: Mapped[bool] = mapped_column(Boolean)
    sp: Mapped[float] = mapped_column(Float)
    du: Mapped[float | None] = mapped_column(Float)
    pp: Mapped[bool] = mapped_column(Boolean)
    po: Mapped[bool] = mapped_column(Boolean)
    actor_id: Mapped[str] = mapped_column(String(36))


class SynthesisCommand(Owned, Base):
    __tablename__ = "synthesis_commands"
    __table_args__ = owner_constraints("synthesis_command") + (
        owned_fk("track_id", "language_tracks", "fk_synthesis_command_track"),
        owned_fk("source_selection_id", "source_selections", "fk_synthesis_command_selection"),
        owned_fk("transcript_id", "transcript_revisions", "fk_synthesis_command_transcript"),
        UniqueConstraint("project_id", "signature", name="uq_synthesis_command_signature"),
        UniqueConstraint(
            "id", "track_id", "project_id", "workspace_id", name="uq_synthesis_command_track"
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    source_selection_id: Mapped[str] = mapped_column(String(36))
    transcript_id: Mapped[str] = mapped_column(String(36))
    selection_revision: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(36))
    replace_selected: Mapped[bool] = mapped_column(Boolean)
    regenerate: Mapped[bool] = mapped_column(Boolean)


class SynthesisLine(Owned, Base):
    __tablename__ = "synthesis_lines"
    __table_args__ = owner_constraints("synthesis_line") + (
        ForeignKeyConstraint(
            ["command_id", "track_id", "project_id", "workspace_id"],
            [
                "synthesis_commands.id",
                "synthesis_commands.track_id",
                "synthesis_commands.project_id",
                "synthesis_commands.workspace_id",
            ],
            name="fk_synthesis_line_command",
        ),
        owned_fk("segment_id", "segments", "fk_synthesis_line_segment"),
        owned_fk("run_id", "stage_runs", "fk_synthesis_line_run"),
        cell_fk(
            "translation_revision_id", "translation_revisions", "fk_synthesis_line_translation"
        ),
        owned_fk("reference_version_id", "reference_versions", "fk_synthesis_line_reference"),
        owned_fk("binding_version_id", "voice_binding_versions", "fk_synthesis_line_binding"),
        owned_fk(
            "review_reference_version_id",
            "reference_versions",
            "fk_synthesis_line_review_reference",
        ),
        owned_fk("authorization_checkpoint_id", "pipeline_checkpoints", "fk_synthesis_line_authorization"),
        UniqueConstraint("run_id", name="uq_synthesis_line_run"),
        UniqueConstraint("command_id", "segment_id", name="uq_synthesis_line_command_cell"),
        cell_unique("uq_synthesis_line_cell"),
    )
    command_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    translation_revision_id: Mapped[str] = mapped_column(String(36))
    reference_version_id: Mapped[str] = mapped_column(String(36))
    binding_version_id: Mapped[str] = mapped_column(String(36))
    input_payload: Mapped[dict] = mapped_column(JSON)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    guard_snapshot: Mapped[dict] = mapped_column(JSON)
    authorization_checkpoint_id: Mapped[str | None] = mapped_column(String(36))
    review_translation_revision: Mapped[int | None] = mapped_column(Integer)
    review_reference_version_id: Mapped[str | None] = mapped_column(String(36))
    publication: Mapped[dict] = mapped_column(JSON, default=dict)


class NaturalOutput(Owned, Base):
    __tablename__ = "natural_outputs"
    __table_args__ = owner_constraints("natural_output") + (
        cell_fk("line_id", "synthesis_lines", "fk_natural_output_line"),
        owned_fk("audio_asset_id", "assets", "fk_natural_output_asset"),
        owned_fk("operation_id", "private_operations", "fk_natural_output_operation"),
        UniqueConstraint("line_id", name="uq_natural_output_line"),
        cell_unique("uq_natural_output_cell"),
        CheckConstraint(
            "duration_ms > 0 AND byte_size > 0 AND sample_rate BETWEEN 8000 AND 192000 AND channels BETWEEN 1 AND 8",
            name="ck_natural_output_measurement",
        ),
    )
    line_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    audio_asset_id: Mapped[str] = mapped_column(String(36))
    operation_id: Mapped[str] = mapped_column(String(36))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer)
    sample_rate: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)
    container: Mapped[str] = mapped_column(String(40))
    codec: Mapped[str] = mapped_column(String(40))
    measurement: Mapped[str] = mapped_column(String(60))


class AudioSelection(Owned, Base):
    __tablename__ = "audio_selections"
    __table_args__ = owner_constraints("audio_selection") + (
        owned_fk("track_id", "language_tracks", "fk_audio_selection_track"),
        owned_fk("segment_id", "segments", "fk_audio_selection_segment"),
        UniqueConstraint("track_id", "segment_id", name="uq_audio_selection_cell"),
        cell_unique("uq_audio_selection_identity"),
        ForeignKeyConstraint(
            ["current_version_id", "id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "audio_selection_versions.id",
                "audio_selection_versions.selection_id",
                "audio_selection_versions.track_id",
                "audio_selection_versions.segment_id",
                "audio_selection_versions.project_id",
                "audio_selection_versions.workspace_id",
            ],
            name="fk_audio_selection_current",
            use_alter=True,
        ),
    )
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    current_version_id: Mapped[str | None] = mapped_column(String(36))


class AudioSelectionVersion(Owned, Base):
    __tablename__ = "audio_selection_versions"
    __table_args__ = owner_constraints("audio_selection_version") + (
        cell_fk("selection_id", "audio_selections", "fk_audio_selection_version_root"),
        cell_fk("output_id", "natural_outputs", "fk_audio_selection_version_output"),
        UniqueConstraint(
            "id",
            "selection_id",
            "track_id",
            "segment_id",
            "project_id",
            "workspace_id",
            name="uq_audio_selection_version_root",
        ),
        ForeignKeyConstraint(
            [
                "parent_version_id",
                "selection_id",
                "track_id",
                "segment_id",
                "project_id",
                "workspace_id",
            ],
            [
                "audio_selection_versions.id",
                "audio_selection_versions.selection_id",
                "audio_selection_versions.track_id",
                "audio_selection_versions.segment_id",
                "audio_selection_versions.project_id",
                "audio_selection_versions.workspace_id",
            ],
            name="fk_audio_selection_version_parent",
        ),
        UniqueConstraint("selection_id", "revision", name="uq_audio_selection_version_revision"),
        CheckConstraint(
            "revision > 0 AND provenance IN ('generated','replacement','manual')",
            name="ck_audio_selection_version",
        ),
    )
    selection_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    output_id: Mapped[str] = mapped_column(String(36))
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))
    provenance: Mapped[str] = mapped_column(String(20))

"""Owned versioned fit settings and immutable CPU plan lineage."""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


def settings_family(column, name, *, alter=False):
    return ForeignKeyConstraint(
        [column, "settings_id", "project_id", "workspace_id"],
        ["fit_settings_versions." + k for k in ("id", "settings_id", "project_id", "workspace_id")],
        name=name,
        use_alter=alter,
    )


class FitSettingsState(Owned, Base):
    __tablename__ = "fit_settings_states"
    __table_args__ = owner_constraints("fit_settings_state") + (
        UniqueConstraint("project_id", name="uq_fit_settings_project"),
        ForeignKeyConstraint(
            ["current_version_id", "id", "project_id", "workspace_id"],
            [
                "fit_settings_versions." + k
                for k in ("id", "settings_id", "project_id", "workspace_id")
            ],
            name="fk_fit_settings_current",
            use_alter=True,
        ),
        CheckConstraint("revision >= 0", name="ck_fit_settings_revision"),
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    current_version_id: Mapped[str | None] = mapped_column(String(36))


class FitSettingsVersion(Owned, Base):
    __tablename__ = "fit_settings_versions"
    __table_args__ = owner_constraints("fit_settings_version") + (
        owned_fk("settings_id", "fit_settings_states", "fk_fit_settings_version_root"),
        UniqueConstraint(
            "id", "settings_id", "project_id", "workspace_id", name="uq_fit_settings_version_family"
        ),
        settings_family("parent_version_id", "fk_fit_settings_version_parent"),
        UniqueConstraint("settings_id", "revision", name="uq_fit_settings_version_revision"),
        CheckConstraint(
            "revision > 0 AND policy = 'shared_fit_v1'", name="ck_fit_settings_version"
        ),
    )
    settings_id: Mapped[str] = mapped_column(String(36))
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSON)
    policy: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(36))


class FitPlanCommand(Owned, Base):
    __tablename__ = "fit_plan_commands"
    __table_args__ = owner_constraints("fit_plan_command") + (
        owned_fk("source_asset_id", "assets", "fk_fit_command_asset"),
        owned_fk("source_selection_id", "source_selections", "fk_fit_command_source"),
        owned_fk("transcript_id", "transcript_revisions", "fk_fit_command_transcript"),
        owned_fk("run_id", "stage_runs", "fk_fit_command_run"),
        owned_fk("settings_version_id", "fit_settings_versions", "fk_fit_command_settings"),
        UniqueConstraint("project_id", "signature", name="uq_fit_command_signature"),
        UniqueConstraint("run_id", name="uq_fit_command_run"),
        UniqueConstraint(
            "id", "run_id", "project_id", "workspace_id", name="uq_fit_command_run_family"
        ),
        CheckConstraint(
            "purpose IN ('dub','incomplete_preview','original_only') AND admission_sequence >= 0 AND line_count BETWEEN 0 AND 1000",
            name="ck_fit_command",
        ),
    )
    source_asset_id: Mapped[str] = mapped_column(String(36))
    source_selection_id: Mapped[str] = mapped_column(String(36))
    transcript_id: Mapped[str | None] = mapped_column(String(36))
    settings_version_id: Mapped[str | None] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    signature: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(36))
    purpose: Mapped[str] = mapped_column(String(24))
    admission_sequence: Mapped[int] = mapped_column(Integer)
    line_count: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)


class FitPlanLine(Owned, Base):
    __tablename__ = "fit_plan_lines"
    __table_args__ = owner_constraints("fit_plan_line") + (
        owned_fk("command_id", "fit_plan_commands", "fk_fit_line_command"),
        owned_fk("track_id", "language_tracks", "fk_fit_line_track"),
        owned_fk("segment_id", "segments", "fk_fit_line_segment"),
        ForeignKeyConstraint(
            ["source_revision_id", "segment_id", "project_id", "workspace_id"],
            ["segment_revisions." + k for k in ("id", "segment_id", "project_id", "workspace_id")],
            name="fk_fit_line_source_revision",
        ),
        ForeignKeyConstraint(
            ["translation_revision_id", "segment_id", "track_id", "project_id", "workspace_id"],
            [
                "translation_revisions." + k
                for k in ("id", "segment_id", "track_id", "project_id", "workspace_id")
            ],
            name="fk_fit_line_translation",
        ),
        ForeignKeyConstraint(
            ["audio_selection_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "audio_selections." + k
                for k in ("id", "track_id", "segment_id", "project_id", "workspace_id")
            ],
            name="fk_fit_line_audio_root",
        ),
        ForeignKeyConstraint(
            [
                "audio_version_id",
                "audio_selection_id",
                "track_id",
                "segment_id",
                "project_id",
                "workspace_id",
            ],
            [
                "audio_selection_versions." + k
                for k in (
                    "id",
                    "selection_id",
                    "track_id",
                    "segment_id",
                    "project_id",
                    "workspace_id",
                )
            ],
            name="fk_fit_line_audio_version",
        ),
        ForeignKeyConstraint(
            ["output_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "natural_outputs." + k
                for k in ("id", "track_id", "segment_id", "project_id", "workspace_id")
            ],
            name="fk_fit_line_output",
        ),
        UniqueConstraint("command_id", "track_id", "segment_id", name="uq_fit_line_cell"),
    )
    command_id: Mapped[str] = mapped_column(String(36))
    track_id: Mapped[str] = mapped_column(String(36))
    segment_id: Mapped[str] = mapped_column(String(36))
    source_revision_id: Mapped[str] = mapped_column(String(36))
    translation_revision_id: Mapped[str | None] = mapped_column(String(36))
    audio_selection_id: Mapped[str | None] = mapped_column(String(36))
    audio_version_id: Mapped[str | None] = mapped_column(String(36))
    output_id: Mapped[str | None] = mapped_column(String(36))
    included: Mapped[bool] = mapped_column(Boolean)
    snapshot: Mapped[dict] = mapped_column(JSON)


class FitPlanResult(Owned, Base):
    __tablename__ = "fit_plan_results"
    __table_args__ = owner_constraints("fit_plan_result") + (
        ForeignKeyConstraint(
            ["command_id", "run_id", "project_id", "workspace_id"],
            ["fit_plan_commands." + k for k in ("id", "run_id", "project_id", "workspace_id")],
            name="fk_fit_result_command",
        ),
        owned_fk("run_id", "stage_runs", "fk_fit_result_run"),
        owned_fk("operation_id", "private_operations", "fk_fit_result_operation"),
        UniqueConstraint("command_id", name="uq_fit_result_command"),
    )
    command_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    operation_id: Mapped[str] = mapped_column(String(36))
    payload_fingerprint: Mapped[str] = mapped_column(String(64))
    timeline_feasible: Mapped[bool] = mapped_column(Boolean)
    planned_output_duration: Mapped[dict] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON)
    plan: Mapped[dict] = mapped_column(JSON)

"""Frozen additive owned fit settings, command capture and CPU plan results."""

import sqlalchemy as sa

from alembic import op

revision = "0011_fit_plans"
down_revision = "0010_voice_qc"
branch_labels = None
depends_on = None


def upgrade():

    op.create_table(
        "fit_settings_states",
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_fit_settings_revision"),
        sa.ForeignKeyConstraint(
            ["current_version_id", "id", "project_id", "workspace_id"],
            [
                "fit_settings_versions.id",
                "fit_settings_versions.settings_id",
                "fit_settings_versions.project_id",
                "fit_settings_versions.workspace_id",
            ],
            name="fk_fit_settings_current",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_fit_settings_state_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_fit_settings_state_owner"),
        sa.UniqueConstraint("project_id", name="uq_fit_settings_project"),
    )
    op.create_index(
        op.f("ix_fit_settings_states_project_id"),
        "fit_settings_states",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "fit_settings_versions",
        sa.Column("settings_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("policy", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision > 0 AND policy = 'shared_fit_v1'", name="ck_fit_settings_version"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id", "settings_id", "project_id", "workspace_id"],
            [
                "fit_settings_versions.id",
                "fit_settings_versions.settings_id",
                "fit_settings_versions.project_id",
                "fit_settings_versions.workspace_id",
            ],
            name="fk_fit_settings_version_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_fit_settings_version_project",
        ),
        sa.ForeignKeyConstraint(
            ["settings_id", "project_id", "workspace_id"],
            [
                "fit_settings_states.id",
                "fit_settings_states.project_id",
                "fit_settings_states.workspace_id",
            ],
            name="fk_fit_settings_version_root",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", "workspace_id", name="uq_fit_settings_version_owner"
        ),
        sa.UniqueConstraint(
            "id", "settings_id", "project_id", "workspace_id", name="uq_fit_settings_version_family"
        ),
        sa.UniqueConstraint("settings_id", "revision", name="uq_fit_settings_version_revision"),
    )
    op.create_index(
        op.f("ix_fit_settings_versions_project_id"),
        "fit_settings_versions",
        ["project_id"],
        unique=False,
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_fit_settings_current",
            "fit_settings_states",
            "fit_settings_versions",
            ["current_version_id", "id", "project_id", "workspace_id"],
            ["id", "settings_id", "project_id", "workspace_id"],
        )
    op.create_table(
        "fit_plan_commands",
        sa.Column("source_asset_id", sa.String(length=36), nullable=False),
        sa.Column("source_selection_id", sa.String(length=36), nullable=False),
        sa.Column("transcript_id", sa.String(length=36), nullable=True),
        sa.Column("settings_version_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("admission_sequence", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('dub','incomplete_preview','original_only') AND admission_sequence >= 0 AND line_count BETWEEN 0 AND 1000",
            name="ck_fit_command",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_fit_plan_command_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_fit_command_run",
        ),
        sa.ForeignKeyConstraint(
            ["settings_version_id", "project_id", "workspace_id"],
            [
                "fit_settings_versions.id",
                "fit_settings_versions.project_id",
                "fit_settings_versions.workspace_id",
            ],
            name="fk_fit_command_settings",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_fit_command_asset",
        ),
        sa.ForeignKeyConstraint(
            ["source_selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_fit_command_source",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_fit_command_transcript",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_fit_plan_command_owner"),
        sa.UniqueConstraint("project_id", "signature", name="uq_fit_command_signature"),
        sa.UniqueConstraint("run_id", name="uq_fit_command_run"),
        sa.UniqueConstraint(
            "id", "run_id", "project_id", "workspace_id", name="uq_fit_command_run_family"
        ),
    )
    op.create_index(
        op.f("ix_fit_plan_commands_project_id"), "fit_plan_commands", ["project_id"], unique=False
    )
    op.create_table(
        "fit_plan_results",
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("timeline_feasible", sa.Boolean(), nullable=False),
        sa.Column("planned_output_duration", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["command_id", "run_id", "project_id", "workspace_id"],
            [
                "fit_plan_commands.id",
                "fit_plan_commands.run_id",
                "fit_plan_commands.project_id",
                "fit_plan_commands.workspace_id",
            ],
            name="fk_fit_result_command",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "project_id", "workspace_id"],
            [
                "private_operations.id",
                "private_operations.project_id",
                "private_operations.workspace_id",
            ],
            name="fk_fit_result_operation",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_fit_plan_result_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_fit_result_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id", name="uq_fit_result_command"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_fit_plan_result_owner"),
    )
    op.create_index(
        op.f("ix_fit_plan_results_project_id"), "fit_plan_results", ["project_id"], unique=False
    )
    op.create_table(
        "fit_plan_lines",
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision_id", sa.String(length=36), nullable=False),
        sa.Column("translation_revision_id", sa.String(length=36), nullable=True),
        sa.Column("audio_selection_id", sa.String(length=36), nullable=True),
        sa.Column("audio_version_id", sa.String(length=36), nullable=True),
        sa.Column("output_id", sa.String(length=36), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["audio_selection_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "audio_selections.id",
                "audio_selections.track_id",
                "audio_selections.segment_id",
                "audio_selections.project_id",
                "audio_selections.workspace_id",
            ],
            name="fk_fit_line_audio_root",
        ),
        sa.ForeignKeyConstraint(
            [
                "audio_version_id",
                "audio_selection_id",
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
            name="fk_fit_line_audio_version",
        ),
        sa.ForeignKeyConstraint(
            ["command_id", "project_id", "workspace_id"],
            [
                "fit_plan_commands.id",
                "fit_plan_commands.project_id",
                "fit_plan_commands.workspace_id",
            ],
            name="fk_fit_line_command",
        ),
        sa.ForeignKeyConstraint(
            ["output_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "natural_outputs.id",
                "natural_outputs.track_id",
                "natural_outputs.segment_id",
                "natural_outputs.project_id",
                "natural_outputs.workspace_id",
            ],
            name="fk_fit_line_output",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_fit_plan_line_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_fit_line_segment",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id", "segment_id", "project_id", "workspace_id"],
            [
                "segment_revisions.id",
                "segment_revisions.segment_id",
                "segment_revisions.project_id",
                "segment_revisions.workspace_id",
            ],
            name="fk_fit_line_source_revision",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_fit_line_track",
        ),
        sa.ForeignKeyConstraint(
            ["translation_revision_id", "segment_id", "track_id", "project_id", "workspace_id"],
            [
                "translation_revisions.id",
                "translation_revisions.segment_id",
                "translation_revisions.track_id",
                "translation_revisions.project_id",
                "translation_revisions.workspace_id",
            ],
            name="fk_fit_line_translation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id", "track_id", "segment_id", name="uq_fit_line_cell"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_fit_plan_line_owner"),
    )
    op.create_index(
        op.f("ix_fit_plan_lines_project_id"), "fit_plan_lines", ["project_id"], unique=False
    )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_fit_settings_current", "fit_settings_states", type_="foreignkey")

    op.drop_index(op.f("ix_fit_plan_lines_project_id"), table_name="fit_plan_lines")
    op.drop_table("fit_plan_lines")
    op.drop_index(op.f("ix_fit_plan_results_project_id"), table_name="fit_plan_results")
    op.drop_table("fit_plan_results")
    op.drop_index(op.f("ix_fit_plan_commands_project_id"), table_name="fit_plan_commands")
    op.drop_table("fit_plan_commands")
    op.drop_index(op.f("ix_fit_settings_versions_project_id"), table_name="fit_settings_versions")
    op.drop_table("fit_settings_versions")
    op.drop_index(op.f("ix_fit_settings_states_project_id"), table_name="fit_settings_states")
    op.drop_table("fit_settings_states")

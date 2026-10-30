"""Frozen additive natural synthesis, controls and audio-selection history."""

import sqlalchemy as sa

from alembic import op

revision = "0009_synthesis"
down_revision = "0008_translation_operations"
branch_labels = None
depends_on = None


def upgrade():
    sqlite = op.get_bind().dialect.name == "sqlite"
    op.create_table(
        "voice_settings",
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("scope_key", sa.String(length=50), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.CheckConstraint("revision >= 0", name="ck_voice_settings_revision"),
        *(
            [
                sa.ForeignKeyConstraint(
                    ["current_version_id", "id", "track_id", "project_id", "workspace_id"],
                    [
                        "voice_settings_versions.id",
                        "voice_settings_versions.settings_id",
                        "voice_settings_versions.track_id",
                        "voice_settings_versions.project_id",
                        "voice_settings_versions.workspace_id",
                    ],
                    name="fk_voice_settings_current",
                )
            ]
            if sqlite
            else []
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_settings_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_voice_settings_segment",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_voice_settings_track",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_voice_settings_owner"),
        sa.UniqueConstraint(*["track_id", "scope_key"], name="uq_voice_settings_scope"),
        sa.UniqueConstraint(
            *["id", "track_id", "project_id", "workspace_id"], name="uq_voice_settings_track"
        ),
    )
    op.create_index("ix_voice_settings_project_id", "voice_settings", ["project_id"])
    op.create_table(
        "voice_settings_versions",
        sa.Column("settings_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("override", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("ns", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("gs", sa.Float(), nullable=False, primary_key=False),
        sa.Column("dn", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("sp", sa.Float(), nullable=False, primary_key=False),
        sa.Column("du", sa.Float(), nullable=True, primary_key=False),
        sa.Column("pp", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("po", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.CheckConstraint(
            "revision > 0 AND ns BETWEEN 4 AND 64 AND gs BETWEEN 0 AND 4 AND sp BETWEEN 0.5 AND 1.5 AND (du IS NULL OR du BETWEEN 0.01 AND 10000)",
            name="ck_voice_settings_controls",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_settings_version_project",
        ),
        sa.ForeignKeyConstraint(
            ["settings_id", "track_id", "project_id", "workspace_id"],
            [
                "voice_settings.id",
                "voice_settings.track_id",
                "voice_settings.project_id",
                "voice_settings.workspace_id",
            ],
            name="fk_voice_settings_version_root",
        ),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_voice_settings_version_owner"
        ),
        sa.UniqueConstraint(
            *["settings_id", "revision"], name="uq_voice_settings_version_revision"
        ),
        sa.UniqueConstraint(
            *["id", "settings_id", "track_id", "project_id", "workspace_id"],
            name="uq_voice_settings_version_root",
        ),
    )
    op.create_index(
        "ix_voice_settings_versions_project_id", "voice_settings_versions", ["project_id"]
    )
    op.create_table(
        "synthesis_commands",
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("source_selection_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("transcript_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("selection_revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("signature", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("replace_selected", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("regenerate", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_synthesis_command_project",
        ),
        sa.ForeignKeyConstraint(
            ["source_selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_synthesis_command_selection",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_synthesis_command_track",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_synthesis_command_transcript",
        ),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_synthesis_command_owner"
        ),
        sa.UniqueConstraint(*["project_id", "signature"], name="uq_synthesis_command_signature"),
        sa.UniqueConstraint(
            *["id", "track_id", "project_id", "workspace_id"], name="uq_synthesis_command_track"
        ),
    )
    op.create_index("ix_synthesis_commands_project_id", "synthesis_commands", ["project_id"])
    op.create_table(
        "synthesis_lines",
        sa.Column("command_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("run_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column(
            "translation_revision_id", sa.String(length=36), nullable=False, primary_key=False
        ),
        sa.Column("reference_version_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("binding_version_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("input_payload", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("guard_snapshot", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("review_translation_revision", sa.Integer(), nullable=True, primary_key=False),
        sa.Column(
            "review_reference_version_id", sa.String(length=36), nullable=True, primary_key=False
        ),
        sa.Column("publication", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(
            ["binding_version_id", "project_id", "workspace_id"],
            [
                "voice_binding_versions.id",
                "voice_binding_versions.project_id",
                "voice_binding_versions.workspace_id",
            ],
            name="fk_synthesis_line_binding",
        ),
        sa.ForeignKeyConstraint(
            ["command_id", "track_id", "project_id", "workspace_id"],
            [
                "synthesis_commands.id",
                "synthesis_commands.track_id",
                "synthesis_commands.project_id",
                "synthesis_commands.workspace_id",
            ],
            name="fk_synthesis_line_command",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_synthesis_line_project",
        ),
        sa.ForeignKeyConstraint(
            ["reference_version_id", "project_id", "workspace_id"],
            [
                "reference_versions.id",
                "reference_versions.project_id",
                "reference_versions.workspace_id",
            ],
            name="fk_synthesis_line_reference",
        ),
        sa.ForeignKeyConstraint(
            ["review_reference_version_id", "project_id", "workspace_id"],
            [
                "reference_versions.id",
                "reference_versions.project_id",
                "reference_versions.workspace_id",
            ],
            name="fk_synthesis_line_review_reference",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_synthesis_line_run",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_synthesis_line_segment",
        ),
        sa.ForeignKeyConstraint(
            ["translation_revision_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "translation_revisions.id",
                "translation_revisions.track_id",
                "translation_revisions.segment_id",
                "translation_revisions.project_id",
                "translation_revisions.workspace_id",
            ],
            name="fk_synthesis_line_translation",
        ),
        sa.UniqueConstraint(
            *["id", "track_id", "segment_id", "project_id", "workspace_id"],
            name="uq_synthesis_line_cell",
        ),
        sa.UniqueConstraint(*["command_id", "segment_id"], name="uq_synthesis_line_command_cell"),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_synthesis_line_owner"),
        sa.UniqueConstraint(*["run_id"], name="uq_synthesis_line_run"),
    )
    op.create_index(
        "ix_synthesis_lines_input_fingerprint", "synthesis_lines", ["input_fingerprint"]
    )
    op.create_index("ix_synthesis_lines_project_id", "synthesis_lines", ["project_id"])
    op.create_table(
        "natural_outputs",
        sa.Column("line_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("audio_asset_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("sha256", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("channels", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("container", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("codec", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("measurement", sa.String(length=60), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.CheckConstraint(
            "duration_ms > 0 AND byte_size > 0 AND sample_rate BETWEEN 8000 AND 192000 AND channels BETWEEN 1 AND 8",
            name="ck_natural_output_measurement",
        ),
        sa.ForeignKeyConstraint(
            ["audio_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_natural_output_asset",
        ),
        sa.ForeignKeyConstraint(
            ["line_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "synthesis_lines.id",
                "synthesis_lines.track_id",
                "synthesis_lines.segment_id",
                "synthesis_lines.project_id",
                "synthesis_lines.workspace_id",
            ],
            name="fk_natural_output_line",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "project_id", "workspace_id"],
            [
                "private_operations.id",
                "private_operations.project_id",
                "private_operations.workspace_id",
            ],
            name="fk_natural_output_operation",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_natural_output_project",
        ),
        sa.UniqueConstraint(
            *["id", "track_id", "segment_id", "project_id", "workspace_id"],
            name="uq_natural_output_cell",
        ),
        sa.UniqueConstraint(*["line_id"], name="uq_natural_output_line"),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_natural_output_owner"),
    )
    op.create_index("ix_natural_outputs_project_id", "natural_outputs", ["project_id"])
    op.create_table(
        "audio_selections",
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        *(
            [
                sa.ForeignKeyConstraint(
                    [
                        "current_version_id",
                        "id",
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
                    name="fk_audio_selection_current",
                )
            ]
            if sqlite
            else []
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_audio_selection_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_audio_selection_segment",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_audio_selection_track",
        ),
        sa.UniqueConstraint(*["track_id", "segment_id"], name="uq_audio_selection_cell"),
        sa.UniqueConstraint(
            *["id", "track_id", "segment_id", "project_id", "workspace_id"],
            name="uq_audio_selection_identity",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_audio_selection_owner"),
    )
    op.create_index("ix_audio_selections_project_id", "audio_selections", ["project_id"])
    op.create_table(
        "audio_selection_versions",
        sa.Column("selection_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("track_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("output_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("provenance", sa.String(length=20), nullable=False, primary_key=False),
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.CheckConstraint(
            "revision > 0 AND provenance IN ('generated','replacement','manual')",
            name="ck_audio_selection_version",
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
            name="fk_audio_selection_version_output",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_audio_selection_version_project",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "audio_selections.id",
                "audio_selections.track_id",
                "audio_selections.segment_id",
                "audio_selections.project_id",
                "audio_selections.workspace_id",
            ],
            name="fk_audio_selection_version_root",
        ),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_audio_selection_version_owner"
        ),
        sa.UniqueConstraint(
            *["selection_id", "revision"], name="uq_audio_selection_version_revision"
        ),
        sa.UniqueConstraint(
            *["id", "selection_id", "track_id", "segment_id", "project_id", "workspace_id"],
            name="uq_audio_selection_version_root",
        ),
    )
    op.create_index(
        "ix_audio_selection_versions_project_id", "audio_selection_versions", ["project_id"]
    )
    if not sqlite:
        op.create_foreign_key(
            "fk_voice_settings_current",
            "voice_settings",
            "voice_settings_versions",
            ["current_version_id", "id", "track_id", "project_id", "workspace_id"],
            ["id", "settings_id", "track_id", "project_id", "workspace_id"],
        )
        op.create_foreign_key(
            "fk_audio_selection_current",
            "audio_selections",
            "audio_selection_versions",
            ["current_version_id", "id", "track_id", "segment_id", "project_id", "workspace_id"],
            ["id", "selection_id", "track_id", "segment_id", "project_id", "workspace_id"],
        )


def downgrade():
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_voice_settings_current", "voice_settings", type_="foreignkey")
        op.drop_constraint("fk_audio_selection_current", "audio_selections", type_="foreignkey")
    op.drop_table("audio_selection_versions")
    op.drop_table("audio_selections")
    op.drop_table("natural_outputs")
    op.drop_table("synthesis_lines")
    op.drop_table("synthesis_commands")
    op.drop_table("voice_settings_versions")
    op.drop_table("voice_settings")

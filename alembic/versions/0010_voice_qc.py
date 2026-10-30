"""Frozen additive independent recognition and immutable listening history."""

import sqlalchemy as sa

from alembic import op

revision = "0010_voice_qc"
down_revision = "0009_synthesis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "voice_qc_commands",
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("admission_sequence", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_qc_command_project",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_voice_qc_command_track",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_voice_qc_command_owner"),
        sa.UniqueConstraint(
            "id", "track_id", "project_id", "workspace_id", name="uq_voice_qc_command_track"
        ),
        sa.UniqueConstraint("project_id", "signature", name="uq_voice_qc_command_signature"),
        sa.CheckConstraint("admission_sequence >= 0", name="ck_voice_qc_admission"),
    )
    op.create_index(
        op.f("ix_voice_qc_commands_project_id"), "voice_qc_commands", ["project_id"], unique=False
    )
    op.create_table(
        "audio_reviews",
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("output_id", sa.String(length=36), nullable=False),
        sa.Column("translation_revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_selection_id", sa.String(length=36), nullable=False),
        sa.Column("transcript_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("qc_evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("qc_acknowledgement", sa.JSON(), nullable=False),
        sa.Column("guard_snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision > 0 AND decision IN ('accepted','rejected')", name="ck_audio_review_decision"
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
            name="fk_audio_review_output",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_audio_review_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_audio_review_segment",
        ),
        sa.ForeignKeyConstraint(
            ["source_selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_audio_review_source",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_audio_review_track",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_audio_review_transcript",
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
            name="fk_audio_review_translation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_audio_review_owner"),
        sa.UniqueConstraint("track_id", "segment_id", "revision", name="uq_audio_review_revision"),
    )
    op.create_index(
        op.f("ix_audio_reviews_project_id"), "audio_reviews", ["project_id"], unique=False
    )
    op.create_table(
        "voice_qc_lines",
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("output_id", sa.String(length=36), nullable=False),
        sa.Column("translation_revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_selection_id", sa.String(length=36), nullable=False),
        sa.Column("transcript_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("recognition_identity", sa.String(length=64), nullable=False),
        sa.Column("recognition_input", sa.JSON(), nullable=False),
        sa.Column("comparison_input", sa.JSON(), nullable=False),
        sa.Column("guard_snapshot", sa.JSON(), nullable=False),
        sa.Column("publication", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["command_id", "track_id", "project_id", "workspace_id"],
            [
                "voice_qc_commands.id",
                "voice_qc_commands.track_id",
                "voice_qc_commands.project_id",
                "voice_qc_commands.workspace_id",
            ],
            name="fk_voice_qc_line_command",
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
            name="fk_voice_qc_line_output",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_qc_line_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_voice_qc_line_run",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_voice_qc_line_segment",
        ),
        sa.ForeignKeyConstraint(
            ["source_selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_voice_qc_line_source",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_voice_qc_line_transcript",
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
            name="fk_voice_qc_line_translation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id", "segment_id", name="uq_voice_qc_line_command_cell"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_voice_qc_line_owner"),
        sa.UniqueConstraint(
            "id",
            "track_id",
            "segment_id",
            "project_id",
            "workspace_id",
            name="uq_voice_qc_line_cell",
        ),
        sa.UniqueConstraint("run_id", name="uq_voice_qc_line_run"),
    )
    op.create_index(
        op.f("ix_voice_qc_lines_project_id"), "voice_qc_lines", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_voice_qc_lines_recognition_identity"),
        "voice_qc_lines",
        ["recognition_identity"],
        unique=False,
    )
    op.create_table(
        "voice_qc_results",
        sa.Column("line_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("recognition_identity", sa.String(length=64), nullable=False),
        sa.Column("recognition", sa.JSON(), nullable=False),
        sa.Column("comparison", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["line_id", "track_id", "segment_id", "project_id", "workspace_id"],
            [
                "voice_qc_lines.id",
                "voice_qc_lines.track_id",
                "voice_qc_lines.segment_id",
                "voice_qc_lines.project_id",
                "voice_qc_lines.workspace_id",
            ],
            name="fk_voice_qc_result_line",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "project_id", "workspace_id"],
            [
                "private_operations.id",
                "private_operations.project_id",
                "private_operations.workspace_id",
            ],
            name="fk_voice_qc_result_operation",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_qc_result_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_voice_qc_result_owner"),
        sa.UniqueConstraint(
            "id",
            "track_id",
            "segment_id",
            "project_id",
            "workspace_id",
            name="uq_voice_qc_result_cell",
        ),
        sa.UniqueConstraint("line_id", name="uq_voice_qc_result_line"),
    )
    op.create_index(
        op.f("ix_voice_qc_results_project_id"), "voice_qc_results", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_voice_qc_results_recognition_identity"),
        "voice_qc_results",
        ["recognition_identity"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_voice_qc_results_recognition_identity"), table_name="voice_qc_results")
    op.drop_index(op.f("ix_voice_qc_results_project_id"), table_name="voice_qc_results")
    op.drop_table("voice_qc_results")
    op.drop_index(op.f("ix_voice_qc_lines_recognition_identity"), table_name="voice_qc_lines")
    op.drop_index(op.f("ix_voice_qc_lines_project_id"), table_name="voice_qc_lines")
    op.drop_table("voice_qc_lines")
    op.drop_index(op.f("ix_audio_reviews_project_id"), table_name="audio_reviews")
    op.drop_table("audio_reviews")
    op.drop_index(op.f("ix_voice_qc_commands_project_id"), table_name="voice_qc_commands")
    op.drop_table("voice_qc_commands")

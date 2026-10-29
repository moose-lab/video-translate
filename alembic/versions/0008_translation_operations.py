"""Frozen owned command proofs and separately checkpointed translation phases."""

import sqlalchemy as sa

from alembic import op

revision = "0008_translation_operations"
down_revision = "0007_prepared_object_lifecycle"
branch_labels = None
depends_on = None


def owned_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def owned_constraints(name):
    return [
        sa.UniqueConstraint("id", "project_id", "workspace_id", name=f"uq_{name}_owner"),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name=f"fk_{name}_project",
        ),
    ]


def owned_fk(column, table, name):
    return sa.ForeignKeyConstraint(
        [column, "project_id", "workspace_id"],
        [f"{table}.id", f"{table}.project_id", f"{table}.workspace_id"],
        name=name,
    )


def upgrade():
    op.create_table(
        "translation_commands",
        *owned_columns(),
        sa.Column("track_id", sa.String(36), nullable=False),
        sa.Column("selection_id", sa.String(36), nullable=False),
        sa.Column("transcript_id", sa.String(36), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_heads", sa.JSON(), nullable=False),
        sa.Column("generated_context_id", sa.String(36), nullable=True),
        *owned_constraints("translation_command"),
        owned_fk("track_id", "language_tracks", "fk_translation_command_track"),
        owned_fk("selection_id", "source_selections", "fk_translation_command_selection"),
        owned_fk("transcript_id", "transcript_revisions", "fk_translation_command_transcript"),
        sa.UniqueConstraint("project_id", "signature", name="uq_translation_command_signature"),
        sa.ForeignKeyConstraint(
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
    op.create_index("ix_translation_commands_project_id", "translation_commands", ["project_id"])
    op.create_table(
        "translation_phases",
        *owned_columns(),
        sa.Column("command_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("parent_phase_id", sa.String(36), nullable=True),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("dependency_snapshot", sa.JSON(), nullable=False),
        sa.Column("guard_snapshot", sa.JSON(), nullable=False),
        sa.Column("publication", sa.JSON(), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        *owned_constraints("translation_phase"),
        owned_fk("command_id", "translation_commands", "fk_translation_phase_command"),
        owned_fk("run_id", "stage_runs", "fk_translation_phase_run"),
        owned_fk("parent_phase_id", "translation_phases", "fk_translation_phase_parent"),
        sa.UniqueConstraint("run_id", name="uq_translation_phase_run"),
        sa.UniqueConstraint(
            "command_id", "batch_index", "phase", name="uq_translation_phase_batch"
        ),
        sa.CheckConstraint(
            "batch_index >= 0 AND phase IN ('context','draft','critique','rewrite','shorten')",
            name="ck_translation_phase",
        ),
    )
    op.create_index("ix_translation_phases_project_id", "translation_phases", ["project_id"])
    op.create_index(
        "ix_translation_phases_input_fingerprint", "translation_phases", ["input_fingerprint"]
    )


def downgrade():
    op.drop_table("translation_phases")
    op.drop_table("translation_commands")

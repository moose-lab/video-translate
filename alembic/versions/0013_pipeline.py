"""Frozen owned full workflow coordination, checkpoints and stop barriers."""

import sqlalchemy as sa

from alembic import op

revision = "0013_pipeline"
down_revision = "0012_deliveries"
branch_labels = None
depends_on = None


def upgrade():
    # Conservatively retain independently admitted historical jobs on full cancellation.
    op.add_column(
        "stage_runs",
        sa.Column(
            "independently_requested", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.add_column(
        "workflow_intents",
        sa.Column("continuation_stopped", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "pipeline_workflows",
        sa.Column("selection_id", sa.String(length=36), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("source_mode", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("next_action", sa.String(length=60), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("scope_revision", sa.Integer(), nullable=False),
        sa.Column("target_track_ids", sa.JSON(), nullable=False),
        sa.Column("delivery_track_ids", sa.JSON(), nullable=False),
        sa.Column("delivery_options", sa.JSON(), nullable=False),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("wake_revision", sa.Integer(), nullable=False),
        sa.Column("reconciled_revision", sa.Integer(), nullable=False),
        sa.Column("control_run_id", sa.String(length=36), nullable=True),
        sa.Column("target_states", sa.JSON(), nullable=False),
        sa.Column("finish_state", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('dub','incomplete_preview')", name="ck_pipeline_purpose"),
        sa.CheckConstraint(
            "source_mode IN ('automatic','use_current','manual_import')", name="ck_pipeline_source"
        ),
        sa.CheckConstraint(
            "status IN ('running','review','paused','failed','stale','cancelling','cancelled','completed')",
            name="ck_pipeline_status",
        ),
        sa.CheckConstraint(
            "revision > 0 AND generation > 0 AND policy_revision > 0 AND scope_revision > 0 AND wake_revision >= reconciled_revision",
            name="ck_pipeline_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["control_run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_pipeline_control",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_pipeline_project",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_pipeline_selection",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_pipeline_owner"),
        sa.UniqueConstraint("project_id", "signature", name="uq_pipeline_signature"),
    )
    op.create_index(
        op.f("ix_pipeline_workflows_project_id"), "pipeline_workflows", ["project_id"], unique=False
    )
    op.create_table(
        "pipeline_checkpoints",
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("guard", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.String(length=24), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('human','automatic_policy')", name="ck_pipeline_checkpoint_provenance"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_pipeline_checkpoint_project",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "project_id", "workspace_id"],
            [
                "pipeline_workflows.id",
                "pipeline_workflows.project_id",
                "pipeline_workflows.workspace_id",
            ],
            name="fk_pipeline_checkpoint_workflow",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", "workspace_id", name="uq_pipeline_checkpoint_owner"
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "scope_key",
            "guard",
            "provenance",
            "policy_revision",
            name="uq_pipeline_checkpoint",
        ),
    )
    op.create_index(
        op.f("ix_pipeline_checkpoints_project_id"),
        "pipeline_checkpoints",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "pipeline_policies",
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("auto_advance", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_pipeline_policy_project",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "project_id", "workspace_id"],
            [
                "pipeline_workflows.id",
                "pipeline_workflows.project_id",
                "pipeline_workflows.workspace_id",
            ],
            name="fk_pipeline_policy_workflow",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_pipeline_policy_owner"),
        sa.UniqueConstraint("workflow_id", "revision", name="uq_pipeline_policy_revision"),
    )
    op.create_index(
        op.f("ix_pipeline_policies_project_id"), "pipeline_policies", ["project_id"], unique=False
    )
    op.create_table(
        "pipeline_commands",
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("dispatch_key", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("exclusively_owned", sa.Boolean(), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("translation_id", sa.String(length=36), nullable=True),
        sa.Column("synthesis_id", sa.String(length=36), nullable=True),
        sa.Column("qc_id", sa.String(length=36), nullable=True),
        sa.Column("fit_id", sa.String(length=36), nullable=True),
        sa.Column("delivery_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "CASE WHEN source_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN translation_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN synthesis_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN qc_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN fit_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN delivery_id IS NOT NULL THEN 1 ELSE 0 END = 1",
            name="ck_pipeline_command_one",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id", "project_id", "workspace_id"],
            [
                "delivery_commands.id",
                "delivery_commands.project_id",
                "delivery_commands.workspace_id",
            ],
            name="fk_pipeline_delivery",
        ),
        sa.ForeignKeyConstraint(
            ["fit_id", "project_id", "workspace_id"],
            [
                "fit_plan_commands.id",
                "fit_plan_commands.project_id",
                "fit_plan_commands.workspace_id",
            ],
            name="fk_pipeline_fit",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_pipeline_command_project",
        ),
        sa.ForeignKeyConstraint(
            ["qc_id", "project_id", "workspace_id"],
            [
                "voice_qc_commands.id",
                "voice_qc_commands.project_id",
                "voice_qc_commands.workspace_id",
            ],
            name="fk_pipeline_qc",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "project_id", "workspace_id"],
            ["workflow_intents.id", "workflow_intents.project_id", "workflow_intents.workspace_id"],
            name="fk_pipeline_source",
        ),
        sa.ForeignKeyConstraint(
            ["synthesis_id", "project_id", "workspace_id"],
            [
                "synthesis_commands.id",
                "synthesis_commands.project_id",
                "synthesis_commands.workspace_id",
            ],
            name="fk_pipeline_synthesis",
        ),
        sa.ForeignKeyConstraint(
            ["translation_id", "project_id", "workspace_id"],
            [
                "translation_commands.id",
                "translation_commands.project_id",
                "translation_commands.workspace_id",
            ],
            name="fk_pipeline_translation",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "project_id", "workspace_id"],
            [
                "pipeline_workflows.id",
                "pipeline_workflows.project_id",
                "pipeline_workflows.workspace_id",
            ],
            name="fk_pipeline_command_workflow",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_pipeline_command_owner"),
        sa.UniqueConstraint("workflow_id", "dispatch_key", name="uq_pipeline_dispatch"),
    )
    op.create_index(
        op.f("ix_pipeline_commands_project_id"), "pipeline_commands", ["project_id"], unique=False
    )
    with op.batch_alter_table("synthesis_lines") as batch:
        batch.add_column(
            sa.Column("authorization_checkpoint_id", sa.String(length=36), nullable=True)
        )
        batch.create_foreign_key(
            "fk_synthesis_line_authorization",
            "pipeline_checkpoints",
            ["authorization_checkpoint_id", "project_id", "workspace_id"],
            ["id", "project_id", "workspace_id"],
        )
    op.add_column(
        "translation_commands",
        sa.Column("continuation_stopped", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade():
    op.drop_column("stage_runs", "independently_requested")
    op.drop_column("workflow_intents", "continuation_stopped")
    op.drop_column("translation_commands", "continuation_stopped")
    with op.batch_alter_table("synthesis_lines") as batch:
        batch.drop_constraint("fk_synthesis_line_authorization", type_="foreignkey")
        batch.drop_column("authorization_checkpoint_id")
    op.drop_index(op.f("ix_pipeline_commands_project_id"), table_name="pipeline_commands")
    op.drop_table("pipeline_commands")
    op.drop_index(op.f("ix_pipeline_policies_project_id"), table_name="pipeline_policies")
    op.drop_table("pipeline_policies")
    op.drop_index(op.f("ix_pipeline_checkpoints_project_id"), table_name="pipeline_checkpoints")
    op.drop_table("pipeline_checkpoints")
    op.drop_index(op.f("ix_pipeline_workflows_project_id"), table_name="pipeline_workflows")
    op.drop_table("pipeline_workflows")

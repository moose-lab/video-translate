"""Frozen additive owned delivery capture. CPU manifests reuse private operations."""

import sqlalchemy as sa

from alembic import op

revision = "0012_deliveries"
down_revision = "0011_fit_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "delivery_commands",
        sa.Column("fit_plan_id", sa.String(36), nullable=False),
        sa.Column("fit_result_id", sa.String(36), nullable=False),
        sa.Column("source_asset_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_delivery_command_owner"),
        sa.UniqueConstraint("project_id", "signature", name="uq_delivery_signature"),
        sa.UniqueConstraint("run_id", name="uq_delivery_run"),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_delivery_command_project",
        ),
        sa.ForeignKeyConstraint(
            ["fit_plan_id", "project_id", "workspace_id"],
            [
                "fit_plan_commands.id",
                "fit_plan_commands.project_id",
                "fit_plan_commands.workspace_id",
            ],
            name="fk_delivery_fit",
        ),
        sa.ForeignKeyConstraint(
            ["fit_result_id", "project_id", "workspace_id"],
            ["fit_plan_results.id", "fit_plan_results.project_id", "fit_plan_results.workspace_id"],
            name="fk_delivery_result",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_delivery_source",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_delivery_run",
        ),
    )
    op.create_index("ix_delivery_commands_project_id", "delivery_commands", ["project_id"])


def downgrade():
    op.drop_index("ix_delivery_commands_project_id", table_name="delivery_commands")
    op.drop_table("delivery_commands")

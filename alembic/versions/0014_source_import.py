"""Add private encrypted source-link commands without changing prior history."""

import sqlalchemy as sa

from alembic import op

revision = "0014_source_import"
down_revision = "0013_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_imports",
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("encrypted_url", sa.Text(), nullable=False),
        sa.Column("adapter", sa.String(20), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("source_asset_id", sa.String(36), nullable=True),
        sa.Column("probe_run_id", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("adapter IN ('direct','youtube')", name="ck_source_import_adapter"),
        sa.CheckConstraint("expected_revision > 0", name="ck_source_import_revision"),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_source_import_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_source_import_run",
        ),
        sa.ForeignKeyConstraint(
            ["probe_run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_source_import_probe",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_source_import_asset",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_source_import_owner"),
        sa.UniqueConstraint("project_id", "signature", name="uq_source_import_signature"),
    )
    op.create_index("ix_source_imports_project_id", "source_imports", ["project_id"])


def downgrade():
    op.drop_index("ix_source_imports_project_id", table_name="source_imports")
    op.drop_table("source_imports")

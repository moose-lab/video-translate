"""Owned shared-run request keys and fenced raw-reference upload recovery.

Frozen self-contained schema and baseline key/input metadata backfill.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_analysis_recovery_fixes"
down_revision = "0005_analysis_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_request_keys",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_run_request_key"),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_request_key_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_request_key_run",
        ),
    )
    op.create_index("ix_request_keys_run", "run_request_keys", ["run_id"])
    op.execute(
        sa.text("""INSERT INTO run_request_keys
        (id, project_id, workspace_id, run_id, key, request_fingerprint, created_at)
        SELECT id, project_id, workspace_id, id, idempotency_key, request_fingerprint, created_at
        FROM stage_runs WHERE idempotency_key IS NOT NULL""")
    )
    op.add_column("reference_requests", sa.Column("upload_token", sa.String(64), nullable=True))
    op.add_column(
        "reference_requests",
        sa.Column("upload_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reference_requests",
        sa.Column("upload_write_settled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "reference_requests",
        sa.Column("upload_gc_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Previous orphan/queued input checkpoints were written only after put settled.
    # A legacy writing reservation remains unknown, requiring a GC tombstone.
    op.execute(
        sa.text(
            "UPDATE reference_requests SET upload_write_settled = true WHERE upload_state IS NOT NULL AND upload_state != 'writing'"
        )
    )
    op.create_index(
        "ix_reference_upload_gc",
        "reference_requests",
        ["workspace_id", "upload_state", "created_at"],
    )


def downgrade():
    op.drop_index("ix_reference_upload_gc", table_name="reference_requests")
    op.drop_column("reference_requests", "upload_gc_checked_at")
    op.drop_column("reference_requests", "upload_write_settled")
    op.drop_column("reference_requests", "upload_lease_expires_at")
    op.drop_column("reference_requests", "upload_token")
    op.drop_index("ix_request_keys_run", table_name="run_request_keys")
    op.drop_table("run_request_keys")

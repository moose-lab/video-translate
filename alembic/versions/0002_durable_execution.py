"""Durable queue schema. Historical migration: independent of application model changes."""

import sqlalchemy as sa

from alembic import op

revision = "0002_durable_execution"
down_revision = "0001_saas_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects", sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_index("uq_projects_id_workspace", "projects", ["id", "workspace_id"], unique=True)
    op.create_table(
        "stage_runs",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("stage", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("scope_key", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("target_language", sa.String(length=40), nullable=True, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("options", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("input_project_revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column(
            "dependency_fingerprint", sa.String(length=64), nullable=False, primary_key=False
        ),
        sa.Column("dependency_snapshot", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("output_key", sa.String(length=200), nullable=False, primary_key=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True, primary_key=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=20), nullable=False, primary_key=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("auto_failures", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("lease_token", sa.String(length=64), nullable=True, primary_key=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=True, primary_key=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column(
            "cancel_requested_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
        sa.Column("result", sa.JSON(), nullable=True, primary_key=False),
        sa.Column("safe_error", sa.JSON(), nullable=True, primary_key=False),
        sa.Column("provider", sa.String(length=60), nullable=True, primary_key=False),
        sa.Column("model", sa.String(length=120), nullable=True, primary_key=False),
        sa.Column("request_key", sa.String(length=64), nullable=True, primary_key=False),
        sa.Column("remote_id", sa.String(length=200), nullable=True, primary_key=False),
        sa.Column("remote_state", sa.String(length=20), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.UniqueConstraint(*["project_id", "idempotency_key"]),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_run_project_owner",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_run_owner"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.CheckConstraint("attempt_count >= 0 AND auto_failures >= 0", name="ck_run_counts"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.CheckConstraint(
            "remote_state IN ('not_submitted','submitting','submitted','completed')",
            name="ck_remote_state",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','retry_wait','succeeded','needs_review','failed','stale','cancelling','cancelled')",
            name="ck_run_status",
        ),
    )
    op.create_index(
        "ix_runs_project", "stage_runs", ["workspace_id", "project_id", "created_at"], unique=False
    )
    op.create_index("ix_runs_queue", "stage_runs", ["status", "due_at", "created_at"], unique=False)
    op.create_table(
        "run_attempts",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("number", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("outcome", sa.String(length=40), nullable=True, primary_key=False),
        sa.Column("safe_error", sa.JSON(), nullable=True, primary_key=False),
        sa.UniqueConstraint(*["run_id", "number"]),
        sa.CheckConstraint("number > 0", name="ck_attempt_number"),
        sa.ForeignKeyConstraint(["run_id"], ["stage_runs.id"]),
    )
    op.create_index("ix_run_attempts_run_id", "run_attempts", ["run_id"], unique=False)
    op.create_table(
        "input_states",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("key", sa.String(length=200), nullable=False, primary_key=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_input_project_owner",
        ),
        sa.UniqueConstraint(*["workspace_id", "project_id", "key"]),
    )
    op.create_index("ix_input_states_project_id", "input_states", ["project_id"], unique=False)
    op.create_table(
        "project_events",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("project_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=60), nullable=False, primary_key=False),
        sa.Column("run_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("stage", sa.String(length=40), nullable=True, primary_key=False),
        sa.Column("segment_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("target_language", sa.String(length=40), nullable=True, primary_key=False),
        sa.Column("attempt", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("facts", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_event_run_owner",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint(*["project_id", "sequence"]),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_event_project_owner",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_event_sequence"),
        sa.ForeignKeyConstraint(["run_id"], ["stage_runs.id"]),
    )
    op.create_index(
        "ix_events_project",
        "project_events",
        ["workspace_id", "project_id", "sequence"],
        unique=False,
    )


def downgrade():
    op.drop_table("project_events")
    op.drop_table("input_states")
    op.drop_table("run_attempts")
    op.drop_table("stage_runs")
    op.drop_index("uq_projects_id_workspace", table_name="projects")
    op.drop_column("projects", "event_sequence")

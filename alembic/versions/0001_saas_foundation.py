"""Identity, workspace isolation, revisioned projects and private assets."""

import sqlalchemy as sa

from alembic import op

revision = "0001_saas_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.UniqueConstraint("user_id", "workspace_id"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("user_id", "workspace_id", "expires_at"):
        op.create_index(f"ix_auth_sessions_{column}", "auth_sessions", [column])
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_window_started", "login_attempts", ["window_started"])
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_language", sa.String(40), nullable=False),
        sa.Column("target_languages", sa.JSON(), nullable=False),
        sa.Column(
            "source_asset_id",
            sa.String(36),
            sa.ForeignKey("assets.id", name="fk_projects_source_asset", use_alter=True),
            nullable=True,
        ),
        sa.Column("source_track_index", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])
    op.create_index("ix_projects_workspace_active", "projects", ["workspace_id", "deleted_at"])
    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assets_workspace_id", "assets", ["workspace_id"])
    op.create_index("ix_assets_project_id", "assets", ["project_id"])
    # SQLite accepts references to a subsequently created table. PostgreSQL needs ALTER.
    if op.get_context().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_projects_source_asset", "projects", "assets", ["source_asset_id"], ["id"]
        )


def downgrade():
    if op.get_context().dialect.name != "sqlite":
        op.drop_constraint("fk_projects_source_asset", "projects", type_="foreignkey")
    for table in (
        "assets",
        "projects",
        "login_attempts",
        "auth_sessions",
        "memberships",
        "workspaces",
        "users",
    ):
        op.drop_table(table)

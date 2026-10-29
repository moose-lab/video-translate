"""Workspace credentials and versioned provider configuration."""

import sqlalchemy as sa

from alembic import op

revision = "0003_cloud_services"
down_revision = "0002_durable_execution"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("workspace_credentials", "credential"),
        ("provider_connections", "connection"),
        ("provider_connection_revisions", "revision"),
    ]:
        columns = [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False
            ),
            sa.Column("revision", sa.Integer, nullable=False),
        ]
        if kind == "credential":
            columns += [
                sa.Column("kind", sa.String(30), nullable=False),
                sa.Column("ciphertext", sa.Text, nullable=True),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                sa.UniqueConstraint("workspace_id", "kind"),
            ]
        else:
            columns += [
                sa.Column("slot", sa.String(30), nullable=False),
                sa.Column("settings", sa.JSON, nullable=False),
            ]
            if kind == "connection":
                columns += [
                    sa.Column("check_state", sa.JSON, nullable=True),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("workspace_id", "slot"),
                ]
            else:
                columns += [
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("workspace_id", "slot", "revision"),
                ]
        op.create_table(name, *columns)
        op.create_index("ix_" + name + "_workspace_id", name, ["workspace_id"])


def downgrade():
    for name in ("provider_connection_revisions", "provider_connections", "workspace_credentials"):
        op.drop_index("ix_" + name + "_workspace_id", table_name=name)
        op.drop_table(name)

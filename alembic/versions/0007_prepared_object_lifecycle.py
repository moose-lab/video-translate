"""Fenced prepared-object settlement and original source timing normalization flags.

Frozen self-contained schema. Completed legacy writes are known only for orphan
and published rows; prior writing/deleting/deleted rows remain conservative
unknown-writer tombstones until they can be safely reconsidered.
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_prepared_object_lifecycle"
down_revision = "0006_analysis_recovery_fixes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("prepared_objects", sa.Column("reservation_token", sa.String(64), nullable=True))
    op.add_column(
        "prepared_objects",
        sa.Column("write_settled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "prepared_objects",
        sa.Column("delete_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "prepared_objects", sa.Column("gc_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE prepared_objects SET write_settled = true WHERE state IN ('orphan','published')"
        )
    )
    op.create_index("ix_prepared_gc", "prepared_objects", ["workspace_id", "state", "created_at"])
    op.add_column(
        "segments",
        sa.Column(
            "source_analysis_flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )


def downgrade():
    op.drop_column("segments", "source_analysis_flags")
    op.drop_index("ix_prepared_gc", table_name="prepared_objects")
    op.drop_column("prepared_objects", "gc_checked_at")
    op.drop_column("prepared_objects", "delete_pending")
    op.drop_column("prepared_objects", "write_settled")
    op.drop_column("prepared_objects", "reservation_token")

"""Durable stage queue, attempts, dependency states and project journal."""

import sqlalchemy as sa

from alembic import op
from videotranslate.models.execution import InputState, ProjectEvent, RunAttempt, StageRun

revision = "0002_durable_execution"
down_revision = "0001_saas_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects", sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0")
    )
    for model in (StageRun, RunAttempt, InputState, ProjectEvent):
        model.__table__.create(op.get_bind())


def downgrade():
    for model in (ProjectEvent, InputState, RunAttempt, StageRun):
        model.__table__.drop(op.get_bind())
    op.drop_column("projects", "event_sequence")

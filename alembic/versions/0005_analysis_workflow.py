"""Private recoverable analysis, guarded workflows and voice-reference lineage.

Frozen schema; no imports from application metadata or models.
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_analysis_workflow"
down_revision = "0004_dubbing_domain"
branch_labels = None
depends_on = None


def upgrade():

    op.create_table(
        "voice_references",
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_reference_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_voice_reference_owner"),
    )
    op.create_index(
        op.f("ix_voice_references_project_id"), "voice_references", ["project_id"], unique=False
    )
    op.create_table(
        "private_operations",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("connection_revision", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("host", sa.String(length=300), nullable=False),
        sa.Column("prefix", sa.String(length=100), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("remote_id", sa.String(length=200), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("terminal_payload", sa.JSON(), nullable=True),
        sa.Column("prepared_payload", sa.JSON(), nullable=True),
        sa.Column("public_facts", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('ready','submitting','accepted','terminal','prepared','failed')",
            name="ck_operation_phase",
        ),
        sa.CheckConstraint("connection_revision >= 0", name="ck_operation_revision"),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_private_operation_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_operation_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_private_operation_owner"),
        sa.UniqueConstraint("run_id", "generation", name="uq_operation_generation"),
    )
    op.create_index(
        op.f("ix_private_operations_project_id"), "private_operations", ["project_id"], unique=False
    )
    op.create_table(
        "reference_requests",
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dependency_snapshot", sa.JSON(), nullable=False),
        sa.Column("upload_key", sa.String(length=255), nullable=True),
        sa.Column("upload_size", sa.Integer(), nullable=True),
        sa.Column("upload_sha256", sa.String(length=64), nullable=True),
        sa.Column("upload_state", sa.String(length=20), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "origin IN ('uploaded','source','vocals')", name="ck_reference_request_origin"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_reference_request_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_reference_request_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_reference_request_owner"),
    )
    op.create_index(
        op.f("ix_reference_requests_project_id"), "reference_requests", ["project_id"], unique=False
    )
    op.create_table(
        "prepared_objects",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('writing','orphan','published','deleting','deleted')",
            name="ck_prepared_state",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_prepared_asset",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "project_id", "workspace_id"],
            [
                "private_operations.id",
                "private_operations.project_id",
                "private_operations.workspace_id",
            ],
            name="fk_prepared_operation",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_prepared_object_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_prepared_object_owner"),
        sa.UniqueConstraint("storage_key", name="uq_prepared_storage"),
    )
    op.create_index(
        op.f("ix_prepared_objects_project_id"), "prepared_objects", ["project_id"], unique=False
    )
    op.create_table(
        "analysis_media",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("selection_id", sa.String(length=36), nullable=False),
        sa.Column("working_asset_id", sa.String(length=36), nullable=True),
        sa.Column("asr_asset_id", sa.String(length=36), nullable=True),
        sa.Column("vocals_asset_id", sa.String(length=36), nullable=True),
        sa.Column("instrumental_asset_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asr_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_analysis_asr_asset",
        ),
        sa.ForeignKeyConstraint(
            ["instrumental_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_analysis_instrumental_asset",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_analysis_media_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_analysis_media_run",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_analysis_media_selection",
        ),
        sa.ForeignKeyConstraint(
            ["vocals_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_analysis_vocals_asset",
        ),
        sa.ForeignKeyConstraint(
            ["working_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_analysis_working_asset",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_analysis_media_owner"),
        sa.UniqueConstraint("run_id", name="uq_analysis_media_run"),
    )
    op.create_index(
        op.f("ix_analysis_media_project_id"), "analysis_media", ["project_id"], unique=False
    )
    op.create_table(
        "workflow_intents",
        sa.Column("selection_id", sa.String(length=36), nullable=False),
        sa.Column("command_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("editor_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("next_action", sa.String(length=60), nullable=True),
        sa.Column("auto_advance", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('analyse','prepare_media')", name="ck_workflow_action"),
        sa.CheckConstraint(
            "status IN ('running','paused','review','stale','failed','cancelled')",
            name="ck_workflow_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_workflow_intent_project",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_workflow_selection",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_workflow_intent_owner"),
        sa.UniqueConstraint("project_id", "command_fingerprint", name="uq_workflow_command"),
    )
    op.create_index(
        op.f("ix_workflow_intents_project_id"), "workflow_intents", ["project_id"], unique=False
    )
    op.create_table(
        "workflow_children",
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_workflow_child_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_child_run",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "project_id", "workspace_id"],
            ["workflow_intents.id", "workflow_intents.project_id", "workflow_intents.workspace_id"],
            name="fk_child_workflow",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_workflow_child_owner"),
        sa.UniqueConstraint("workflow_id", "run_id", name="uq_workflow_child"),
    )
    op.create_index(
        op.f("ix_workflow_children_project_id"), "workflow_children", ["project_id"], unique=False
    )
    op.create_table(
        "voice_bindings",
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("speaker_id", sa.String(length=36), nullable=True),
        sa.Column("segment_id", sa.String(length=36), nullable=True),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(speaker_id IS NULL) != (segment_id IS NULL)", name="ck_voice_binding_scope"
        ),
        sa.CheckConstraint("revision >= 0", name="ck_voice_binding_revision"),
        sa.ForeignKeyConstraint(
            ["current_version_id", "id", "project_id", "workspace_id"],
            [
                "voice_binding_versions.id",
                "voice_binding_versions.binding_id",
                "voice_binding_versions.project_id",
                "voice_binding_versions.workspace_id",
            ],
            name="fk_voice_binding_current",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_binding_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_voice_binding_segment",
        ),
        sa.ForeignKeyConstraint(
            ["speaker_id", "project_id", "workspace_id"],
            ["speakers.id", "speakers.project_id", "speakers.workspace_id"],
            name="fk_voice_binding_speaker",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_voice_binding_owner"),
        sa.UniqueConstraint("project_id", "scope_key", name="uq_voice_binding_scope"),
    )
    op.create_index(
        op.f("ix_voice_bindings_project_id"), "voice_bindings", ["project_id"], unique=False
    )
    op.create_table(
        "reference_versions",
        sa.Column("reference_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("audio_asset_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.String(length=10000), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=True),
        sa.Column("source_track_id", sa.String(length=36), nullable=True),
        sa.Column("selection_id", sa.String(length=36), nullable=True),
        sa.Column("source_segment_id", sa.String(length=36), nullable=True),
        sa.Column("source_revision_id", sa.String(length=36), nullable=True),
        sa.Column("speaker_id", sa.String(length=36), nullable=True),
        sa.Column("absolute_start_ms", sa.Integer(), nullable=True),
        sa.Column("absolute_end_ms", sa.Integer(), nullable=True),
        sa.Column("relative_start_ms", sa.Integer(), nullable=True),
        sa.Column("relative_end_ms", sa.Integer(), nullable=True),
        sa.Column("dependency_snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("duration_ms > 0", name="ck_reference_duration"),
        sa.ForeignKeyConstraint(
            ["audio_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_reference_audio",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id", "reference_id", "project_id", "workspace_id"],
            [
                "reference_versions.id",
                "reference_versions.reference_id",
                "reference_versions.project_id",
                "reference_versions.workspace_id",
            ],
            name="fk_reference_version_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_reference_version_project",
        ),
        sa.ForeignKeyConstraint(
            ["reference_id", "project_id", "workspace_id"],
            ["voice_references.id", "voice_references.project_id", "voice_references.workspace_id"],
            name="fk_reference_version_root",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_reference_run",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_reference_selection",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_reference_source_asset",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id", "source_segment_id", "project_id", "workspace_id"],
            [
                "segment_revisions.id",
                "segment_revisions.segment_id",
                "segment_revisions.project_id",
                "segment_revisions.workspace_id",
            ],
            name="fk_reference_source_revision",
        ),
        sa.ForeignKeyConstraint(
            ["source_segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_reference_segment",
        ),
        sa.ForeignKeyConstraint(
            ["source_track_id", "project_id", "workspace_id"],
            ["source_tracks.id", "source_tracks.project_id", "source_tracks.workspace_id"],
            name="fk_reference_source_track",
        ),
        sa.ForeignKeyConstraint(
            ["speaker_id", "project_id", "workspace_id"],
            ["speakers.id", "speakers.project_id", "speakers.workspace_id"],
            name="fk_reference_speaker",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "workspace_id", name="uq_reference_version_owner"),
        sa.UniqueConstraint(
            "id", "reference_id", "project_id", "workspace_id", name="uq_reference_version_family"
        ),
    )
    op.create_index(
        op.f("ix_reference_versions_project_id"), "reference_versions", ["project_id"], unique=False
    )
    op.create_table(
        "voice_binding_versions",
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("reference_version_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["binding_id", "project_id", "workspace_id"],
            ["voice_bindings.id", "voice_bindings.project_id", "voice_bindings.workspace_id"],
            name="fk_binding_version_root",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id", "binding_id", "project_id", "workspace_id"],
            [
                "voice_binding_versions.id",
                "voice_binding_versions.binding_id",
                "voice_binding_versions.project_id",
                "voice_binding_versions.workspace_id",
            ],
            name="fk_binding_version_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_voice_binding_version_project",
        ),
        sa.ForeignKeyConstraint(
            ["reference_version_id", "project_id", "workspace_id"],
            [
                "reference_versions.id",
                "reference_versions.project_id",
                "reference_versions.workspace_id",
            ],
            name="fk_binding_reference_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "revision", name="uq_binding_version_revision"),
        sa.UniqueConstraint(
            "id", "binding_id", "project_id", "workspace_id", name="uq_binding_version_family"
        ),
        sa.UniqueConstraint(
            "id", "project_id", "workspace_id", name="uq_voice_binding_version_owner"
        ),
    )
    op.create_index(
        op.f("ix_voice_binding_versions_project_id"),
        "voice_binding_versions",
        ["project_id"],
        unique=False,
    )
    op.add_column(
        "transcript_revisions", sa.Column("detected_language", sa.String(length=40), nullable=True)
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_voice_binding_current",
            "voice_bindings",
            "voice_binding_versions",
            ["current_version_id", "id", "project_id", "workspace_id"],
            ["id", "binding_id", "project_id", "workspace_id"],
        )


def downgrade():
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_voice_binding_current", "voice_bindings", type_="foreignkey")
    else:
        op.execute("UPDATE voice_bindings SET current_version_id = NULL")

    op.drop_column("transcript_revisions", "detected_language")
    op.drop_index(op.f("ix_voice_binding_versions_project_id"), table_name="voice_binding_versions")
    op.drop_table("voice_binding_versions")
    op.drop_index(op.f("ix_reference_versions_project_id"), table_name="reference_versions")
    op.drop_table("reference_versions")
    op.drop_index(op.f("ix_voice_bindings_project_id"), table_name="voice_bindings")
    op.drop_table("voice_bindings")
    op.drop_index(op.f("ix_workflow_children_project_id"), table_name="workflow_children")
    op.drop_table("workflow_children")
    op.drop_index(op.f("ix_workflow_intents_project_id"), table_name="workflow_intents")
    op.drop_table("workflow_intents")
    op.drop_index(op.f("ix_analysis_media_project_id"), table_name="analysis_media")
    op.drop_table("analysis_media")
    op.drop_index(op.f("ix_prepared_objects_project_id"), table_name="prepared_objects")
    op.drop_table("prepared_objects")
    op.drop_index(op.f("ix_reference_requests_project_id"), table_name="reference_requests")
    op.drop_table("reference_requests")
    op.drop_index(op.f("ix_private_operations_project_id"), table_name="private_operations")
    op.drop_table("private_operations")
    op.drop_index(op.f("ix_voice_references_project_id"), table_name="voice_references")
    op.drop_table("voice_references")

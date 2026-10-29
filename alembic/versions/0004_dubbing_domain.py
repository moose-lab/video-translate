"""Immutable dubbing domain, current pointers and composite ownership. Frozen schema."""

import sqlalchemy as sa

from alembic import op

revision = "0004_dubbing_domain"
down_revision = "0003_cloud_services"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_assets_id_project_workspace",
        "assets",
        ["id", "project_id", "workspace_id"],
        unique=True,
    )
    sqlite = op.get_bind().dialect.name == "sqlite"
    op.create_table(
        "source_tracks",
        sa.Column("source_asset_id", sa.String(36), nullable=False),
        sa.Column("probe_run_id", sa.String(36), nullable=False),
        sa.Column("audio_ordinal", sa.Integer(), nullable=False),
        sa.Column("stream_index", sa.Integer(), nullable=False),
        sa.Column("codec", sa.String(80), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "audio_ordinal >= 0 AND stream_index >= 0 AND duration_ms > 0 AND channels >= 0 AND sample_rate >= 0",
            name="ck_source_track_facts",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id", "workspace_id"],
            ["assets.id", "assets.project_id", "assets.workspace_id"],
            name="fk_source_track_asset",
        ),
        sa.ForeignKeyConstraint(
            ["probe_run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_source_track_probe",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_source_track_project",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_source_track_owner"),
    )
    op.create_index("ix_source_tracks_project_id", "source_tracks", ["project_id"], unique=False)
    op.create_table(
        "source_selections",
        sa.Column("track_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision > 0 AND start_ms >= 0 AND end_ms > start_ms", name="ck_selection_window"
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["source_tracks.id", "source_tracks.project_id", "source_tracks.workspace_id"],
            name="fk_selection_track",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_source_selection_project",
        ),
        sa.UniqueConstraint(*["project_id", "revision"], name="uq_selection_revision"),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_source_selection_owner"
        ),
    )
    op.create_index(
        "ix_source_selections_project_id", "source_selections", ["project_id"], unique=False
    )
    op.create_table(
        "transcript_revisions",
        sa.Column("selection_id", sa.String(36), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), nullable=True),
        sa.Column("provenance", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("provider", sa.String(80), nullable=True),
        sa.Column("original_segments", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_transcript_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_transcript_project",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "workspace_id"],
            ["stage_runs.id", "stage_runs.project_id", "stage_runs.workspace_id"],
            name="fk_transcript_run",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_transcript_selection",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_transcript_owner"),
    )
    op.create_index(
        "ix_transcript_revisions_project_id", "transcript_revisions", ["project_id"], unique=False
    )
    op.create_table(
        "source_states",
        sa.Column("selection_id", sa.String(36), nullable=False),
        sa.Column("transcript_id", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_source_state_project",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_source_state_selection",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_source_state_transcript",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_source_state_owner"),
        sa.UniqueConstraint(*["project_id"], name="uq_source_state_project"),
    )
    op.create_index("ix_source_states_project_id", "source_states", ["project_id"], unique=False)
    op.create_table(
        "speakers",
        sa.Column("selection_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("merged_into_id", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["merged_into_id", "project_id", "workspace_id"],
            ["speakers.id", "speakers.project_id", "speakers.workspace_id"],
            name="fk_speaker_merge",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_speaker_project",
        ),
        sa.ForeignKeyConstraint(
            ["selection_id", "project_id", "workspace_id"],
            [
                "source_selections.id",
                "source_selections.project_id",
                "source_selections.workspace_id",
            ],
            name="fk_speaker_selection",
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_speaker_owner"),
    )
    op.create_index("ix_speakers_project_id", "speakers", ["project_id"], unique=False)
    op.create_table(
        "speaker_revisions",
        sa.Column("speaker_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("merged_into_id", sa.String(36), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["merged_into_id", "project_id", "workspace_id"],
            ["speakers.id", "speakers.project_id", "speakers.workspace_id"],
            name="fk_speaker_revision_merged_into",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_speaker_revision_project",
        ),
        sa.ForeignKeyConstraint(
            ["speaker_id", "project_id", "workspace_id"],
            ["speakers.id", "speakers.project_id", "speakers.workspace_id"],
            name="fk_speaker_revision_speaker",
        ),
        sa.UniqueConstraint(*["speaker_id", "revision"], name="uq_speaker_revision"),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_speaker_revision_owner"
        ),
    )
    op.create_index(
        "ix_speaker_revisions_project_id", "speaker_revisions", ["project_id"], unique=False
    )
    op.create_table(
        "segments",
        sa.Column("transcript_id", sa.String(36), nullable=False),
        sa.Column("display_index", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("original_speaker_label", sa.String(100), nullable=True),
        sa.Column("current_revision_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0 AND display_index >= 0", name="ck_segment_revision"),
        *(
            [
                sa.ForeignKeyConstraint(
                    ["current_revision_id", "id", "project_id", "workspace_id"],
                    [
                        "segment_revisions.id",
                        "segment_revisions.segment_id",
                        "segment_revisions.project_id",
                        "segment_revisions.workspace_id",
                    ],
                    name="fk_segment_current",
                )
            ]
            if sqlite
            else []
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_segment_project",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id", "project_id", "workspace_id"],
            [
                "transcript_revisions.id",
                "transcript_revisions.project_id",
                "transcript_revisions.workspace_id",
            ],
            name="fk_segment_transcript",
        ),
        sa.UniqueConstraint(*["transcript_id", "display_index"], name="uq_segment_order"),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_segment_owner"),
    )
    op.create_index("ix_segments_project_id", "segments", ["project_id"], unique=False)
    op.create_table(
        "segment_revisions",
        sa.Column("segment_id", sa.String(36), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("speaker_id", sa.String(36), nullable=True),
        sa.Column("provenance", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms", name="ck_segment_revision_timing"
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "segment_id", "project_id", "workspace_id"],
            [
                "segment_revisions.id",
                "segment_revisions.segment_id",
                "segment_revisions.project_id",
                "segment_revisions.workspace_id",
            ],
            name="fk_segment_revision_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_segment_revision_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_segment_revision_segment",
        ),
        sa.ForeignKeyConstraint(
            ["speaker_id", "project_id", "workspace_id"],
            ["speakers.id", "speakers.project_id", "speakers.workspace_id"],
            name="fk_segment_revision_speaker",
        ),
        sa.UniqueConstraint(
            *["id", "segment_id", "project_id", "workspace_id"], name="uq_segment_revision_cell"
        ),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_segment_revision_owner"
        ),
    )
    op.create_index(
        "ix_segment_revisions_project_id", "segment_revisions", ["project_id"], unique=False
    )
    op.create_table(
        "segment_parents",
        sa.Column("segment_id", sa.String(36), nullable=False),
        sa.Column("parent_segment_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_segment_parent_child",
        ),
        sa.ForeignKeyConstraint(
            ["parent_segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_segment_parent_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_segment_parent_project",
        ),
        sa.UniqueConstraint(*["segment_id", "parent_segment_id"], name="uq_segment_parent"),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_segment_parent_owner"),
    )
    op.create_index(
        "ix_segment_parents_project_id", "segment_parents", ["project_id"], unique=False
    )
    op.create_table(
        "language_tracks",
        sa.Column("tag", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("context_revision_id", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('Fast','Cinematic','Autofit') AND revision > 0", name="ck_track_mode"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_language_track_project",
        ),
        *(
            [
                sa.ForeignKeyConstraint(
                    ["context_revision_id", "id", "project_id", "workspace_id"],
                    [
                        "context_revisions.id",
                        "context_revisions.track_id",
                        "context_revisions.project_id",
                        "context_revisions.workspace_id",
                    ],
                    name="fk_track_context",
                )
            ]
            if sqlite
            else []
        ),
        sa.UniqueConstraint(*["id", "project_id", "workspace_id"], name="uq_language_track_owner"),
        sa.UniqueConstraint(*["project_id", "tag"], name="uq_language_track_tag"),
    )
    op.create_index(
        "ix_language_tracks_project_id", "language_tracks", ["project_id"], unique=False
    )
    op.create_table(
        "context_revisions",
        sa.Column("track_id", sa.String(36), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("glossary", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "track_id", "project_id", "workspace_id"],
            [
                "context_revisions.id",
                "context_revisions.track_id",
                "context_revisions.project_id",
                "context_revisions.workspace_id",
            ],
            name="fk_context_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_context_revision_project",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_context_track",
        ),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_context_revision_owner"
        ),
        sa.UniqueConstraint(
            *["id", "track_id", "project_id", "workspace_id"], name="uq_context_track"
        ),
    )
    op.create_index(
        "ix_context_revisions_project_id", "context_revisions", ["project_id"], unique=False
    )
    op.create_table(
        "translation_revisions",
        sa.Column("segment_id", sa.String(36), nullable=False),
        sa.Column("track_id", sa.String(36), nullable=False),
        sa.Column("context_revision_id", sa.String(36), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_text_fingerprint", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("provenance", sa.String(30), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["context_revision_id", "track_id", "project_id", "workspace_id"],
            [
                "context_revisions.id",
                "context_revisions.track_id",
                "context_revisions.project_id",
                "context_revisions.workspace_id",
            ],
            name="fk_translation_context",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "segment_id", "track_id", "project_id", "workspace_id"],
            [
                "translation_revisions.id",
                "translation_revisions.segment_id",
                "translation_revisions.track_id",
                "translation_revisions.project_id",
                "translation_revisions.workspace_id",
            ],
            name="fk_translation_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_translation_revision_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_translation_segment",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_translation_track",
        ),
        sa.UniqueConstraint(
            *["id", "segment_id", "track_id", "project_id", "workspace_id"],
            name="uq_translation_revision_cell",
        ),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_translation_revision_owner"
        ),
    )
    op.create_index(
        "ix_translation_revisions_project_id", "translation_revisions", ["project_id"], unique=False
    )
    op.create_table(
        "translation_states",
        sa.Column("segment_id", sa.String(36), nullable=False),
        sa.Column("track_id", sa.String(36), nullable=False),
        sa.Column("current_revision_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_translation_state_revision"),
        sa.ForeignKeyConstraint(
            ["current_revision_id", "segment_id", "track_id", "project_id", "workspace_id"],
            [
                "translation_revisions.id",
                "translation_revisions.segment_id",
                "translation_revisions.track_id",
                "translation_revisions.project_id",
                "translation_revisions.workspace_id",
            ],
            name="fk_translation_state_current",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_translation_state_project",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "project_id", "workspace_id"],
            ["segments.id", "segments.project_id", "segments.workspace_id"],
            name="fk_translation_state_segment",
        ),
        sa.ForeignKeyConstraint(
            ["track_id", "project_id", "workspace_id"],
            ["language_tracks.id", "language_tracks.project_id", "language_tracks.workspace_id"],
            name="fk_translation_state_track",
        ),
        sa.UniqueConstraint(*["segment_id", "track_id"], name="uq_translation_state_cell"),
        sa.UniqueConstraint(
            *["id", "project_id", "workspace_id"], name="uq_translation_state_owner"
        ),
    )
    op.create_index(
        "ix_translation_states_project_id", "translation_states", ["project_id"], unique=False
    )
    if not sqlite:
        op.create_foreign_key(
            "fk_segment_current",
            "segments",
            "segment_revisions",
            ["current_revision_id", "id", "project_id", "workspace_id"],
            ["id", "segment_id", "project_id", "workspace_id"],
        )
        op.create_foreign_key(
            "fk_track_context",
            "language_tracks",
            "context_revisions",
            ["context_revision_id", "id", "project_id", "workspace_id"],
            ["id", "track_id", "project_id", "workspace_id"],
        )


def downgrade():
    sqlite = op.get_bind().dialect.name == "sqlite"
    if not sqlite:
        op.drop_constraint("fk_segment_current", "segments", type_="foreignkey")
        op.drop_constraint("fk_track_context", "language_tracks", type_="foreignkey")
    op.drop_table("translation_states")
    op.drop_table("translation_revisions")
    op.drop_table("context_revisions")
    op.drop_table("language_tracks")
    op.drop_table("segment_parents")
    op.drop_table("segment_revisions")
    op.drop_table("segments")
    op.drop_table("speaker_revisions")
    op.drop_table("speakers")
    op.drop_table("source_states")
    op.drop_table("transcript_revisions")
    op.drop_table("source_selections")
    op.drop_table("source_tracks")
    op.drop_index("uq_assets_id_project_workspace", table_name="assets")

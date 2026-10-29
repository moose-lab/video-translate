"""Narrow source/cast edit proof: target and mix edits deliberately excluded."""

from sqlalchemy import select

from ..execution.inputs import fingerprint
from ..models.dubbing import Segment, Speaker
from .ownership import scope
from .source import source_state


def editor_fingerprint(db, project):
    state = source_state(db, project)
    rows = db.execute(
        select(Segment.id, Segment.revision, Segment.current_revision_id, Segment.archived)
        .where(
            Segment.project_id == project.id,
            Segment.workspace_id == project.workspace_id,
            Segment.transcript_id == (state.transcript_id if state else ""),
        )
        .order_by(Segment.id)
    ).all()
    speakers = db.scalars(scope(Speaker, project).order_by(Speaker.id)).all()
    return fingerprint(
        {
            "selection": state.selection_id if state else None,
            "transcript": state.transcript_id if state else None,
            "source_language": project.source_language,
            "segments": [list(row) for row in rows],
            "cast": [
                [s.id, s.selection_id, s.revision, s.archived, s.merged_into_id] for s in speakers
            ],
        }
    )

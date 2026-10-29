"""Probe-backed source selection and immutable active-transcript identity."""

from ..execution.inputs import fingerprint, is_current, set_inputs
from ..models.core import Asset, new_id
from ..models.dubbing import SourceSelection, SourceState, SourceTrack, TranscriptRevision
from ..models.execution import StageRun
from .ownership import changed, conflict, invalid, owned, owner, scope


def source_state(db, project):
    return db.scalar(scope(SourceState, project))


def selection_current(db, project, selection):
    track = owned(db, SourceTrack, project, selection.track_id)
    probe = owned(db, StageRun, project, track.probe_run_id)
    return (
        project.source_asset_id == track.source_asset_id
        and project.source_track_index == track.audio_ordinal
        and probe.status == "succeeded"
        and not probe.is_stale
        and is_current(db, project, probe.dependency_snapshot)
        and is_current(db, project, {"source.selection": fingerprint(selection.id)})
    )


def selection_json(db, project, selection):
    track = owned(db, SourceTrack, project, selection.track_id)
    return {
        "id": selection.id,
        "revision": selection.revision,
        "start_ms": selection.start_ms,
        "end_ms": selection.end_ms,
        "source_asset_id": track.source_asset_id,
        "stale": not selection_current(db, project, selection),
        "track": {
            key: getattr(track, key)
            for key in (
                "id",
                "audio_ordinal",
                "stream_index",
                "codec",
                "language",
                "channels",
                "sample_rate",
                "duration_ms",
                "probe_run_id",
            )
        },
    }


def select_source(db, project, body, actor):
    if project.revision != body.revision:
        conflict()
    asset = owned(db, Asset, project, body.source_asset_id)
    if project.source_asset_id != asset.id:
        conflict()
    probes = db.scalars(
        scope(StageRun, project)
        .where(
            StageRun.stage == "probe", StageRun.status == "succeeded", StageRun.is_stale.is_(False)
        )
        .order_by(StageRun.created_at.desc(), StageRun.id)
    ).all()
    probe = next(
        (
            r
            for r in probes
            if is_current(db, project, r.dependency_snapshot)
            and "source.video" in r.dependency_snapshot
        ),
        None,
    )
    if probe is None or not probe.result:
        conflict()
    facts = probe.result
    audio = next(
        (a for a in facts.get("audio", []) if a["audio_ordinal"] == body.audio_ordinal), None
    )
    end = facts["duration_ms"] if body.end_ms is None else body.end_ms
    if audio is None or not 0 <= body.start_ms < end <= facts["duration_ms"]:
        invalid()
    state = source_state(db, project)
    previous = owned(db, SourceSelection, project, state.selection_id) if state else None
    if previous:
        track = owned(db, SourceTrack, project, previous.track_id)
        if (
            track.source_asset_id == asset.id
            and track.audio_ordinal == body.audio_ordinal
            and previous.start_ms == body.start_ms
            and previous.end_ms == end
            and selection_current(db, project, previous)
        ):
            return selection_json(db, project, previous)
    track = SourceTrack(
        id=new_id(),
        **owner(project),
        source_asset_id=asset.id,
        probe_run_id=probe.id,
        duration_ms=facts["duration_ms"],
        **{
            k: audio[k]
            for k in (
                "audio_ordinal",
                "stream_index",
                "codec",
                "language",
                "channels",
                "sample_rate",
            )
        },
    )
    db.add(track)
    db.flush()
    selection = SourceSelection(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        revision=previous.revision + 1 if previous else 1,
        start_ms=body.start_ms,
        end_ms=end,
        actor_id=actor,
    )
    db.add(selection)
    db.flush()
    if state:
        invalidate_transcript(db, project, state.transcript_id)
        state.selection_id = selection.id
        state.transcript_id = None
    else:
        db.add(SourceState(**owner(project), selection_id=selection.id))
    project.source_track_index = body.audio_ordinal
    db.flush()
    set_inputs(
        db,
        project,
        {
            "source.audio_track": body.audio_ordinal,
            "source.window": {"start_ms": body.start_ms, "end_ms": end},
            "source.selection": selection.id,
            "source.transcript": None,
        },
    )
    changed(
        db,
        project,
        "source.selection_changed",
        revision=selection.revision,
        asset_id=asset.id,
        audio_ordinal=body.audio_ordinal,
    )
    return selection_json(db, project, selection)


def active_source(db, project, guard, *, require_transcript=False):
    state = source_state(db, project)
    if state is None:
        conflict()
    selection = owned(db, SourceSelection, project, state.selection_id)
    if (
        selection.revision != guard.selection_revision
        or state.transcript_id != guard.transcript_revision
        or not selection_current(db, project, selection)
    ):
        conflict()
    transcript = (
        owned(db, TranscriptRevision, project, state.transcript_id) if state.transcript_id else None
    )
    if transcript and transcript.selection_id != selection.id:
        conflict()
    if require_transcript and transcript is None:
        conflict()
    return state, selection, transcript


def new_transcript(db, project, state, selection, actor, provenance, originals=None):
    invalidate_transcript(db, project, state.transcript_id)
    transcript = TranscriptRevision(
        id=new_id(),
        **owner(project),
        selection_id=selection.id,
        parent_revision_id=state.transcript_id,
        provenance=provenance,
        actor_id=actor,
        original_segments=originals or [],
    )
    db.add(transcript)
    db.flush()
    state.transcript_id = transcript.id
    db.flush()
    set_inputs(db, project, {"source.transcript": transcript.id})
    return transcript


def invalidate_transcript(db, project, transcript_id):
    if not transcript_id:
        return
    from ..models.dubbing import Segment
    from .segments import invalidate_segment

    for segment in db.scalars(
        scope(Segment, project).where(
            Segment.transcript_id == transcript_id, Segment.archived.is_(False)
        )
    ):
        invalidate_segment(db, project, segment)

"""Deterministic read-only previews and guarded, explicitly mapped caption application."""

from ..execution.inputs import fingerprint
from ..models.dubbing import Segment, SegmentRevision
from .contracts import SpeakerCreate
from .ownership import changed, conflict, invalid, owned, scope
from .segments import active_segment, insert_segment, validate_fields
from .source import active_source, new_transcript
from .speakers import active_speaker, create_speaker
from .subtitles import parse_subtitles
from .translations import track_for, translation_state, write_translation


def preview_import(db, project, body, tag=None):
    _, selection, transcript = active_source(db, project, body)
    track = track_for(db, project, tag) if tag else None
    if not track and body.format == "numbered":
        invalid()
    try:
        cues = parse_subtitles(body.content, body.format)
    except ValueError:
        invalid()
    window = selection.end_ms - selection.start_ms
    for cue in cues:
        if cue["end_ms"] is not None and cue["end_ms"] > window:
            cue["errors"].append("OUTSIDE_WINDOW")
    # Hash the current cells incrementally; do not return an unbounded collection.
    # This guards source edits and target locks/revisions made after a preview.
    import hashlib

    snapshot = hashlib.sha256()
    matches = {cue["id"]: [] for cue in cues}
    indexed = {cue["index"]: cue for cue in cues} if body.format == "numbered" else {}
    timing = {}
    for cue in cues:
        timing.setdefault((cue["start_ms"], cue["end_ms"]), []).append(cue)
    if transcript:
        query = (
            scope(Segment, project)
            .where(Segment.transcript_id == transcript.id, Segment.archived.is_(False))
            .order_by(Segment.display_index, Segment.id)
        )
        for segment in db.scalars(query).yield_per(100):
            revision = owned(db, SegmentRevision, project, segment.current_revision_id)
            state = translation_state(db, project, track, segment) if track else None
            snapshot.update(
                fingerprint(
                    [
                        segment.id,
                        segment.revision,
                        revision.id,
                        state.revision if state else 0,
                        state.locked if state else False,
                        state.current_revision_id if state else None,
                    ]
                ).encode()
            )
            candidates = (
                [indexed[segment.display_index]]
                if segment.display_index in indexed
                else timing.get((revision.start_ms, revision.end_ms), [])
            )
            for cue in candidates:
                if len(matches[cue["id"]]) < 20:
                    matches[cue["id"]].append(
                        {
                            "segment_id": segment.id,
                            "source_revision": segment.revision,
                            "revision": state.revision if state else 0,
                            "locked": state.locked if state else False,
                        }
                    )
    conflicts = []
    for cue in cues:
        cue["proposed_matches"] = matches[cue["id"]]
        if cue["errors"]:
            conflicts.append({"cue_id": cue["id"], "code": "INVALID_CUE"})
        if cue["warnings"]:
            conflicts.append({"cue_id": cue["id"], "code": "AMBIGUOUS_VOICE_LABEL"})
        if track:
            # Suggestions are never applied implicitly, even exact timing/index matches.
            conflicts.append({"cue_id": cue["id"], "code": "EXPLICIT_MAPPING_REQUIRED"})
            if any(row["locked"] for row in cue["proposed_matches"]):
                conflicts.append({"cue_id": cue["id"], "code": "LOCKED"})
    digest = fingerprint(
        {
            "cues": cues,
            "selection_id": selection.id,
            "transcript_id": transcript.id if transcript else None,
            "track": [track.id, track.revision, track.context_revision_id] if track else None,
            "cells": snapshot.hexdigest(),
        }
    )
    return {
        "digest": digest,
        "cues": cues,
        "conflicts": conflicts,
        "selection_revision": selection.revision,
        "transcript_revision": transcript.id if transcript else None,
    }


def apply_import(db, project, body, actor, tag=None):
    preview = preview_import(db, project, body, tag)
    if preview["digest"] != body.digest:
        conflict()
    cues = {row["id"]: row for row in preview["cues"]}
    mapping = {row.cue_id: row for row in body.mapping}
    if len(mapping) != len(body.mapping) or set(mapping) != set(cues):
        conflict()
    if any(cue["errors"] for cue in cues.values()):
        invalid()
    state, selection, transcript = active_source(db, project, body)
    if tag:
        if transcript is None:
            conflict()
        track = track_for(db, project, tag)
        if len({row.segment_id for row in mapping.values()}) != len(mapping):
            conflict()
        # Validate every mapped cell before any revisions are created.
        rows = []
        for cue_id, item in mapping.items():
            if item.segment_id is None:
                conflict()
            segment = active_segment(db, project, transcript, item.segment_id)
            current = translation_state(db, project, track, segment)
            if (current.revision if current else 0) != item.revision or (
                current and current.locked and not body.force_locked
            ):
                conflict()
            rows.append((segment, item, cues[cue_id]))
        for segment, item, cue in rows:
            write_translation(
                db,
                project,
                track,
                segment,
                item.revision,
                cue["text"],
                actor,
                provenance="import_forced" if body.force_locked else "import",
                force_locked=body.force_locked,
            )
        changed(
            db,
            project,
            "translation.import_forced" if body.force_locked else "translation.imported",
            count=len(rows),
            fingerprint=body.digest,
        )
        return {"count": len(rows)}
    if body.mode == "replace_current" and transcript is None:
        conflict()
    # Source caption import always creates a new immutable transcript, never zips onto IDs.
    if any(item.segment_id is not None for item in mapping.values()):
        conflict()
    for item in mapping.values():
        if item.speaker_id:
            active_speaker(db, project, item.speaker_id, selection)
    new = new_transcript(db, project, state, selection, actor, "import", list(cues.values()))
    voice_labels = {}
    for cue in preview["cues"]:
        item = mapping[cue["id"]]
        speaker_id = item.speaker_id
        if item.use_voice_label:
            label = cue["voice_label"]
            if not label or speaker_id:
                invalid()
            if label not in voice_labels:
                voice_labels[label] = create_speaker(db, project, SpeakerCreate(name=label), actor)[
                    "id"
                ]
            speaker_id = voice_labels[label]
        values = {
            "text": cue["text"],
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "speaker_id": speaker_id,
        }
        validate_fields(db, project, selection, values)
        insert_segment(db, project, new, values, actor, "import", label=cue["voice_label"])
    changed(
        db,
        project,
        "source.imported",
        count=len(cues),
        fingerprint=body.digest,
        transcript_id=new.id,
        provenance="import",
    )
    return {"transcript_revision": new.id, "count": len(cues)}

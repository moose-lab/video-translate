"""Immutable owned fit command capture and current-input proofs, with no media I/O."""

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import fingerprint, set_inputs
from ..models.core import Asset, new_id
from ..models.dubbing import Segment, SegmentRevision, SourceTrack, TranslationRevision
from ..models.execution import StageRun
from ..models.finishing import FitPlanCommand, FitPlanLine, FitPlanResult
from ..models.synthesis import AudioSelectionVersion, NaturalOutput
from . import fit_settings
from .fit_contracts import POLICY, FitPlanCreate, FitSettingsBody
from .ownership import changed, conflict, invalid, owned, owner, scope
from .segments import active_segment, active_segments_query
from .source import active_source
from .synthesis import selection_for
from .translations import track_for, translation_state
from .voice_qc import current_proof, output_assessment

SNAPSHOT_LIMIT = 2 * 1024 * 1024


@dataclass(frozen=True)
class FitAdmission:
    """Committed identity is projected through the ordinary authoritative read path."""

    id: str
    reused: bool = False


def json_size(value):
    import json

    return len(json.dumps(value, allow_nan=False).encode())


def source_snapshot(db, project, body):
    _, selection, transcript = active_source(
        db, project, body, require_transcript=body.purpose != "original_only"
    )
    track = owned(db, SourceTrack, project, selection.track_id)
    asset = owned(db, Asset, project, track.source_asset_id)
    root, version = fit_settings.current(db, project)
    revision = root.revision if root else 0
    if body.settings_revision != revision:
        conflict()
    return dict(
        source_asset_id=asset.id,
        source_sha256=asset.sha256,
        source_selection_id=selection.id,
        selection_revision=selection.revision,
        source_track_id=track.id,
        start_ms=selection.start_ms,
        end_ms=selection.end_ms,
        transcript_id=transcript.id if transcript else None,
        settings_revision=revision,
        settings_version_id=version.id if version else None,
        settings=version.settings if version else FitSettingsBody().model_dump(),
        policy=POLICY,
    ), transcript


def capture_row(db, project, track, transcript, row):
    segment = active_segment(db, project, transcript, row.id)
    source = owned(db, SegmentRevision, project, segment.current_revision_id)
    state = translation_state(db, project, track, segment)
    target = owned(db, TranslationRevision, project, state.current_revision_id) if state else None
    audio = selection_for(db, project, track, segment)
    version = (
        owned(db, AudioSelectionVersion, project, audio.current_version_id)
        if audio and audio.current_version_id
        else None
    )
    output = owned(db, NaturalOutput, project, version.output_id) if version else None
    # Supplied foreign/cross-cell IDs never degrade into a preview omission.
    if row.output_id:
        supplied = owned(db, NaturalOutput, project, row.output_id)
        if supplied.track_id != track.id or supplied.segment_id != segment.id:
            invalid()
    if (
        row.expected_source_revision_id != source.id
        or row.expected_source_text_fingerprint != fingerprint(source.text)
        or row.translation_revision != (state.revision if state else 0)
        or row.selection_revision != (audio.revision if audio else 0)
        or row.output_id != (output.id if output else None)
    ):
        conflict()
    issues, valid, assessment = [], False, None
    try:
        current_proof(db, project, track, segment)
        valid = True
    except APIError as error:
        issues.append(error.code)
    if output:
        assessment = output_assessment(db, project, track, segment, output)
        issues.extend(assessment["issues"])
        if "NATURAL_AUDIO_STALE" in issues:
            valid = False
    if row.review_revision != (
        assessment["review_revision"] if assessment else 0
    ) or row.qc_evidence_fingerprint != (
        assessment["qc_evidence_fingerprint"] if assessment else None
    ):
        conflict()
    facts = dict(
        track_id=track.id,
        tag=track.tag,
        segment_id=segment.id,
        source_revision_id=source.id,
        source_text_fingerprint=fingerprint(source.text),
        start_ms=source.start_ms,
        end_ms=source.end_ms,
        role_id=source.speaker_id,
        translation_revision_id=target.id if target else None,
        translation_revision=state.revision if state else 0,
        target_text_fingerprint=fingerprint(target.text) if target else None,
        audio_selection_id=audio.id if audio else None,
        audio_version_id=version.id if version else None,
        audio_selection_revision=audio.revision if audio else 0,
        output_id=output.id if output else None,
        audio_sha256=output.sha256 if output else None,
        natural_duration_ms=output.duration_ms if output else None,
        measurement=dict(
            byte_size=output.byte_size,
            sample_rate=output.sample_rate,
            channels=output.channels,
            container=output.container,
            codec=output.codec,
            measurement=output.measurement,
            input_fingerprint=output.input_fingerprint,
            operation_id=output.operation_id,
        )
        if output
        else None,
        review_revision=row.review_revision,
        qc_evidence_fingerprint=row.qc_evidence_fingerprint,
        review_id=assessment["review"]["id"] if assessment and assessment["review"] else None,
        ready=bool(valid and assessment and assessment["ready"]),
        included=bool(valid),
        issues=sorted(set(issues)),
    )
    return facts


def command(db, project, body, actor, *, pipeline_call=False):
    from ..execution.service import create_run

    snapshot, transcript = source_snapshot(db, project, body)
    captured, tracks, seen = [], [], set()
    for requested in body.tracks:
        track = track_for(db, project, requested.tag)
        if track.id in seen:
            invalid()
        seen.add(track.id)
        if body.purpose == "dub":
            active_ids = set(
                db.scalars(
                    active_segments_query(project, transcript.id)
                    .with_only_columns(Segment.id)
                    .limit(1001)
                )
            )
            if active_ids != {r.id for r in requested.segments}:
                raise APIError(
                    409, "FIT_TRACK_INCOMPLETE", "Complete current source rows are required"
                )
        rows = [capture_row(db, project, track, transcript, r) for r in requested.segments]
        captured.extend(rows)
        tracks.append(
            dict(
                id=track.id,
                tag=track.tag,
                included_segment_ids=sorted(r["segment_id"] for r in rows if r["included"]),
            )
        )
    captured.sort(key=lambda r: (r["track_id"], r["segment_id"]))
    if body.purpose == "dub" and any(not r["ready"] for r in captured):
        issues = Counter(i for r in captured if not r["ready"] for i in r["issues"])
        raise APIError(
            409,
            "FIT_AUDIO_NOT_READY",
            "Every current row requires accepted usable natural audio",
            details={
                "count": sum(not r["ready"] for r in captured),
                "issues": dict(issues),
                "rows": [
                    dict(track_id=r["track_id"], segment_id=r["segment_id"], issues=r["issues"])
                    for r in captured
                    if not r["ready"]
                ][:100],
            },
        )
    snapshot.update(purpose=body.purpose, tracks=sorted(tracks, key=lambda t: t["id"]))
    if json_size({"snapshot": snapshot, "rows": captured}) > SNAPSHOT_LIMIT:
        raise APIError(422, "FIT_SNAPSHOT_LIMIT", "Fit capture exceeds the snapshot limit")
    signature = fingerprint({"snapshot": snapshot, "rows": captured, "actor_id": actor})
    prior = db.scalar(scope(FitPlanCommand, project).where(FitPlanCommand.signature == signature))
    if prior:
        if not pipeline_call:
            from .pipeline import mark_shared

            mark_shared(db, project, "fit", prior.id)
        return FitAdmission(prior.id, reused=True)
    intent = FitPlanCommand(
        id=new_id(),
        **owner(project),
        source_asset_id=snapshot["source_asset_id"],
        source_selection_id=snapshot["source_selection_id"],
        transcript_id=snapshot["transcript_id"],
        settings_version_id=snapshot["settings_version_id"],
        signature=signature,
        actor_id=actor,
        purpose=body.purpose,
        admission_sequence=project.event_sequence,
        line_count=len(captured),
        snapshot=snapshot,
    )
    db.add(intent)
    db.flush()
    for row in captured:
        db.add(
            FitPlanLine(
                id=new_id(),
                **owner(project),
                command_id=intent.id,
                **{
                    k: row[k]
                    for k in (
                        "track_id",
                        "segment_id",
                        "source_revision_id",
                        "translation_revision_id",
                        "audio_selection_id",
                        "audio_version_id",
                        "output_id",
                        "included",
                    )
                },
                snapshot=row,
            )
        )
    db.flush()
    set_inputs(db, project, {"finishing.fit_input:" + intent.id: signature})
    run = create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(stage="plan_fit", options={"command_id": intent.id}),
        idempotency_key="plan_fit:" + intent.id,
        guarded_command=True,
    )
    intent.run_id = run.id
    changed(
        db,
        project,
        "finishing.plan_queued",
        run=run,
        command_id=intent.id,
        purpose=intent.purpose,
        count=len(captured),
        included_count=sum(r["included"] for r in captured),
    )
    db.flush()
    return FitAdmission(intent.id)


def captured_rows(db, project, intent):
    return db.scalars(
        scope(FitPlanLine, project)
        .where(FitPlanLine.command_id == intent.id)
        .order_by(FitPlanLine.track_id, FitPlanLine.segment_id)
        .limit(1001)
    ).all()


def capture_integrity(intent, rows):
    try:
        if len(rows) != intent.line_count or len(rows) > 1000:
            return False
        if any(
            getattr(intent, name) != intent.snapshot[name]
            for name in (
                "source_asset_id",
                "source_selection_id",
                "transcript_id",
                "settings_version_id",
                "purpose",
            )
        ):
            return False
        for row in rows:
            data = row.snapshot
            if any(
                getattr(row, name) != data[name]
                for name in (
                    "track_id",
                    "segment_id",
                    "source_revision_id",
                    "translation_revision_id",
                    "audio_selection_id",
                    "audio_version_id",
                    "output_id",
                    "included",
                )
            ):
                return False
            if any(type(data[name]) is not bool for name in ("included", "ready")):
                return False
            if any(
                type(data[name]) is not int
                for name in (
                    "start_ms",
                    "end_ms",
                    "translation_revision",
                    "audio_selection_revision",
                    "review_revision",
                )
            ):
                return False
            if (
                data["natural_duration_ms"] is not None
                and type(data["natural_duration_ms"]) is not int
            ):
                return False
            if data["measurement"] is not None and any(
                type(data["measurement"][name]) is not int
                for name in ("byte_size", "sample_rate", "channels")
            ):
                return False
        plain = [r.snapshot for r in rows]
        return (
            json_size({"snapshot": intent.snapshot, "rows": plain}) <= SNAPSHOT_LIMIT
            and fingerprint(
                {"snapshot": intent.snapshot, "rows": plain, "actor_id": intent.actor_id}
            )
            == intent.signature
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def current_plan_state(db, project, intent, rows=None):
    rows = captured_rows(db, project, intent) if rows is None else rows
    if not capture_integrity(intent, rows):
        return dict(
            current=False,
            stale=True,
            audio_eligible=False,
            dub_ready=False,
            issues=["FIT_CAPTURE_INVALID"],
        )
    current, ready, issues = True, bool(rows), set()
    cells = {(r.track_id, r.segment_id): r for r in rows}
    try:
        body = FitPlanCreate(
            selection_revision=intent.snapshot["selection_revision"],
            transcript_revision=intent.transcript_id,
            settings_revision=intent.snapshot["settings_revision"],
            purpose=intent.purpose,
            tracks=[
                dict(
                    tag=t["tag"],
                    segments=[
                        dict(
                            id=r.segment_id,
                            expected_source_revision_id=r.source_revision_id,
                            expected_source_text_fingerprint=r.snapshot["source_text_fingerprint"],
                            translation_revision=r.snapshot["translation_revision"],
                            selection_revision=r.snapshot["audio_selection_revision"],
                            output_id=r.output_id,
                            review_revision=r.snapshot["review_revision"],
                            qc_evidence_fingerprint=r.snapshot["qc_evidence_fingerprint"],
                        )
                        for r in rows
                        if r.track_id == t["id"]
                    ],
                )
                for t in intent.snapshot["tracks"]
            ],
        )
        source, transcript = source_snapshot(db, project, body)
        expected = {k: v for k, v in intent.snapshot.items() if k not in {"purpose", "tracks"}}
        if source != expected:
            current = False
        for track_body in body.tracks:
            track = track_for(db, project, track_body.tag)
            if intent.purpose == "dub":
                from ..models.dubbing import Segment

                if set(
                    db.scalars(
                        active_segments_query(project, transcript.id)
                        .with_only_columns(Segment.id)
                        .limit(1001)
                    )
                ) != {r.id for r in track_body.segments}:
                    current = False
            for requested in track_body.segments:
                captured = cells[track.id, requested.id]
                now = capture_row(db, project, track, transcript, requested)
                if now != captured.snapshot:
                    current = False
                ready = ready and now["ready"]
                issues.update(now["issues"])
    except (APIError, ValueError, KeyError, TypeError, AttributeError):
        current, ready = False, False
    if not current:
        issues.add("FIT_INPUT_CHANGED")
    return dict(
        current=current,
        stale=not current,
        audio_eligible=bool(current and ready),
        dub_ready=bool(current and ready and intent.purpose == "dub"),
        issues=sorted(issues),
    )


def detail(db, project, intent, limit=100, offset=0, *, reused=False):
    rows = captured_rows(db, project, intent)
    valid_capture = capture_integrity(intent, rows)
    state = current_plan_state(db, project, intent, rows)
    record = db.scalar(scope(FitPlanResult, project).where(FitPlanResult.command_id == intent.id))
    run = owned(db, StageRun, project, intent.run_id)
    result = dict(
        id=intent.id,
        run_id=run.id,
        status=run.status,
        purpose=intent.purpose,
        actor_id=intent.actor_id,
        total=intent.line_count,
        reused=reused,
        admission_sequence=intent.admission_sequence,
        **state,
        timeline_feasible=record.timeline_feasible if record else None,
        planned_output_duration_ms=record.planned_output_duration if record else None,
        render_eligible=bool(
            record
            and record.timeline_feasible
            and state["audio_eligible"]
            and intent.purpose == "dub"
        ),
        tracks=intent.snapshot["tracks"] if valid_capture else [],
        plan=record.plan if record else None,
        lines=[
            dict(id=r.id, **r.snapshot)
            if valid_capture
            else dict(
                id=r.id,
                track_id=r.track_id,
                segment_id=r.segment_id,
                included=False,
                issues=["FIT_CAPTURE_INVALID"],
            )
            for r in rows[offset : offset + limit]
        ],
    )
    if record and not valid_capture:
        result.update(
            plan=None,
            timeline_feasible=None,
            planned_output_duration_ms=None,
            render_eligible=False,
        )
        result["issues"] = sorted(set(result["issues"] + ["FIT_PLAN_INVALID"]))
        return result
    if record:
        # Detach plain immutable inputs, end the read transaction BEFORE strict CPU validation.
        snapshot = dict(intent.snapshot)
        plain_rows = [dict(r.snapshot) for r in rows]
        capture_integrity_value = capture_integrity(intent, rows)
        expected_signature = fingerprint(
            {"snapshot": snapshot, "rows": plain_rows, "actor_id": intent.actor_id}
        )
        plan = record.plan
        summary = (record.timeline_feasible, record.planned_output_duration, record.issues)
        payload_fingerprint = record.payload_fingerprint
        from ..execution.prepared import current_operation
        from .fit_checkpoint import (
            canonical_facts,
            same_json,
            validate_checkpoint,
            validate_operation,
            validate_summary,
        )

        operation = current_operation(db, run)
        provenance_valid = bool(
            operation and operation.id == record.operation_id and record.run_id == run.id
        )
        db.commit()
        from .fit_snapshot import validate_stored

        try:
            if (
                not capture_integrity_value
                or not provenance_valid
                or expected_signature != intent.signature
                or fingerprint(plan) != payload_fingerprint
            ):
                raise ValueError("Invalid owned plan")
            validate_stored(plan, snapshot, plain_rows)
            validate_summary(*summary, plan)
            expected_binding = validate_operation(intent, run, operation)
            validate_checkpoint(
                operation.prepared_payload,
                expected_binding,
                operation.public_facts,
                canonical_facts(intent, plain_rows, plan),
            )
            if operation.prepared_payload[
                "payload_fingerprint"
            ] != payload_fingerprint or not same_json(operation.prepared_payload["plan"], plan):
                raise ValueError("Invalid producing fit checkpoint")
            result["issues"] = sorted(set(result["issues"] + [r["code"] for r in plan["issues"]]))
        except (ValueError, KeyError, TypeError, AttributeError):
            result.update(
                plan=None,
                render_eligible=False,
                timeline_feasible=None,
                planned_output_duration_ms=None,
            )
            result["issues"] = sorted(set(result["issues"] + ["FIT_PLAN_INVALID"]))
    if not record and run.status in {"needs_review", "failed"}:
        result["calculation_error"] = run.safe_error
        result["issues"] = sorted(
            set(
                result["issues"]
                + ["FIT_PLAN_INVALID" if run.status == "needs_review" else "FIT_COMPUTATION_FAILED"]
            )
        )
    return result


def summaries(db, project, limit=100, offset=0):
    from .fit_checkpoint import captured_summary

    # Deliberately project only summary columns. Large maps/snapshots stay out of this query.
    total = db.scalar(
        select(func.count())
        .select_from(FitPlanCommand)
        .where(
            FitPlanCommand.project_id == project.id,
            FitPlanCommand.workspace_id == project.workspace_id,
        )
    )
    selected = (
        select(
            FitPlanCommand.id,
            FitPlanCommand.run_id,
            FitPlanCommand.purpose,
            FitPlanCommand.line_count,
            FitPlanCommand.admission_sequence,
            StageRun.status,
            FitPlanResult.timeline_feasible,
            FitPlanResult.planned_output_duration,
        )
        .outerjoin(FitPlanResult, FitPlanResult.command_id == FitPlanCommand.id)
        .join(StageRun, StageRun.id == FitPlanCommand.run_id)
        .where(
            FitPlanCommand.project_id == project.id,
            FitPlanCommand.workspace_id == project.workspace_id,
        )
        .order_by(FitPlanCommand.admission_sequence.desc(), FitPlanCommand.id)
        .limit(limit)
        .offset(offset)
    )
    return dict(
        total=total,
        items=[
            dict(
                id=r.id,
                run_id=r.run_id,
                purpose=r.purpose,
                total=r.line_count,
                admission_sequence=r.admission_sequence,
                status=r.status,
                current=None,
                currentness="not_assessed",
                plan_validation="not_assessed",
                audio_eligible=None,
                render_eligible=None,
                captured_result=captured_summary(r.timeline_feasible, r.planned_output_duration),
            )
            for r in db.execute(selected)
        ],
    )

"""Owned QC commands and comparison/listening proofs; no network or media I/O."""

from sqlalchemy import func, select

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import fingerprint, set_inputs
from ..models.core import new_id
from ..models.dubbing import LanguageTrack, SegmentRevision, TranscriptRevision, TranslationRevision
from ..models.execution import StageRun
from ..models.synthesis import AudioSelectionVersion, NaturalOutput, SynthesisLine
from ..models.voice_qc import AudioReview, VoiceQCCommand, VoiceQCLine, VoiceQCResult
from .ownership import changed, conflict, invalid, owned, owner, scope
from .segments import active_segment
from .source import active_source, current_selection, source_state
from .synthesis import ACTIVE, selection_for
from .translations import track_for, translation_state

POLICY = {"version": "qc_pcm16kmono_v1", "sample_rate": 16000, "channels": 1, "codec": "pcm_s16le"}


def current_proof(db, project, track, segment):
    state = source_state(db, project)
    selection = current_selection(db, project)
    source = owned(db, SegmentRevision, project, segment.current_revision_id)
    target_state = translation_state(db, project, track, segment)
    if not target_state or target_state.stale:
        raise APIError(409, "TARGET_STALE", "A current target wording is required")
    target = owned(db, TranslationRevision, project, target_state.current_revision_id)
    if not target.text.strip() or target.source_text_fingerprint != fingerprint(source.text):
        conflict()
    audio = selection_for(db, project, track, segment)
    if not audio or not audio.current_version_id:
        raise APIError(409, "AUDIO_REQUIRED", "Select validated natural audio first")
    selected = owned(db, AudioSelectionVersion, project, audio.current_version_id)
    output = owned(db, NaturalOutput, project, selected.output_id)
    if output.track_id != track.id or output.segment_id != segment.id:
        invalid()
    from .synthesis_cache import validate_output_evidence

    try:
        validate_output_evidence(db, project, output)
    except (APIError, ValueError, KeyError, TypeError, AttributeError):
        raise APIError(
            409, "AUDIO_EVIDENCE_INVALID", "Natural audio provenance requires review"
        ) from None
    proof = {
        "source_selection_id": selection.id,
        "source_selection_revision": selection.revision,
        "transcript_id": state.transcript_id,
        "source_text_fingerprint": fingerprint(source.text),
        "target_text_fingerprint": fingerprint(target.text),
        "target_language": track.tag,
        "translation_revision_id": target.id,
        "translation_revision": target_state.revision,
        "audio_selection_revision": audio.revision,
        "audio_selection_version_id": selected.id,
        "output_id": output.id,
        "audio_sha256": output.sha256,
    }
    return proof, output, target


def check_row(row, proof):
    if (
        row.translation_revision != proof["translation_revision"]
        or row.expected_source_text_fingerprint != proof["source_text_fingerprint"]
        or row.selection_revision != proof["audio_selection_revision"]
        or row.output_id != proof["output_id"]
    ):
        conflict()


def line_current(db, project, line):
    try:
        track = owned(db, LanguageTrack, project, line.track_id)
        state = source_state(db, project)
        if track.archived or state is None or state.transcript_id is None:
            return False
        transcript = owned(db, TranscriptRevision, project, state.transcript_id)
        segment = active_segment(db, project, transcript, line.segment_id)
        proof, *_ = current_proof(db, project, track, segment)
        return proof == line.guard_snapshot
    except (APIError, ValueError, KeyError, TypeError, AttributeError):
        return False


def verification_config(db, project):
    from ..providers.settings import capability_contract
    from .workflow import connection

    config = connection(db, project, "verification")
    if not config or config.settings.get("adapter") != "hf_router":
        raise APIError(
            409, "PROVIDER_REQUIRED", "Configure independent verification or use listening review"
        )
    values = config.settings
    caps = capability_contract("verification", "hf_router", model=values.get("model"))
    return config, caps


def capability_status(caps, tag):
    from ..languages.catalog import resolve

    base = resolve(tag)["code"]
    return "supported" if base in caps["supported_languages"] else caps["language_support"]


def command(db, project, tag, body, actor):
    from ..execution.service import create_run

    _, _, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    if len({r.id for r in body.segments}) != len(body.segments):
        invalid()
    config, caps = verification_config(db, project)
    support = capability_status(caps, track.tag)
    if support != "supported":
        raise APIError(
            409,
            "QC_LANGUAGE_UNSUPPORTED" if support == "unsupported" else "QC_LANGUAGE_UNKNOWN",
            "Independent recognition coverage is unavailable; use explicit listening review",
        )
    captured = []
    for row in body.segments:
        segment = active_segment(db, project, transcript, row.id)
        proof, output, target = current_proof(db, project, track, segment)
        check_row(row, proof)
        inputs = {
            "audio_sha256": output.sha256,
            "config": config.settings,
            "connection_revision": config.revision,
            "preprocessing": POLICY,
            "model_declaration_revision": caps.get("model_declaration_revision"),
        }
        generation = owned(db, SynthesisLine, project, output.line_id)
        comparison = {
            "expected": target.text,
            "target": track.tag,
            "reference": generation.input_payload["reference_text"],
        }
        captured.append((row, proof, inputs, comparison))
    signature = fingerprint({"track_id": track.id, "rows": [list(item[1:]) for item in captured]})
    prior = db.scalar(scope(VoiceQCCommand, project).where(VoiceQCCommand.signature == signature))
    if prior:
        return command_json(db, project, prior)
    for row, *_ in captured:
        pending = db.scalar(
            scope(StageRun, project).where(
                StageRun.stage == "voice_qc",
                StageRun.target_language == tag,
                StageRun.segment_id == row.id,
                (StageRun.status.in_(ACTIVE)) | (StageRun.remote_state == "submitting"),
            )
        )
        if pending:
            raise APIError(
                409,
                "SUBMISSION_UNCERTAIN" if pending.remote_state == "submitting" else "RUN_ACTIVE",
                "Existing recognition must finish or be explicitly reconciled",
            )
    intent = VoiceQCCommand(
        id=new_id(), **owner(project), track_id=track.id, signature=signature, actor_id=actor
    )
    db.add(intent)
    db.flush()
    for row, proof, inputs, comparison in captured:
        digest = fingerprint(inputs)
        line = VoiceQCLine(
            id=new_id(),
            **owner(project),
            command_id=intent.id,
            track_id=track.id,
            segment_id=row.id,
            output_id=row.output_id,
            translation_revision_id=proof["translation_revision_id"],
            source_selection_id=proof["source_selection_id"],
            transcript_id=proof["transcript_id"],
            recognition_identity=digest,
            recognition_input=inputs,
            comparison_input=comparison,
            guard_snapshot=proof,
        )
        db.add(line)
        db.flush()
        set_inputs(db, project, {"voice_qc.input:" + digest: inputs})
        run = create_run(
            db,
            project.workspace_id,
            project.id,
            RunCreate(
                stage="voice_qc",
                target_language=tag,
                segment_id=row.id,
                options={"line_id": line.id},
            ),
            idempotency_key="voice_qc:" + line.id,
            guarded_command=True,
        )
        line.run_id = run.id
    changed(
        db,
        project,
        "voice_qc.queued",
        workflow_id=intent.id,
        count=len(captured),
        target_language=tag,
    )
    db.flush()
    return command_json(db, project, intent)


def command_json(db, project, intent, limit=100, offset=0):
    query = scope(VoiceQCLine, project).where(VoiceQCLine.command_id == intent.id)
    rows = db.scalars(
        query.order_by(VoiceQCLine.created_at, VoiceQCLine.id).limit(limit).offset(offset)
    ).all()
    result = []
    for line in rows:
        run = owned(db, StageRun, project, line.run_id)
        record = db.scalar(scope(VoiceQCResult, project).where(VoiceQCResult.line_id == line.id))
        result.append(
            {
                "id": line.id,
                "segment_id": line.segment_id,
                "output_id": line.output_id,
                "run_id": run.id,
                "status": run.status,
                "publication": line.publication,
                "current": line_current(db, project, line),
                "recognition": record.recognition if record else None,
                "comparison": record.comparison if record else None,
                "next_action": "acknowledge_uncertain_submission"
                if run.remote_state == "submitting"
                else "listen_and_review",
            }
        )
    return {
        "id": intent.id,
        "total": db.scalar(select(func.count()).select_from(query.subquery())),
        "lines": result,
    }


def review_query(project, track, segment):
    return scope(AudioReview, project).where(
        AudioReview.track_id == track.id, AudioReview.segment_id == segment.id
    )


def put_review(db, project, tag, segment_id, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    segment = active_segment(db, project, transcript, segment_id)
    proof, output, _ = current_proof(db, project, track, segment)
    if (
        body.translation_revision != proof["translation_revision"]
        or body.expected_source_text_fingerprint != proof["source_text_fingerprint"]
        or body.audio_selection_revision != proof["audio_selection_revision"]
        or body.output_id != output.id
    ):
        conflict()
    latest = db.scalar(
        review_query(project, track, segment).order_by(AudioReview.revision.desc()).limit(1)
    )
    if body.revision != (latest.revision if latest else 0):
        conflict()
    evidence = output_assessment(db, project, track, segment, output)["qc_evidence_fingerprint"]
    if body.qc_evidence_fingerprint != evidence:
        conflict()
    review = AudioReview(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        segment_id=segment.id,
        output_id=output.id,
        translation_revision_id=proof["translation_revision_id"],
        source_selection_id=proof["source_selection_id"],
        transcript_id=proof["transcript_id"],
        revision=body.revision + 1,
        actor_id=actor,
        decision=body.decision,
        note=body.note,
        qc_evidence_fingerprint=evidence,
        guard_snapshot=proof,
    )
    db.add(review)
    db.flush()
    changed(
        db,
        project,
        "voice_qc.listening_reviewed",
        segment_id=segment.id,
        revision=review.revision,
        action=review.decision,
    )
    return output_assessment(db, project, track, segment, output)


def review_json(row, current):
    return {
        "id": row.id,
        "output_id": row.output_id,
        "revision": row.revision,
        "decision": row.decision,
        "actor_id": row.actor_id,
        "note": row.note,
        "qc_evidence_fingerprint": row.qc_evidence_fingerprint,
        "current": current,
        "created_at": row.created_at,
    }


def review_history(db, project, track, segment, limit=100, offset=0):
    try:
        proof, *_ = current_proof(db, project, track, segment)
    except APIError:
        proof = None
    query = review_query(project, track, segment)
    return {
        "total": db.scalar(select(func.count()).select_from(query.subquery())),
        "items": [
            review_json(r, r.guard_snapshot == proof)
            for r in db.scalars(
                query.order_by(AudioReview.revision.desc()).limit(limit).offset(offset)
            )
        ],
    }


def output_assessment(db, project, track, segment, output):
    try:
        proof, selected, _ = current_proof(db, project, track, segment)
    except APIError:
        proof, selected = None, None
    review = db.scalar(
        review_query(project, track, segment).order_by(AudioReview.revision.desc()).limit(1)
    )
    lines = db.scalars(
        scope(VoiceQCLine, project)
        .where(VoiceQCLine.output_id == output.id)
        .order_by(VoiceQCLine.created_at.desc(), VoiceQCLine.id.desc())
        .limit(100)
    ).all()
    current = next((x for x in lines if x.guard_snapshot == proof), None)
    qc = {"status": "unassessed", "comparison": None, "request_id": None}
    if current:
        run = owned(db, StageRun, project, current.run_id)
        result = db.scalar(scope(VoiceQCResult, project).where(VoiceQCResult.line_id == current.id))
        qc = {
            "status": run.status,
            "comparison": result.comparison if result else None,
            "request_id": current.command_id,
            "line_id": current.id,
        }
    elif lines:
        qc["status"] = "stale"
    else:
        try:
            _, caps = verification_config(db, project)
            support = capability_status(caps, track.tag)
            if support != "supported":
                qc["status"] = support
        except APIError:
            qc["status"] = "unconfigured"
    evidence = fingerprint({"proof": proof, "output_id": output.id, "qc": qc})
    review_current = bool(
        review
        and review.guard_snapshot == proof
        and review.qc_evidence_fingerprint == evidence
        and selected is not None
        and selected.id == output.id
    )
    acceptance = (review.decision if review_current else "stale") if review else "not_assessed"
    issues = []
    if acceptance != "accepted":
        issues.append("LISTENING_" + acceptance.upper())
    if qc["status"] != "succeeded":
        issues.append("QC_" + qc["status"].upper())
    elif qc["comparison"] and (
        not qc["comparison"]["text_match"]
        or qc["comparison"]["reference_carryover"]
        or qc["comparison"]["language_status"]
        in {"mismatch", "not_reported", "unrecognized_report"}
    ):
        issues.append("QC_MANUAL_REVIEW")
    return {
        "acceptance": acceptance,
        "review_revision": review.revision if review else 0,
        "review": review_json(review, review_current) if review else None,
        "qc": qc,
        "qc_evidence_fingerprint": evidence,
        "ready": acceptance == "accepted" and selected is not None and selected.id == output.id,
        "readiness_basis": "manual_review" if acceptance == "accepted" else None,
        "qc_override": acceptance == "accepted" and bool(issues),
        "issues": issues,
    }

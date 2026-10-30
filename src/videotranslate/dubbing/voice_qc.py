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
        return same_meaning_proof(proof, line.guard_snapshot)
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
    for row, _, inputs, _ in captured:
        pending = db.scalar(
            scope(StageRun, project).where(
                StageRun.stage == "voice_qc",
                StageRun.target_language == track.tag,
                StageRun.segment_id == row.id,
                (StageRun.status.in_(ACTIVE)) | (StageRun.remote_state == "submitting"),
            )
        )
        uncertain = unresolved_recognition(db, project, fingerprint(inputs))
        if pending or uncertain:
            raise APIError(
                409,
                "SUBMISSION_UNCERTAIN"
                if uncertain
                or (pending.remote_state == "submitting" and pending.status not in ACTIVE)
                else "RUN_ACTIVE",
                "Existing recognition must finish or be explicitly reconciled",
            )
    intent = VoiceQCCommand(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        signature=signature,
        actor_id=actor,
        admission_sequence=project.event_sequence,
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
                target_language=track.tag,
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
        target_language=track.tag,
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
        recognition, comparison = (
            (record.recognition, record.comparison) if record else (None, None)
        )
        if record is None:
            from .qc_comparison import compare
            from .remote_voice_qc import cached_recognition

            try:
                payload, _ = cached_recognition(db, project, line)
                recognition = payload["recognition"] | {
                    "working_timings": payload["working_timings"]
                }
                comparison = compare(
                    line.comparison_input["expected"],
                    "".join(r["text"] for r in recognition["segments"]),
                    target=line.comparison_input["target"],
                    detected=recognition["detected_language"],
                    reference=line.comparison_input["reference"],
                )
            except (APIError, ValueError, KeyError, TypeError, AttributeError):
                pass
        result.append(
            {
                "id": line.id,
                "segment_id": line.segment_id,
                "output_id": line.output_id,
                "run_id": run.id,
                "status": run.status,
                "publication": line.publication,
                "current": line_current(db, project, line),
                "recognition": recognition,
                "comparison": comparison,
                "next_action": "acknowledge_uncertain_submission"
                if run.remote_state == "submitting" and run.status not in ACTIVE
                else "wait_for_recognition"
                if run.status in ACTIVE
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
    assessment = output_assessment(db, project, track, segment, output)
    evidence = assessment["qc_evidence_fingerprint"]
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
        qc_acknowledgement=assessment["qc_risks"],
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
        "qc_acknowledgement": row.qc_acknowledgement,
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
            review_json(r, same_meaning_proof(r.guard_snapshot, proof))
            for r in db.scalars(
                query.order_by(AudioReview.revision.desc()).limit(limit).offset(offset)
            )
        ],
    }


def output_assessment(db, project, track, segment, output):
    try:
        proof, selected, _ = current_proof(db, project, track, segment)
    except APIError as error:
        proof, selected = None, None
        proof_error = error.code
    else:
        proof_error = None
    review = db.scalar(
        review_query(project, track, segment).order_by(AudioReview.revision.desc()).limit(1)
    )
    qc = current_qc_evidence(db, project, track, output, proof)
    evidence = fingerprint({"proof": proof, "output_id": output.id, "qc": qc})
    review_current = bool(
        review
        and same_meaning_proof(review.guard_snapshot, proof)
        and selected is not None
        and selected.id == output.id
    )
    acceptance = (review.decision if review_current else "stale") if review else "not_assessed"
    issues = [proof_error] if proof_error else []
    if acceptance != "accepted":
        issues.append("LISTENING_" + acceptance.upper())
    if qc["status"] != "succeeded":
        issues.append("QC_" + qc["status"].upper())
    if qc["comparison"] and (
        not qc["comparison"]["text_match"]
        or qc["comparison"]["reference_carryover"]
        or qc["comparison"]["language_status"]
        in {"mismatch", "not_reported", "unrecognized_report"}
    ):
        issues.append("QC_MANUAL_REVIEW")
    risks = qc_risks(qc)
    acknowledged = not risks or bool(
        review_current and all(review.qc_acknowledgement.get(k) == v for k, v in risks.items())
    )
    if acceptance == "accepted" and not acknowledged:
        issues.append("QC_ACKNOWLEDGEMENT_REQUIRED")
    from .synthesis import inference_inputs

    natural_stale = True
    try:
        inputs, *_ = inference_inputs(db, project, track, segment)
        natural_stale = fingerprint(inputs) != output.input_fingerprint
    except (APIError, ValueError):
        pass
    if natural_stale:
        issues.append("NATURAL_AUDIO_STALE")
    ready = (
        acceptance == "accepted"
        and acknowledged
        and not natural_stale
        and selected is not None
        and selected.id == output.id
    )
    return {
        "acceptance": acceptance,
        "review_revision": review.revision if review else 0,
        "review": review_json(review, review_current) if review else None,
        "qc": qc,
        "qc_evidence_fingerprint": evidence,
        "qc_risks": risks,
        "qc_issues_acknowledged": acknowledged,
        "ready": ready,
        "readiness_basis": "manual_review" if ready else None,
        "qc_override": ready and any(i.startswith("QC_") for i in issues),
        "issues": issues,
    }


def current_qc_evidence(db, project, track, output, proof):
    # Project admission is durable; worker/app clocks and completion order are not.
    query = (
        scope(VoiceQCLine, project)
        .join(VoiceQCCommand, VoiceQCLine.command_id == VoiceQCCommand.id)
        .where(
            VoiceQCLine.output_id == output.id,
            VoiceQCCommand.project_id == project.id,
            VoiceQCCommand.workspace_id == project.workspace_id,
        )
        .order_by(VoiceQCCommand.admission_sequence.desc(), VoiceQCLine.id.desc())
    )
    qc = {"status": "unassessed", "comparison": None, "request_id": None, "evidence": None}
    if proof is None:
        applicable = query.where(False)
    else:
        applicable = query
        for key, value in proof.items():
            if key in {"translation_revision", "translation_revision_id"}:
                continue
            column = VoiceQCLine.guard_snapshot[key]
            column = column.as_integer() if type(value) is int else column.as_string()
            applicable = applicable.where(column == value)
    current = db.scalar(applicable.limit(1))
    # Inconclusive work cannot erase an observed result. Read the latest applicable
    # conclusive row independently, without scanning/truncating a pending history.
    evidence_line = db.scalar(
        applicable.join(VoiceQCResult, VoiceQCResult.line_id == VoiceQCLine.id)
        .where(
            VoiceQCResult.project_id == project.id,
            VoiceQCResult.workspace_id == project.workspace_id,
        )
        .limit(1)
    )
    if current:
        run = owned(db, StageRun, project, current.run_id)
        qc.update(status=run.status, request_id=current.command_id, line_id=current.id)
    elif db.scalar(query.limit(1)):
        qc["status"] = "stale"
    else:
        try:
            _, caps = verification_config(db, project)
            support = capability_status(caps, track.tag)
            if support != "supported":
                qc["status"] = support
        except APIError:
            qc["status"] = "unconfigured"
    if evidence_line:
        result = db.scalar(
            scope(VoiceQCResult, project).where(VoiceQCResult.line_id == evidence_line.id)
        )
        evidence_run = owned(db, StageRun, project, evidence_line.run_id)
        qc.update(
            comparison=result.comparison,
            evidence={
                "line_id": evidence_line.id,
                "request_id": evidence_line.command_id,
                "status": evidence_run.status,
            },
            recognized_text_fingerprint=fingerprint(
                "".join(row["text"] for row in result.recognition["segments"])
            ),
        )
    return qc


def qc_risks(qc):
    risks = {}
    if qc["status"] != "succeeded" and qc["status"] not in {"queued", "running", "retry_wait"}:
        risks["gap"] = qc["status"]
    comparison = qc["comparison"]
    if not comparison:
        if qc["status"] == "succeeded":
            risks["gap"] = "missing_comparison"
        return risks
    if not comparison["text_match"]:
        risks["text"] = fingerprint(
            {
                "comparison": comparison,
                "recognized_text_fingerprint": qc.get("recognized_text_fingerprint"),
            }
        )
    if comparison["reference_carryover"]:
        risks["reference_carryover"] = fingerprint(comparison["reference_carryover"])
    if comparison["language_status"] in {"mismatch", "unrecognized_report"}:
        risks["language"] = comparison["detected_language"]
    return risks


def target_readiness(db, project, track, transcript):
    from collections import Counter

    from .segments import active_segments_query

    query = active_segments_query(project, transcript.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    if total > 1000:
        return {
            "ready": False,
            "assessed_rows": 0,
            "ready_rows": 0,
            "issues": {"READINESS_ROW_LIMIT": total},
            "total": total,
        }
    issues, ready = Counter(), 0
    for segment in db.scalars(query.limit(1000)):
        selection = selection_for(db, project, track, segment)
        if not selection or not selection.current_version_id:
            issues["AUDIO_MISSING"] += 1
            continue
        version = owned(db, AudioSelectionVersion, project, selection.current_version_id)
        output = owned(db, NaturalOutput, project, version.output_id)
        assessment = output_assessment(db, project, track, segment, output)
        ready += int(assessment["ready"])
        issues.update(assessment["issues"])
    return {
        "ready": total > 0 and ready == total,
        "assessed_rows": total,
        "ready_rows": ready,
        "issues": dict(issues),
        "total": total,
    }


def unresolved_recognition(db, project, identity, exclude_run_id=None):
    query = (
        scope(StageRun, project)
        .join(VoiceQCLine, VoiceQCLine.run_id == StageRun.id)
        .where(
            VoiceQCLine.project_id == project.id,
            VoiceQCLine.workspace_id == project.workspace_id,
            VoiceQCLine.recognition_identity == identity,
            StageRun.remote_state == "submitting",
            StageRun.status.not_in(ACTIVE),
        )
    )
    if exclude_run_id:
        query = query.where(StageRun.id != exclude_run_id)
    return db.scalar(query.limit(1))


def earlier_active_recognition(db, project, line):
    """Serialize paid identities using project-locked event order, never wall clocks.

    All rows of a command commit together, so stable line IDs break intra-command
    ties. Later commands defer before CPU preparation and reuse the earlier success.
    No second lock/store or user acknowledgement is needed for ordinary active work.
    """
    intent = owned(db, VoiceQCCommand, project, line.command_id)
    return db.scalar(
        scope(StageRun, project)
        .join(VoiceQCLine, VoiceQCLine.run_id == StageRun.id)
        .join(VoiceQCCommand, VoiceQCLine.command_id == VoiceQCCommand.id)
        .where(
            VoiceQCLine.project_id == project.id,
            VoiceQCLine.workspace_id == project.workspace_id,
            VoiceQCCommand.project_id == project.id,
            VoiceQCCommand.workspace_id == project.workspace_id,
            VoiceQCLine.recognition_identity == line.recognition_identity,
            StageRun.id != line.run_id,
            StageRun.status.in_(ACTIVE),
            (VoiceQCCommand.admission_sequence < intent.admission_sequence)
            | (
                (VoiceQCCommand.admission_sequence == intent.admission_sequence)
                & (VoiceQCLine.id < line.id)
            ),
        )
        .limit(1)
    )


def same_meaning_proof(left, right):
    if left is None or right is None:
        return False
    # Exact revisions are retained for command/review CAS and audit. Freshness
    # follows wording, source and selected bytes, so approval-only target edits
    # do not pretend the reviewer never heard the same line.
    ignored = {"translation_revision_id", "translation_revision"}
    return fingerprint({k: v for k, v in left.items() if k not in ignored}) == fingerprint(
        {k: v for k, v in right.items() if k not in ignored}
    )

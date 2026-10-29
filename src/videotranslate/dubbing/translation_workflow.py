"""Guarded target translation commands, deterministic batches and manual suggestion apply."""

from urllib.parse import urlsplit

from sqlalchemy import select

from ..errors import APIError
from ..execution.inputs import (
    capture_inputs,
    fingerprint,
    initialize_inputs,
    is_current,
    set_inputs,
)
from ..execution.prepared import current_operation
from ..models.core import new_id
from ..models.dubbing import (
    ContextRevision,
    Segment,
    SegmentRevision,
    TranscriptRevision,
    TranslationRevision,
)
from ..models.execution import StageRun
from ..models.providers import WorkspaceCredential
from ..models.translation import TranslationCommand, TranslationPhase
from ..providers.hf_router import chat_data
from ..providers.network import validate_url
from .ownership import conflict, invalid, owned, owner, scope
from .remote_translation import (
    STAGE_PREFIX,
    estimate_ms,
    phase_result,
    publication_current,
    slot_ms,
)
from .segments import active_segment, active_segments_query
from .source import active_source
from .translations import track_for, translation_state, write_translation

BATCH_ROWS = 20
BATCH_BYTES = 48000


def validate_config(db, project, runtime, target):
    from .workflow import connection

    config = connection(db, project, "translation")
    if not config:
        raise APIError(409, "PROVIDER_REQUIRED", "Translation connection required")
    values = config.settings
    capability = (config.check_state or {}).get("capabilities", {})
    if target in capability.get("unsupported_languages", []) or (
        capability.get("language_support") == "unsupported"
        and target not in capability.get("supported_languages", [])
    ):
        raise APIError(
            422,
            "UNSUPPORTED_LANGUAGE",
            "This provider does not support the requested target; manual editing and import remain available",
        )
    hosts = {
        host.strip().lower() for host in runtime.provider_allowed_hosts.split(",") if host.strip()
    }
    endpoint = values.get("endpoint") or "https://router.huggingface.co/v1"
    try:
        validate_url(endpoint, allowed_hosts=hosts)
        host = urlsplit(endpoint).hostname
        adapter, credential = values["adapter"], values.get("credential_ref")
        if adapter not in {"hf_router", "openai_compatible"} or not values.get("model"):
            raise ValueError()
        if adapter == "hf_router" and (
            credential != "huggingface" or host != "router.huggingface.co"
        ):
            raise ValueError()
        if adapter == "openai_compatible" and (
            credential not in {None, "translation"} or host not in hosts
        ):
            raise ValueError()
        if credential and not db.scalar(
            select(WorkspaceCredential.id).where(
                WorkspaceCredential.workspace_id == project.workspace_id,
                WorkspaceCredential.kind == credential,
                WorkspaceCredential.ciphertext.is_not(None),
            )
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise APIError(
            409, "PROVIDER_REQUIRED", "Translation configuration is unavailable"
        ) from None
    return config


def row_guard(db, project, track, segment):
    state = translation_state(db, project, track, segment)
    revision = owned(db, TranslationRevision, project, state.current_revision_id) if state else None
    return {
        "revision": state.revision if state else 0,
        "locked": state.locked if state else False,
        "approved": bool(revision and revision.approved and not state.stale),
    }


def batches(rows):
    import json

    result, current, size = [], [], 0
    for row in rows:
        count = len(json.dumps(row, ensure_ascii=False).encode())
        if current and (len(current) == BATCH_ROWS or size + count > BATCH_BYTES):
            result.append(current)
            current, size = [], 0
        current.append(row)
        size += count
    if current:
        result.append(current)
    return result


def command(db, project, tag, body, actor, runtime):
    initialize_inputs(db, project)
    _, selection, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    if track.revision != body.track_revision or len({row.id for row in body.segments}) != len(
        body.segments
    ):
        conflict()
    config = validate_config(db, project, runtime, track.tag)
    context = owned(db, ContextRevision, project, track.context_revision_id)
    supplied = {"supplied_summary": context.summary}
    requested = {row.id: row for row in body.segments}
    selected_rows, requested_rows, heads, skipped = [], [], {}, []
    all_rows = []
    for segment in db.scalars(active_segments_query(project, transcript.id)):
        revision = owned(db, SegmentRevision, project, segment.current_revision_id)
        row = {"id": segment.id, "text": revision.text}
        all_rows.append(row)
        if segment.id not in requested:
            continue
        requested_rows.append(row)
        given, actual = requested[segment.id], row_guard(db, project, track, segment)
        if (
            given.expected_source_text_fingerprint != fingerprint(revision.text)
            or {k: getattr(given, k) for k in actual} != actual
        ):
            conflict()
        if (actual["locked"] or actual["approved"]) and not body.force_replace:
            skipped.append(segment.id)
        else:
            selected_rows.append(row)
            heads[segment.id] = actual
    if set(requested) != {row["id"] for row in all_rows if row["id"] in requested}:
        invalid()
    source_rows = all_rows if track.mode != "Fast" else requested_rows
    payload = {
        "target": track.tag,
        "mode": track.mode,
        "track_revision": track.revision,
        "context_revision_id": context.id,
        "context": supplied,
        "glossary": context.glossary,
        "source_rows": source_rows,
        "batches": batches(selected_rows),
        "connection_revision": config.revision,
        "config": config.settings,
        "source_language": project.source_language,
        "force_replace": body.force_replace,
        "initial_row_heads": heads,
        "skipped_ids": skipped,
    }
    # Whole-context extraction is supported as one bounded call; oversized input is rejected here.
    try:
        for request_rows in payload["batches"] if track.mode == "Fast" else [source_rows]:
            chat_data(
                target=track.tag,
                segments=request_rows,
                phase="context" if track.mode != "Fast" else "draft",
                context=supplied,
                glossary=context.glossary,
            )
    except ValueError:
        raise APIError(
            422, "CONTEXT_LIMIT", "Whole source context exceeds the supported request bound"
        ) from None
    signature_data = {
        k: v for k, v in payload.items() if k not in {"initial_row_heads", "skipped_ids", "batches"}
    }
    if body.force_replace:
        signature_data["force_row_heads"] = heads
    signature = fingerprint(
        signature_data
        | {
            "selection": selection.id,
            "transcript": transcript.id,
            "selected_ids": [row["id"] for row in requested_rows],
        }
    )
    prior = db.scalar(
        scope(TranslationCommand, project).where(TranslationCommand.signature == signature)
    )
    if prior:
        return command_json(db, project, prior)
    if not selected_rows:
        raise APIError(409, "TRANSLATION_PROTECTED", "All requested rows are locked or approved")
    # Protect only overlapping selected rows or the same unresolved shared context.
    # Independent Fast rows do not wait for another row's unknown provider outcome.
    selected_ids = {row["id"] for row in selected_rows}
    expected_context = {
        "target": payload["target"],
        "segments": payload["source_rows"],
        "phase": "context",
        "context": payload["context"],
        "glossary": payload["glossary"],
        "source_language": payload["source_language"],
        "connection_revision": payload["connection_revision"],
        "config": payload["config"],
    }
    for uncertain in db.scalars(
        scope(StageRun, project).where(
            StageRun.stage.like("translation_%"),
            StageRun.target_language == track.tag,
            StageRun.remote_state == "submitting",
        )
    ):
        prior_phase_row = db.scalar(
            scope(TranslationPhase, project).where(TranslationPhase.run_id == uncertain.id)
        )
        if prior_phase_row is None:
            continue
        prior_intent = owned(db, TranslationCommand, project, prior_phase_row.command_id)
        operation = current_operation(db, uncertain)
        prior_input = operation.request_payload if operation else prior_phase_row.input_payload
        prior_ids = (
            {row["id"] for batch in prior_intent.payload["batches"] for row in batch}
            if prior_phase_row.phase == "context"
            else {row["id"] for row in prior_input["segments"]}
        )
        same_context = (
            payload["mode"] != "Fast"
            and prior_phase_row.phase == "context"
            and prior_input == expected_context
        )
        if selected_ids.intersection(prior_ids) or same_context:
            raise APIError(
                409,
                "SUBMISSION_UNCERTAIN",
                "Overlapping translation work needs explicit acknowledgement before another request",
            )
    intent = TranslationCommand(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        selection_id=selection.id,
        transcript_id=transcript.id,
        signature=signature,
        actor_id=actor,
        payload=payload,
        row_heads=heads,
    )
    db.add(intent)
    db.flush()
    if track.mode == "Fast":
        for index in range(len(payload["batches"])):
            queue_phase(db, project, intent, "draft", index)
    else:
        queue_phase(db, project, intent, "context", 0)
    from ..execution.events import append_event

    append_event(
        db,
        project,
        "translation.queued",
        facts={
            "workflow_id": intent.id,
            "target_language": track.tag,
            "action": "force_replace" if body.force_replace else "translate",
            "count": len(selected_rows),
        },
    )
    return command_json(db, project, intent)


def phase_rows(db, project, intent):
    return db.scalars(
        scope(TranslationPhase, project)
        .where(TranslationPhase.command_id == intent.id)
        .order_by(TranslationPhase.batch_index, TranslationPhase.created_at, TranslationPhase.id)
    ).all()


def prior_phase(db, project, intent, name, index):
    return db.scalar(
        scope(TranslationPhase, project).where(
            TranslationPhase.command_id == intent.id,
            TranslationPhase.phase == name,
            TranslationPhase.batch_index == index,
        )
    )


def queue_phase(db, project, intent, name, index, parent=None):
    from ..execution.contracts import RunCreate
    from ..execution.service import create_run

    if prior_phase(db, project, intent, name, index):
        return
    payload = intent.payload
    context, glossary = dict(payload["context"]), dict(payload["glossary"])
    if intent.generated_context_id:
        generated = owned(db, ContextRevision, project, intent.generated_context_id)
        context["generated_summary"] = generated.summary
        glossary = generated.glossary | glossary
    rows = payload["source_rows"] if name == "context" else payload["batches"][index]
    inputs = {
        "target": payload["target"],
        "segments": rows,
        "phase": name,
        "context": context,
        "glossary": glossary,
        "source_language": payload["source_language"],
        "connection_revision": payload["connection_revision"],
        "config": payload["config"],
    }
    dependencies = [
        "source.selection",
        "source.transcript",
        "source.language",
        "provider.translation",
        f"target.{payload['target']}.context",
        f"target.{payload['target']}.glossary",
        f"target.{payload['target']}.mode",
        f"target.{payload['target']}.active",
    ]
    used = payload["source_rows"] if payload["mode"] != "Fast" else rows
    for row in used:
        dependencies.append(f"segment.{row['id']}.text")
    if name in {"critique", "rewrite", "shorten"}:
        draft = prior_phase(db, project, intent, "draft", index)
        inputs["draft"] = phase_result(db, project, draft)["segments"]
    if name in {"rewrite", "shorten"}:
        critique = prior_phase(db, project, intent, "critique", index)
        inputs["critique"] = phase_result(db, project, critique)["segments"]
    if name == "shorten":
        rewrite = prior_phase(db, project, intent, "rewrite", index)
        inputs["draft"] = phase_result(db, project, rewrite)["segments"]
        slots = {}
        for row in rows:
            segment = active_segment(
                db, project, owned(db, TranscriptRevision, project, intent.transcript_id), row["id"]
            )
            revision = owned(db, SegmentRevision, project, segment.current_revision_id)
            slots[row["id"]] = {"start_ms": revision.start_ms, "end_ms": revision.end_ms}
            dependencies.append(f"segment.{row['id']}.timing")
        inputs["context"] = context | {"estimated_slots": slots}
    digest = fingerprint(inputs)
    key = "translation.input:" + digest
    set_inputs(db, project, {key: inputs})
    snapshot = capture_inputs(db, project, [key, *dependencies])
    phase = TranslationPhase(
        id=new_id(),
        **owner(project),
        command_id=intent.id,
        phase=name,
        batch_index=index,
        parent_phase_id=parent.id if parent else None,
        input_payload=inputs,
        input_fingerprint=digest,
        dependency_snapshot=snapshot,
        guard_snapshot={
            row["id"]: intent.row_heads[row["id"]] for row in rows if row["id"] in intent.row_heads
        },
    )
    db.add(phase)
    db.flush()
    run = create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(
            stage=STAGE_PREFIX + name,
            target_language=payload["target"],
            options={"phase_id": phase.id},
        ),
        idempotency_key="translation:" + phase.id,
        guarded_command=True,
    )
    phase.run_id = run.id
    db.flush()


def command_json(db, project, intent):
    phases = phase_rows(db, project, intent)
    public, suggestions = [], []
    for phase in phases:
        run = owned(db, StageRun, project, phase.run_id)
        public.append(
            {
                "id": phase.id,
                "phase": phase.phase,
                "batch_index": phase.batch_index,
                "run_id": run.id,
                "status": run.status,
                "publication": phase.publication,
            }
        )
        if phase.phase == "shorten" and phase.publication:
            try:
                output = phase_result(db, project, phase)
                for segment_id, text in output["segments"].items():
                    suggestions.append(
                        {
                            "phase_id": phase.id,
                            "segment_id": segment_id,
                            "text": text,
                            "estimated": True,
                            "estimated_duration_ms": estimate_ms(text, intent.payload["target"]),
                            "fit_guaranteed": False,
                            "stale": not is_current(db, project, phase.dependency_snapshot)
                            or not publication_current(db, run),
                            "applied": phase.applied,
                        }
                    )
            except ValueError:
                pass
    statuses = [row["status"] for row in public]
    if any(value in {"queued", "running", "retry_wait", "cancelling"} for value in statuses):
        status, action = "running", None
    elif any(value in {"failed", "needs_review", "cancelled", "stale"} for value in statuses):
        status, action = "incomplete", "retry_translation_phase"
    elif any(
        not publication_current(db, owned(db, StageRun, project, phase.run_id))
        for phase in phases
        if phase.phase != "shorten"
    ):
        status, action = "incomplete", "review_translation_changes"
    else:
        status, action = "review", "translation_review"
    estimates = []
    if intent.payload["mode"] == "Autofit":
        track = track_for(db, project, intent.payload["target"], active=False)
        for batch in intent.payload["batches"]:
            for row in batch:
                segment = owned(db, Segment, project, row["id"])
                state = translation_state(db, project, track, segment)
                if state:
                    revision = owned(db, TranslationRevision, project, state.current_revision_id)
                    duration = estimate_ms(revision.text, track.tag)
                    estimates.append(
                        {
                            "segment_id": segment.id,
                            "estimated_duration_ms": duration,
                            "slot_ms": slot_ms(db, project, segment.id),
                            "provenance": "estimated_language_rate_v1"
                            if duration is not None
                            else "unknown",
                            "fit_guaranteed": False,
                        }
                    )
    return {
        "estimates": estimates,
        "id": intent.id,
        "target_language": intent.payload["target"],
        "mode": intent.payload["mode"],
        "status": status,
        "next_action": action,
        "segment_ids": [row["id"] for batch in intent.payload["batches"] for row in batch],
        "skipped_ids": intent.payload["skipped_ids"],
        "generated_context_revision_id": intent.generated_context_id,
        "phases": public,
        "suggestions": suggestions,
    }


def apply_suggestion(db, project, tag, command_id, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    intent = owned(db, TranslationCommand, project, command_id)
    phase = owned(db, TranslationPhase, project, body.phase_id)
    if (
        intent.track_id != track.id
        or phase.command_id != intent.id
        or phase.phase != "shorten"
        or phase.applied
    ):
        conflict()
    run = owned(db, StageRun, project, phase.run_id)
    if (
        run.status != "succeeded"
        or not is_current(db, project, phase.dependency_snapshot)
        or not publication_current(db, run)
    ):
        conflict()
    output = phase_result(db, project, phase)
    ids = {row.id for row in body.segments}
    if len(ids) != len(body.segments) or ids != set(output["segments"]):
        invalid()
    facets, revisions, heads = {}, {}, dict(intent.row_heads)
    for row in body.segments:
        segment = active_segment(db, project, transcript, row.id)
        actual = row_guard(db, project, track, segment)
        if (
            {k: getattr(row, k) for k in actual} != actual
            or actual["locked"]
            or actual["approved"]
            or actual != phase.guard_snapshot[row.id]
        ):
            conflict()
        state = write_translation(
            db,
            project,
            track,
            segment,
            row.revision,
            output["segments"][row.id],
            actor,
            expected_source_text_fingerprint=row.expected_source_text_fingerprint,
            approved=False,
            provenance="cloud_shorter_applied",
            force_locked=False,
            input_facets=facets,
        )
        revisions[row.id] = state.current_revision_id
        heads[row.id] = row_guard(db, project, track, segment)
    phase.applied = True
    phase.publication = phase.publication | {"applied_revision_ids": revisions}
    intent.row_heads = heads
    set_inputs(db, project, facets)
    return command_json(db, project, intent)

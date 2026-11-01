"""Remote structured chat: one operation per phase, private success before publication."""

from urllib.parse import urlsplit

from sqlalchemy import select

from ..errors import APIError
from ..execution.contracts import FailureCode, StageFailure, StageResult
from ..execution.inputs import (
    capture_inputs,
    fingerprint,
    is_current,
    set_inputs,
)
from ..execution.prepared import Operations, bounded, current_operation
from ..execution.provider_runtime import make_http
from ..models.core import Project, new_id, utcnow
from ..models.dubbing import (
    ContextRevision,
    Segment,
    SegmentRevision,
    TranscriptRevision,
)
from ..models.execution import StageRun
from ..models.providers import WorkspaceCredential
from ..models.translation import TranslationCommand, TranslationPhase
from ..providers.chat import chat_data, normalize_chat, structured_chat
from ..providers.network import validate_url
from .ownership import invalid, owned, owner, scope
from .segments import active_segment, active_segments_query
from .source import current_selection, source_state
from .translation_contracts import PhaseOptions
from .translations import track_for, write_translation

STAGE_PREFIX = "translation_"


def phase_result(db, project, phase):
    """Cache validity is independent from publisher/editor state."""
    run = owned(db, StageRun, project, phase.run_id)
    checked, _ = phase_for(db, project, run)
    if checked.id != phase.id:
        raise ValueError("Invalid cached phase ownership")
    operation = current_operation(db, run)
    if (
        not operation
        or operation.phase != "prepared"
        or operation.request_payload != phase.input_payload
        or fingerprint(phase.input_payload) != phase.input_fingerprint
        or run.dependency_snapshot != phase.dependency_snapshot
    ):
        raise ValueError("Invalid translation operation lineage")
    payload = operation.prepared_payload
    bounded(payload)
    if (
        set(payload) != {"output", "input_fingerprint"}
        or payload["input_fingerprint"] != phase.input_fingerprint
    ):
        raise ValueError("Invalid translation cache")
    output = payload["output"]
    if (
        not isinstance(output, dict)
        or output.get("target_language") != phase.input_payload["target"]
    ):
        raise ValueError("Invalid cached target identity")
    metadata = output.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Invalid translation metadata")
    value = {k: v for k, v in output.items() if k != "metadata"}
    raw = {"target_language": phase.input_payload["target"], **value}
    if "segments" in raw:
        raw["segments"] = [{"id": k, "text": v} for k, v in raw["segments"].items()]
    validated = normalize_chat(
        raw,
        target=phase.input_payload["target"],
        ids=[row["id"] for row in phase.input_payload["segments"]],
        phase=phase.phase,
    )
    # Revalidate metadata rather than trusting a manually altered private payload.
    from ..providers.chat import actual_metadata

    expected = actual_metadata(
        {
            "id": metadata.get("response_id"),
            "request_id": metadata.get("request_id"),
            "usage": metadata.get("usage"),
        }
    )
    if expected != metadata:
        raise ValueError("Invalid actual provider metadata")
    bounded(operation.public_facts, 65536)
    facts = operation.public_facts
    if (
        type(facts.get("reused")) is not bool
        or type(facts.get("segment_count")) is not int
        or facts
        != {
            "phase": phase.phase,
            "segment_count": len(phase.input_payload["segments"]),
            "target_language": phase.input_payload["target"],
            "reused": facts["reused"],
            **metadata,
        }
    ):
        raise ValueError("Invalid safe translation facts")
    return validated | {"target_language": phase.input_payload["target"], "metadata": metadata}


def phase_options(options):
    try:
        return PhaseOptions.model_validate(options).model_dump()
    except ValueError:
        raise APIError(422, "INVALID_OPTIONS", "Translation requires a guarded command") from None


def phase_scope(request):
    return phase_options(request.options)["phase_id"]


def phase_for(db, project, request):
    options = phase_options(request.options)
    phase = owned(db, TranslationPhase, project, options["phase_id"])
    intent = owned(db, TranslationCommand, project, phase.command_id)
    if (
        request.segment_id is not None
        or request.target_language != intent.payload["target"]
        or request.stage != STAGE_PREFIX + phase.phase
    ):
        invalid()
    inputs = phase.input_payload
    if (
        inputs.get("phase") != phase.phase
        or inputs.get("target") != intent.payload["target"]
        or fingerprint(inputs) != phase.input_fingerprint
        or phase.dependency_snapshot.get("translation.input:" + phase.input_fingerprint)
        != phase.input_fingerprint
    ):
        invalid()
    expected_parent = {
        "context": None,
        "draft": None if intent.payload["mode"] == "Fast" else "context",
        "critique": "draft",
        "rewrite": "critique",
        "shorten": "rewrite",
    }[phase.phase]
    if expected_parent is None:
        if phase.parent_phase_id is not None:
            invalid()
    else:
        parent = owned(db, TranslationPhase, project, phase.parent_phase_id)
        if (
            parent.command_id != intent.id
            or parent.phase != expected_parent
            or parent.batch_index != (0 if expected_parent == "context" else phase.batch_index)
        ):
            invalid()
    return phase, intent


def phase_inputs(db, project, request):
    phase, _ = phase_for(db, project, request)
    # Return actual named values; retry cannot relabel old paid input as new.
    snapshot = capture_inputs(db, project, list(phase.dependency_snapshot))
    if snapshot != phase.dependency_snapshot:
        raise APIError(
            409, "INPUT_REQUIRED", "Translation inputs changed; start a current guarded command"
        )
    return snapshot


def handler(context):
    operations = Operations(context)
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        phase, intent = phase_for(db, project, run)
        inputs = phase.input_payload
        if phase.run_id != run.id:
            raise StageFailure(FailureCode.CONFIGURATION)
        existing = current_operation(db, run)
        if existing and existing.phase == "prepared":
            try:
                phase_result(db, project, phase)
            except (APIError, ValueError, TypeError, AttributeError):
                raise StageFailure(FailureCode.CONFIGURATION) from None
            return StageResult(existing.public_facts, existing.id)
        reusable = None
        for candidate in db.scalars(
            scope(TranslationPhase, project).where(
                TranslationPhase.input_fingerprint == phase.input_fingerprint,
                TranslationPhase.id != phase.id,
            )
        ):
            if candidate.input_payload != inputs or not is_current(
                db, project, candidate.dependency_snapshot
            ):
                continue
            try:
                reusable = phase_result(db, project, candidate)
                break
            except (APIError, ValueError, TypeError, AttributeError):
                continue
        config = inputs["config"]
        if reusable is None:
            from .translation_workflow import validate_config

            try:
                current = validate_config(db, project, context.settings, inputs["target"])
                if current.revision != inputs["connection_revision"] or current.settings != config:
                    raise ValueError("Connection revision changed")
            except (APIError, ValueError):
                raise StageFailure(FailureCode.CONFIGURATION) from None
        credential = (
            db.scalar(
                select(WorkspaceCredential).where(
                    WorkspaceCredential.workspace_id == project.workspace_id,
                    WorkspaceCredential.kind == config.get("credential_ref"),
                )
            )
            if reusable is None and config.get("credential_ref")
            else None
        )
        from ..providers.vault import decrypt_credential

        try:
            token = (
                decrypt_credential(context.settings, project.workspace_id, credential.ciphertext)
                if credential and credential.ciphertext
                else None
            )
        except ValueError:
            raise StageFailure(FailureCode.AUTHENTICATION) from None
    endpoint = config.get("endpoint") or "https://router.huggingface.co/v1"
    parts = urlsplit(endpoint)
    operations.prepare(
        provider=config["adapter"],
        model=config["model"],
        connection_revision=inputs["connection_revision"],
        host=f"{parts.scheme}://{parts.netloc}",
        prefix=parts.path,
        request_payload=inputs,
    )
    if reusable is None:
        http = make_http(context)
        try:
            # Validate all input/host constraints before the submission boundary.
            try:
                chat_data(
                    **{
                        k: inputs[k]
                        for k in (
                            "target",
                            "segments",
                            "phase",
                            "context",
                            "glossary",
                            "draft",
                            "critique",
                        )
                        if k in inputs
                    }
                )
                validate_url(endpoint, allowed_hosts=http.allowed_hosts)
            except ValueError:
                raise StageFailure(FailureCode.CONFIGURATION) from None
            operations.begin()
            try:
                output = structured_chat(
                    http,
                    model=config["model"],
                    token=token,
                    endpoint=endpoint,
                    credential_kind=config.get("credential_ref"),
                    **{
                        k: inputs[k]
                        for k in (
                            "target",
                            "segments",
                            "phase",
                            "context",
                            "glossary",
                            "draft",
                            "critique",
                        )
                        if k in inputs
                    },
                )
            except (ValueError, TimeoutError, OSError):
                # A synchronous request can have reached the provider; never auto-POST it again.
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN) from None
        finally:
            http.close()
    else:
        output = reusable
    facts = {
        "phase": phase.phase,
        "segment_count": len(inputs["segments"]),
        "target_language": inputs["target"],
        "reused": reusable is not None,
        **output["metadata"],
    }
    return operations.cache({"output": output, "input_fingerprint": phase.input_fingerprint}, facts)


def publication_current(db, run):
    from .translation_workflow import row_guard
    from .workflow import connection

    project = db.get(Project, run.project_id)
    try:
        phase, intent = phase_for(db, project, run)
        if phase.run_id != run.id:
            return False
        config = connection(db, project, "translation")
        if not config or config.revision != intent.payload["connection_revision"]:
            return False
        state = source_state(db, project)
        selection = current_selection(db, project)
        track = track_for(db, project, intent.payload["target"])
        if (
            selection.id != intent.selection_id
            or state.transcript_id != intent.transcript_id
            or track.id != intent.track_id
            or track.revision != intent.payload["track_revision"]
            or track.context_revision_id != intent.payload["context_revision_id"]
        ):
            return False
        transcript = owned(db, TranscriptRevision, project, intent.transcript_id)
        for row in phase.input_payload["segments"]:
            segment = active_segment(db, project, transcript, row["id"])
            revision = owned(db, SegmentRevision, project, segment.current_revision_id)
            if revision.text != row["text"]:
                return False
            if (
                phase.phase != "context"
                and row_guard(db, project, track, segment) != intent.row_heads[row["id"]]
            ):
                return False
        # Whole-source auto-context is a real dependency of every refinement batch.
        if intent.payload["mode"] != "Fast":
            actual = [
                {
                    "id": seg.id,
                    "text": owned(db, SegmentRevision, project, seg.current_revision_id).text,
                }
                for seg in db.scalars(active_segments_query(project, transcript.id))
            ]
            if actual != intent.payload["source_rows"]:
                return False
        return True
    except (APIError, ValueError, KeyError):
        return False


def publish(db, run, result):
    from .translation_workflow import queue_phase, row_guard

    project = db.get(Project, run.project_id)
    phase, intent = phase_for(db, project, run)
    operation = current_operation(db, run)
    if not operation or result.prepared_id != operation.id:
        raise ValueError("Mismatched translation publication")
    output = phase_result(db, project, phase)
    track = track_for(db, project, intent.payload["target"])
    if phase.phase == "context":
        generated = ContextRevision(
            id=new_id(),
            **owner(project),
            track_id=track.id,
            parent_revision_id=intent.payload["context_revision_id"],
            summary=output["summary"],
            glossary=output["glossary"],
            actor_id=intent.actor_id,
            provenance="generated",
        )
        db.add(generated)
        db.flush()
        intent.generated_context_id = generated.id
        phase.publication = {"context_revision_id": generated.id}
        # Do not replace supplied context or change any inference dependency.
        for index in range(len(intent.payload["batches"])):
            queue_phase(db, project, intent, "draft", index, phase)
    elif phase.phase in {"draft", "rewrite"}:
        revisions, heads, facets = {}, dict(intent.row_heads), {}
        transcript = owned(db, TranscriptRevision, project, intent.transcript_id)
        for row in phase.input_payload["segments"]:
            segment = active_segment(db, project, transcript, row["id"])
            state = write_translation(
                db,
                project,
                track,
                segment,
                heads[segment.id]["revision"],
                output["segments"][segment.id],
                intent.actor_id,
                expected_source_text_fingerprint=fingerprint(row["text"]),
                approved=False,
                provenance="cloud_" + phase.phase,
                force_locked=intent.payload["force_replace"],
                input_facets=facets,
            )
            heads[segment.id] = row_guard(db, project, track, segment)
            revisions[segment.id] = state.current_revision_id
        intent.row_heads, phase.publication = heads, {"revision_ids": revisions}
        set_inputs(db, project, facets)
        if phase.phase == "draft" and intent.payload["mode"] != "Fast":
            queue_phase(db, project, intent, "critique", phase.batch_index, phase)
        elif phase.phase == "rewrite" and intent.payload["mode"] == "Autofit":
            if any(
                (estimate_ms(text, intent.payload["target"]) or 0)
                > slot_ms(db, project, segment_id)
                for segment_id, text in output["segments"].items()
            ):
                queue_phase(db, project, intent, "shorten", phase.batch_index, phase)
    elif phase.phase == "critique":
        phase.publication = {"critique_operation_id": operation.id}
        queue_phase(db, project, intent, "rewrite", phase.batch_index, phase)
    elif phase.phase == "shorten":
        phase.publication = {"suggestion": True}


def estimate_ms(text, target):
    """Conservative declared heuristics for a small known set, never a TTS guarantee."""
    code = target.split("-")[0]
    if code in {"zh", "ja"}:
        return round(len(text.strip()) / 4 * 1000)
    if code in {"en", "es", "fr", "de", "it", "pt"}:
        return round(len(text.split()) / 2.5 * 1000)
    return None


def slot_ms(db, project, segment_id):
    segment = owned(db, Segment, project, segment_id)
    revision = owned(db, SegmentRevision, project, segment.current_revision_id)
    return revision.end_ms - revision.start_ms


def retire_obsolete_uncertainty(db, project, run):
    """Explicit acknowledgement retires an obsolete command locally, never its unknown history."""
    if (
        run.stage
        not in {
            STAGE_PREFIX + phase for phase in ("context", "draft", "critique", "rewrite", "shorten")
        }
        or run.status not in {"failed", "stale", "needs_review", "cancelled"}
        or run.lease_token is not None
        or run.remote_state != "submitting"
        or run.remote_id is not None
    ):
        return False
    phase, _ = phase_for(db, project, run)
    # Lifecycle/permission guards are not inference input changes. In particular,
    # a manual target save or lock must not silently retire an unknown paid call.
    actual_inputs = {
        key: value
        for key, value in phase.dependency_snapshot.items()
        if not (key.startswith("target.") and key.endswith(".active"))
    }
    if is_current(db, project, actual_inputs):
        return False
    # Displace only the current-generation pointer. The old PrivateOperation keeps
    # its submitting phase, generation and captured request for reconciliation.
    run.request_key = None
    run.remote_state = "not_submitted"
    run.provider = run.model = None
    run.status, run.is_stale = "stale", True
    run.safe_error = run.result = None
    run.finished_at = run.updated_at = utcnow()
    from ..execution.events import append_event

    append_event(
        db,
        project,
        "run.uncertainty_acknowledged",
        run=run,
        facts={"recovery": "retire_obsolete_generation"},
    )
    return True

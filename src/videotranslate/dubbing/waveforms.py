"""Owned waveform discovery and guarded command admission. Reads never compute."""

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import capture_inputs, fingerprint, is_current
from ..execution.prepared import current_operation
from ..models.analysis import PreparedObject
from ..models.core import Asset, Project
from ..models.dubbing import LanguageTrack, Segment
from ..models.execution import StageRun
from ..models.synthesis import AudioSelection, AudioSelectionVersion, NaturalOutput
from .analysis import media_for
from .ownership import conflict, not_found, owned, scope
from .source import active_source
from .synthesis import inference_inputs
from .synthesis_cache import validate_output_evidence
from .waveforms_contracts import WaveformOptions

STAGE = "waveform_envelope"


def preparation_required():
    raise APIError(409, "WAVEFORM_PREPARATION_REQUIRED", "Prepare current working PCM audio first")


def capture(db, project, body):
    _, selection, _ = active_source(db, project, body.guard)
    proof = dict(
        selection_id=selection.id,
        selection_revision=selection.revision,
        transcript_revision=body.guard.transcript_revision,
        source_start_ms=selection.start_ms,
        source_end_ms=selection.end_ms,
    )
    if body.kind == "source":
        try:
            media = media_for(db, project, "extract")
        except APIError:
            preparation_required()
        if not media.working_asset_id:
            preparation_required()
        asset = owned(db, Asset, project, media.working_asset_id)
        # The current extraction manifest must own this exact selected-window object.
        extract_run = owned(db, StageRun, project, media.run_id)
        operation = current_operation(db, extract_run)
        record = db.scalar(
            scope(PreparedObject, project).where(PreparedObject.asset_id == asset.id)
        )
        payload = operation.prepared_payload if operation else None
        if (
            not operation
            or operation.phase != "prepared"
            or type(payload) is not dict
            or payload.get("selection_id") != selection.id
            or not record
            or record.operation_id != operation.id
            or record.id not in payload.get("objects", [])
            or record.state != "published"
            or not record.write_settled
            or record.delete_pending
            or record.storage_key != asset.storage_key
            or record.metadata_json.get("kind") != "working_audio"
            or record.metadata_json.get("sha256") != asset.sha256
            or record.metadata_json.get("byte_size") != asset.byte_size
            or record.metadata_json.get("codec") != "pcm_s16le"
            or record.metadata_json.get("container") != "wav"
        ):
            preparation_required()
        proof.update(extract_run_id=media.run_id, clock="source_selection_relative")
    else:
        output = owned(db, NaturalOutput, project, body.output_id)
        segment = owned(db, Segment, project, output.segment_id)
        track = owned(db, LanguageTrack, project, output.track_id)
        inputs, *_ = inference_inputs(db, project, track, segment)
        selected = db.scalar(
            scope(AudioSelection, project).where(
                AudioSelection.track_id == track.id, AudioSelection.segment_id == segment.id
            )
        )
        version = (
            owned(db, AudioSelectionVersion, project, selected.current_version_id)
            if selected and selected.current_version_id
            else None
        )
        if (
            not version
            or version.output_id != output.id
            or version.track_id != track.id
            or version.segment_id != segment.id
            or output.input_fingerprint != fingerprint(inputs)
        ):
            conflict()
        try:
            validate_output_evidence(db, project, output)
        except (ValueError, TypeError, KeyError, AttributeError):
            preparation_required()
        asset = owned(db, Asset, project, output.audio_asset_id)
        if asset.sha256 != output.sha256:
            preparation_required()
        proof.update(
            output_id=output.id,
            output_fingerprint=output.input_fingerprint,
            selection_version_id=version.id,
            audio_selection_revision=version.revision,
            segment_id=segment.id,
            track_id=track.id,
            clock="natural_audio_relative",
            natural_duration_ms=output.duration_ms,
        )
    if asset.content_type != "audio/wav" or asset.kind not in {"working_audio", "natural_audio"}:
        preparation_required()
    proof.update(asset_id=asset.id, input_sha256=asset.sha256, input_byte_size=asset.byte_size)
    return proof, asset


def options(value):
    try:
        return WaveformOptions.model_validate(value).model_dump()
    except ValueError:
        raise APIError(422, "INVALID_OPTIONS", "Guarded waveform request required") from None


def inputs(db, project, request):
    body = WaveformOptions.model_validate(request.options)
    if request.target_language is not None or request.segment_id is not None:
        raise APIError(422, "INVALID_SCOPE", "Waveforms use an owned audio input")
    proof, _ = capture(db, project, body)
    if fingerprint(proof) != fingerprint(body.proof):
        conflict()
    facets = ["source.selection", "source.window"]
    if body.kind == "source":
        facets.append("output.extract")
    return capture_inputs(db, project, facets)


def command_scope(request):
    return fingerprint(request.options)[:40]


def publication_current(db, run):
    try:
        project = db.get(Project, run.project_id)
        return (
            run.stage == STAGE
            and project.deleted_at is None
            and inputs(db, project, run) == run.dependency_snapshot
            and is_current(db, project, run.dependency_snapshot)
        )
    except (APIError, ValueError, TypeError, KeyError, AttributeError):
        return False


def admit(db, project, body):
    from ..execution.service import create_run

    proof, _ = capture(db, project, body)
    run = create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(stage=STAGE, options=body.model_dump() | {"proof": proof}),
        reuse_active=True,
        guarded_command=True,
    )
    run.independently_requested = True
    return run


def artifact_record(db, project, run):
    op = current_operation(db, run)
    if not op or op.phase != "prepared":
        return None
    payload = op.prepared_payload
    if (
        type(payload) is not dict
        or set(payload) != {"binding", "objects", "entry"}
        or payload["binding"] != binding(run, op)
        or type(payload["objects"]) is not list
        or len(payload["objects"]) != 1
        or type(payload["entry"]) is not dict
    ):
        return None
    entry = payload["entry"]
    record = db.scalar(
        scope(PreparedObject, project).where(PreparedObject.id == payload["objects"][0])
    )
    if not record:
        return None
    if (
        record.operation_id != op.id
        or record.state not in {"orphan", "published"}
        or not record.write_settled
        or record.delete_pending
        or record.storage_key != f"{project.workspace_id}/{project.id}/prepared/{record.id}"
        or entry
        != dict(
            object_id=record.id,
            kind="waveform",
            format="json",
            metadata={
                k: v
                for k, v in record.metadata_json.items()
                if k not in {"kind", "format", "content_type"}
            },
        )
        or record.metadata_json.get("content_type") != "application/json"
    ):
        return None
    return record


def binding(run, operation):
    return dict(
        run_id=run.id,
        operation_id=operation.id,
        generation=operation.generation,
        input_fingerprint=run.dependency_fingerprint,
        options_fingerprint=fingerprint(run.options),
    )


def summary(db, project, run):
    body = WaveformOptions.model_validate(run.options)
    try:
        record = artifact_record(db, project, run) if run.status == "succeeded" else None
    except (ValueError, TypeError, KeyError, AttributeError):
        record = None
    asset = owned(db, Asset, project, record.asset_id) if record and record.asset_id else None
    if asset and (
        asset.storage_key != record.storage_key
        or asset.sha256 != record.metadata_json.get("sha256")
        or asset.byte_size != record.metadata_json.get("byte_size")
        or asset.kind != "waveform"
        or asset.content_type != "application/json"
        or record.metadata_json.get("provenance_fingerprint") != fingerprint(body.proof)
        or record.metadata_json.get("options_fingerprint") != fingerprint(run.options)
    ):
        asset = None
    artifact = dict(asset_id=asset.id, url=f"/api/assets/{asset.id}/content") if asset else None
    return dict(
        id=run.id,
        run_id=run.id,
        status=run.status,
        current=not run.is_stale and publication_current(db, run),
        kind=body.kind,
        output_id=body.output_id,
        artifact=artifact,
        waveform=None,
        error=(
            {"code": "WAVEFORM_ARTIFACT_INVALID"}
            if run.status == "succeeded" and not artifact
            else run.safe_error
        ),
    ), asset


def owned_waveform(db, project, run_id):
    run = owned(db, StageRun, project, run_id)
    if run.stage != STAGE:
        not_found()
    return run


def discovery(db, project, limit=30, offset=0):
    from .contracts import SourceGuard
    from .source import current_selection, source_state
    from .waveforms_contracts import WaveformCreate

    source = dict(
        available=False, asset_id=None, preparation_hint="Prepare current working PCM audio first"
    )
    voices = []
    try:
        selection = current_selection(db, project)
        state = source_state(db, project)
        guard = SourceGuard(
            selection_revision=selection.revision, transcript_revision=state.transcript_id
        )
        try:
            _, asset = capture(db, project, WaveformCreate(guard=guard, kind="source"))
            source = dict(available=True, asset_id=asset.id, preparation_hint=None)
        except APIError:
            pass
        selections = db.scalars(
            scope(AudioSelectionVersion, project)
            .join(AudioSelection, AudioSelection.current_version_id == AudioSelectionVersion.id)
            .order_by(AudioSelectionVersion.id)
            .limit(100)
        ).all()
        for item in selections:
            try:
                proof, asset = capture(
                    db,
                    project,
                    WaveformCreate(guard=guard, kind="natural_voice", output_id=item.output_id),
                )
                voices.append(
                    dict(
                        output_id=item.output_id,
                        asset_id=asset.id,
                        segment_id=proof["segment_id"],
                        track_id=proof["track_id"],
                    )
                )
            except APIError:
                continue
    except APIError:
        pass
    rows = db.scalars(
        scope(StageRun, project)
        .where(StageRun.stage == STAGE)
        .order_by(StageRun.created_at.desc(), StageRun.id)
        .limit(limit)
        .offset(offset)
    )
    return dict(
        source=source,
        natural_voice=voices,
        items=[summary(db, project, run)[0] for run in rows],
        limit=limit,
        offset=offset,
    )

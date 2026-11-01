"""Actual waveform CPU work and artifact validation outside SQL transactions."""

import hashlib
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..execution.contracts import FailureCode, StageFailure, StageResult
from ..execution.inputs import fingerprint
from ..execution.prepared import Operations, current_operation
from ..execution.prepared_media import publish as publish_media
from ..execution.prepared_media import store
from ..media.waveform import MAX_JSON_BYTES, POLICY, envelope
from ..models.core import Project
from .analysis import materialize
from .waveforms import artifact_record, binding, capture, publication_current
from .waveforms_contracts import WaveformArtifact, WaveformOptions


def encode(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_JSON_BYTES:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    return raw


def validate_payload(value, options):
    body = WaveformOptions.model_validate(options)
    artifact = WaveformArtifact.model_validate(value).model_dump()
    proof = body.proof
    if (
        artifact["provenance"] != proof
        or artifact["input_sha256"] != proof["input_sha256"]
        or artifact["clock"] != proof["clock"]
        or artifact["bin_count"] != min(body.bins, artifact["sample_count"])
    ):
        raise ValueError("Waveform binding differs")
    if body.kind == "source":
        frames = round(
            (proof["source_end_ms"] - proof["source_start_ms"]) * artifact["sample_rate"] / 1000
        )
        if artifact["sample_count"] != frames:
            raise ValueError("Source waveform is not the selected window")
    elif abs(artifact["duration_ms"] - proof["natural_duration_ms"]) > 1:
        raise ValueError("Natural waveform duration differs")
    return artifact


def read_artifact(storage, asset, options, *, exact_bytes=False):
    """Server-side validation of owned private JSON; callers release SQL first."""
    if not 0 < asset.byte_size <= MAX_JSON_BYTES:
        raise ValueError("Invalid waveform size")
    with storage.open(asset.storage_key) as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if (
        len(raw) != asset.byte_size
        or hashlib.sha256(raw).hexdigest() != asset.sha256
        or len(raw) > MAX_JSON_BYTES
    ):
        raise ValueError("Waveform bytes differ")
    value = validate_payload(json.loads(raw), options)
    return raw if exact_bytes else value


def content_for_asset(db, asset, storage):
    """The generic asset URL must apply the same validated JSON boundary as detail."""
    from types import SimpleNamespace

    from ..errors import APIError
    from ..models.analysis import PreparedObject, PrivateOperation
    from ..models.execution import StageRun
    from .ownership import scope
    from .waveforms import STAGE, summary

    project = db.get(Project, asset.project_id)
    record = db.scalar(scope(PreparedObject, project).where(PreparedObject.asset_id == asset.id))
    operation = db.get(PrivateOperation, record.operation_id) if record else None
    run = db.get(StageRun, operation.run_id) if operation else None
    if run and run.stage == STAGE:
        _, validated = summary(db, project, run)
        if validated and validated.id == asset.id:
            proof = SimpleNamespace(
                storage_key=validated.storage_key,
                byte_size=validated.byte_size,
                sha256=validated.sha256,
            )
            options = dict(run.options)
            db.rollback()
            try:
                return read_artifact(storage, proof, options, exact_bytes=True)
            except (ValueError, TypeError, KeyError, AttributeError, OSError):
                pass
    raise APIError(409, "WAVEFORM_ARTIFACT_INVALID", "Waveform artifact is unavailable")


def facts(artifact):
    return {key: artifact[key] for key in ("sample_count", "sample_rate", "channels", "bin_count")}


@dataclass(frozen=True)
class ValidatedWaveform(StageResult):
    checkpoint_fingerprint: str | None = None


def handler(context):
    operations = Operations(context)
    context.check_active()
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        body = WaveformOptions.model_validate(run.options)
        proof, asset = capture(db, project, body)
        if proof != body.proof:
            raise StageFailure(FailureCode.CONFIGURATION)
    operation = operations.prepare(
        provider="cpu",
        model=POLICY,
        request_payload=dict(options_fingerprint=fingerprint(run.options)),
    )
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        actual = current_operation(db, run)
        if actual.id != operation.id or actual.request_payload != dict(
            options_fingerprint=fingerprint(run.options)
        ):
            raise StageFailure(FailureCode.CONFIGURATION)
        cached_record = artifact_record(db, project, run) if actual.phase == "prepared" else None
        checkpoint = actual.prepared_payload
        expected_binding = binding(run, actual)
    if cached_record:
        try:
            # PreparedObject exposes the same private byte-size/hash contract as Asset.
            from types import SimpleNamespace

            cached_asset = SimpleNamespace(
                storage_key=cached_record.storage_key, **checkpoint["entry"]["metadata"]
            )
            artifact = read_artifact(context.storage, cached_asset, run.options)
            if actual.public_facts != facts(artifact):
                raise ValueError("Waveform facts differ")
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
    elif actual.phase == "prepared":
        raise StageFailure(FailureCode.CONFIGURATION, review=True)
    else:
        # Source/natural files are already owned PCM. Never open a remote URL or run inference.
        with tempfile.TemporaryDirectory(prefix="videotranslate-waveform-") as directory:
            from types import SimpleNamespace

            from ..media.finishing_types import RenderLimits
            from ..media.float_audio import Budget

            path = Path(directory) / "input.wav"
            last_check = 0

            def check():
                nonlocal last_check
                now = time.monotonic()
                if now - last_check >= 0.1:
                    context.check_active()
                    last_check = now

            budget = Budget(
                RenderLimits(
                    max_output_bytes=MAX_JSON_BYTES,
                    max_temporary_bytes=context.settings.probe_max_bytes + MAX_JSON_BYTES,
                    max_wall_seconds=min(context.settings.probe_timeout_seconds, 86400),
                    max_video_frames=1,
                ),
                check,
                directory,
            )
            materialize(
                SimpleNamespace(storage=context.storage, check_active=budget.check),
                asset,
                path,
                max_bytes=context.settings.probe_max_bytes,
            )
            artifact = envelope(
                path,
                expected_sha256=asset.sha256,
                bins=body.bins,
                max_bytes=context.settings.probe_max_bytes,
                max_duration=context.settings.probe_max_duration_seconds,
                timeout=context.settings.probe_timeout_seconds,
                check=budget.check,
            )
            artifact.update(clock=proof["clock"], provenance=proof)
            artifact = validate_payload(artifact, run.options)
            raw = encode(artifact)
            output = Path(directory) / "waveform.json"
            output.write_bytes(raw)
            budget.check()
            metadata = dict(
                byte_size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                provenance_fingerprint=fingerprint(proof),
                options_fingerprint=fingerprint(run.options),
            )
            object_id = store(context, actual.id, output, metadata, kind="waveform", format="json")
            entry = dict(object_id=object_id, kind="waveform", format="json", metadata=metadata)
            checkpoint = dict(binding=expected_binding, objects=[object_id], entry=entry)
        context.check_active()
        operations.cache(checkpoint, facts(artifact))
    context.check_active()
    return ValidatedWaveform(facts(artifact), operation.id, fingerprint(checkpoint))


def publish(db, run, result):
    project = db.get(Project, run.project_id)
    record = artifact_record(db, project, run)
    op = current_operation(db, run)
    if (
        not isinstance(result, ValidatedWaveform)
        or not record
        or not op
        or op.id != result.prepared_id
        or fingerprint(op.prepared_payload) != result.checkpoint_fingerprint
        or op.public_facts != result.facts
        or not publication_current(db, run)
    ):
        raise ValueError("Invalid current waveform checkpoint")
    publish_media(db, run, [op.prepared_payload["entry"]])

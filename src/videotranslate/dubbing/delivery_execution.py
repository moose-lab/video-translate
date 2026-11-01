"""Durable CPU render, mix and export checkpoints in the ordinary worker engine."""

import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from ..execution import prepared_media
from ..execution.contracts import FailureCode, StageFailure, StageResult
from ..execution.inputs import capture_inputs, fingerprint
from ..execution.prepared import Operations, current_operation
from ..models.analysis import PreparedObject
from ..models.core import Asset, Project
from ..models.delivery import DeliveryCommand
from ..models.execution import StageRun
from . import deliveries, delivery_pipeline
from .delivery_checkpoint import validate_checkpoint
from .fit_contracts import FitOptions
from .ownership import changed, owned

POLICY = "owned_delivery_v1"


@dataclass(frozen=True)
class ValidatedDeliveryResult(StageResult):
    checkpoint_fingerprint: str | None = None


def options(value):
    from ..errors import APIError

    try:
        return FitOptions.model_validate(value).model_dump()
    except ValueError:
        raise APIError(422, "INVALID_OPTIONS", "A guarded delivery command is required") from None


def command_scope(request):
    return options(request.options)["command_id"]


def command_for(db, project, request):
    if request.stage != "deliver" or request.target_language or request.segment_id:
        deliveries.blocked()
    return owned(db, DeliveryCommand, project, command_scope(request))


def inputs(db, project, request):
    intent = command_for(db, project, request)
    if not deliveries.current(db, project, intent):
        deliveries.blocked()
    return capture_inputs(db, project, ["finishing.delivery:" + intent.id])


def publication_current(db, run):
    try:
        project = db.get(Project, run.project_id)
        intent = command_for(db, project, run)
        return intent.run_id == run.id and deliveries.current(db, project, intent)
    except Exception:
        return False


def binding(intent, run, operation):
    if (
        operation is None
        or intent.run_id != run.id
        or operation.run_id != run.id
        or operation.project_id != run.project_id
        or operation.workspace_id != run.workspace_id
        or operation.generation != run.request_key
        or operation.input_fingerprint != run.dependency_fingerprint
        or operation.provider != "cpu"
        or operation.model != POLICY
        or operation.host != ""
        or operation.prefix != ""
        or operation.connection_revision != 0
        or operation.remote_id is not None
        or operation.phase not in {"ready", "prepared"}
        or operation.request_payload != {"command_id": intent.id, "signature": intent.signature}
    ):
        raise ValueError("Invalid delivery operation origin")
    value = dict(
        command_id=intent.id,
        project_id=run.project_id,
        workspace_id=run.workspace_id,
        command_signature=intent.signature,
        run_id=run.id,
        operation_id=operation.id,
        generation=run.request_key,
        input_fingerprint=run.dependency_fingerprint,
        policy=POLICY,
        input_manifest_fingerprint=fingerprint(intent.snapshot),
        voice_keys=[
            p["track_key"] + ":" + p["segment_key"] for p in intent.snapshot["plan"]["placements"]
        ],
        tracks=[t["tag"] for t in intent.snapshot["parent_snapshot"]["tracks"]],
        comparison=intent.snapshot["choices"]["include_original_comparison"],
        captions=intent.snapshot["choices"]["captions"],
        default_track=intent.snapshot["choices"]["default_audio_track"],
    )

    if intent.snapshot["choices"].get("caption_options") is not None:
        value["caption_options"] = intent.snapshot["choices"]["caption_options"]
    return value


def checkpoint(context, operation_id, expected, payload):
    validate_checkpoint(payload, expected)
    context.check_active()
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        operation = current_operation(db, run)
        if (
            not operation
            or operation.id != operation_id
            or binding(command_for(db, project, run), run, operation) != expected
            or operation.phase != "ready"
            or not publication_current(db, run)
        ):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        prior = operation.prepared_payload
        if prior is not None:
            if (
                type(prior) is not dict
                or fingerprint(prior.get("binding")) != fingerprint(expected)
                or type(prior.get("phases")) is not dict
                or type(prior.get("objects")) is not list
                or prior.get("caption_proof") != payload.get("caption_proof")
                or any(
                    fingerprint(payload["phases"].get(name)) != fingerprint(value)
                    for name, value in prior["phases"].items()
                )
                or payload["objects"][: len(prior["objects"])] != prior["objects"]
            ):
                raise ValueError("A completed CPU phase is immutable")
        operation.prepared_payload = payload
        changed(
            db,
            project,
            "delivery.phase_completed",
            run=run,
            stage=payload["phase"],
            count=len(payload["objects"]),
        )


def handler(context):
    from ..media.finishing_types import RenderLimits
    from ..media.float_audio import Budget
    from ..models.finishing import FitPlanCommand
    from .analysis import materialize
    from .fit_snapshot import validate_stored

    operations = Operations(context)
    context.check_active()
    with context.session_factory() as db:
        run = db.get(StageRun, context.run_id)
        project = db.get(Project, run.project_id)
        intent = command_for(db, project, run)
        parent = owned(db, FitPlanCommand, project, intent.fit_plan_id)
        deliveries.valid_parent(db, project, parent)  # ends read transaction before strict CPU
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        intent = command_for(db, project, run)
        if not publication_current(db, run):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        snapshot = dict(intent.snapshot)
        assets = {
            key: owned(db, Asset, project, facts["id"]) for key, facts in snapshot["assets"].items()
        }
    plan = validate_stored(snapshot["plan"], snapshot["parent_snapshot"], snapshot["rows"])
    operation = operations.prepare(
        provider="cpu",
        model=POLICY,
        request_payload={"command_id": intent.id, "signature": intent.signature},
    )
    with context.session_factory.begin() as db:
        _, run = context._locked(db)
        current = current_operation(db, run)
        expected = binding(intent, run, current)
        payload = current.prepared_payload
        phase = current.phase
    if payload is not None:
        validate_checkpoint(payload, expected)
        from .delivery_subtitles import validate_capture

        validate_capture(payload, snapshot, plan)
    else:
        payload = dict(binding=expected, phase="render", phases={}, objects=[], artifacts=[])
    limits = RenderLimits(**snapshot["limits"])
    last_check = 0.0
    deadline = time.monotonic() + limits.max_wall_seconds
    with tempfile.TemporaryDirectory(prefix="vt-delivery-") as directory:
        root = Path(directory)

        def temporary_bytes():
            total = 0
            for path in root.rglob("*"):
                try:
                    item = path.stat()
                except FileNotFoundError:
                    continue  # native progress replaces its owned name atomically
                if stat.S_ISREG(item.st_mode):
                    total += item.st_size
            return total

        def check():
            nonlocal last_check
            now = time.monotonic()
            if now > deadline or temporary_bytes() > limits.max_temporary_bytes:
                raise StageFailure(FailureCode.MEDIA_LIMIT)
            if now - last_check >= 0.5:
                context.check_active()
                last_check = now

        budget = Budget(limits, check, root)
        # Recheck every captured owned input on every attempt, including prepared restarts.
        # Byte hashing/storage never shares a SQL transaction.
        import hashlib

        def verify_inputs():
            for asset in assets.values():
                actual = hashlib.sha256()
                size = 0
                with context.storage.open(asset.storage_key) as source:
                    while chunk := source.read(1024 * 1024):
                        check()
                        actual.update(chunk)
                        size += len(chunk)
                        if size > limits.max_output_bytes:
                            raise StageFailure(FailureCode.MEDIA_LIMIT)
                if actual.hexdigest() != asset.sha256 or size != asset.byte_size:
                    raise StageFailure(FailureCode.INVALID_MEDIA)

        verify_inputs()
        io_context = SimpleNamespace(storage=context.storage, check_active=check)
        local = {}

        def load_asset(key):
            if key not in local:
                path = root / ("input-" + str(len(local)))
                materialize(io_context, assets[key], path, max_bytes=limits.max_output_bytes)
                local[key] = path
            return local[key]

        def store_file(media, kind, format):
            metadata = media.metadata()
            object_id = prepared_media.store(
                context, operation.id, media.path, metadata, kind=kind, format=format
            )
            payload["objects"].append(object_id)
            return dict(object_id=object_id, metadata=metadata, kind=kind, format=format)

        def restore(entry):
            object_id = entry["object_id"]
            if object_id not in local:
                with context.session_factory.begin() as db:
                    project, active = context._locked(db)
                    item = owned(db, PreparedObject, project, object_id)
                    if (
                        item.operation_id != operation.id
                        or item.state not in {"orphan", "published"}
                        or not item.write_settled
                        or item.delete_pending
                        or item.metadata_json
                        != dict(
                            entry["metadata"],
                            kind=entry["kind"],
                            format=entry["format"],
                            content_type=prepared_media.FORMATS[entry["format"]],
                        )
                    ):
                        raise ValueError("Invalid checkpoint media")
                path = root / ("restored-" + object_id + "." + entry["format"])
                # Same owned storage and measured hash/size contract, without SQL during I/O.

                materialize(
                    io_context,
                    SimpleNamespace(
                        storage_key=item.storage_key,
                        byte_size=entry["metadata"]["byte_size"],
                        sha256=entry["metadata"]["sha256"],
                    ),
                    path,
                    max_bytes=limits.max_output_bytes,
                )
                local[object_id] = path
            return local[object_id]

        # Fontconfig/cmap/hash work runs before render and outside SQL. A retry
        # must reproduce the captured exact faces and glyph/cue proofs.
        from . import delivery_subtitles

        caption_context = None
        if delivery_subtitles.needed(snapshot["choices"]):
            caption_context = delivery_subtitles.preflight(snapshot, plan, budget)
            proof = caption_context[2]
            if "caption_proof" in payload:
                if payload["caption_proof"] != proof:
                    raise delivery_subtitles.CaptionFailure(
                        delivery_subtitles.FontCoverageError("FONT_PROOF_CHANGED")
                    )
            else:
                payload["caption_proof"] = proof
                payload["phase"] = "caption_preflight"
                checkpoint(context, operation.id, expected, payload)
        if phase == "prepared":
            for entry in [e for p in payload["phases"].values() for e in p["outputs"]]:
                restore(entry)
            verify_inputs()
            context.check_active()
            cached = operations.cached()
            return ValidatedDeliveryResult(cached.facts, cached.prepared_id, fingerprint(payload))
        if "render" not in payload["phases"]:
            outputs = delivery_pipeline.render(
                snapshot, assets, plan, root, limits, check, load_asset, store_file
            )
            payload["phases"]["render"] = dict(outputs=outputs, fingerprint=fingerprint(outputs))
            payload["phase"] = "render"
            checkpoint(context, operation.id, expected, payload)
        render = payload["phases"]["render"]["outputs"]
        if "mix" not in payload["phases"]:
            outputs = delivery_pipeline.mix_tracks(
                snapshot, plan, root, limits, check, load_asset, store_file, restore, render
            )
            payload["phases"]["mix"] = dict(outputs=outputs, fingerprint=fingerprint(outputs))
            payload["phase"] = "mix"
            checkpoint(context, operation.id, expected, payload)
        mixed = payload["phases"]["mix"]["outputs"]
        if "export" not in payload["phases"]:
            outputs, artifacts = delivery_pipeline.export(
                snapshot,
                plan,
                root,
                budget,
                store_file,
                restore,
                render,
                mixed,
                caption_context=caption_context,
            )
            payload["phases"]["export"] = dict(outputs=outputs, fingerprint=fingerprint(outputs))
            payload["phase"] = "export"
            payload["artifacts"] = artifacts
            delivery_subtitles.validate_capture(payload, snapshot, plan)
            checkpoint(context, operation.id, expected, payload)
        verify_inputs()
        if (
            caption_context
            and delivery_subtitles.preflight(snapshot, plan, budget)[2] != payload["caption_proof"]
        ):
            raise delivery_subtitles.CaptionFailure(
                delivery_subtitles.FontCoverageError("FONT_PROOF_CHANGED")
            )
        context.check_active()
        with context.session_factory() as db:
            run = db.get(StageRun, context.run_id)
            project = db.get(Project, run.project_id)
            command = command_for(db, project, run)
            deliveries.valid_parent(
                db, project, owned(db, FitPlanCommand, project, command.fit_plan_id)
            )
        with context.session_factory.begin() as db:
            _, run = context._locked(db)
            if not publication_current(db, run):
                raise StageFailure(FailureCode.CONFIGURATION, review=True)
        cached = operations.cache(
            payload, dict(phase="export", count=len(payload["artifacts"]), purpose=intent.purpose)
        )
        return ValidatedDeliveryResult(cached.facts, cached.prepared_id, fingerprint(payload))


def publish(db, run, result):
    project = db.get(Project, run.project_id)
    intent = command_for(db, project, run)
    operation = current_operation(db, run)
    if (
        not isinstance(result, ValidatedDeliveryResult)
        or not operation
        or operation.id != result.prepared_id
        or fingerprint(operation.prepared_payload) != result.checkpoint_fingerprint
        or not publication_current(db, run)
    ):
        raise ValueError("Invalid delivery publication")
    payload = operation.prepared_payload
    if fingerprint(payload["binding"]) != fingerprint(binding(intent, run, operation)):
        raise ValueError("Delivery publication binding changed")
    if payload["phase"] != "export" or not {"render", "mix", "export"} <= payload["phases"].keys():
        raise ValueError("Incomplete delivery")
    prepared_media.publish(
        db, run, [entry for phase in payload["phases"].values() for entry in phase["outputs"]]
    )
    changed(
        db,
        project,
        "delivery.published",
        run=run,
        command_id=intent.id,
        count=len(payload["artifacts"]),
        purpose=intent.purpose,
    )

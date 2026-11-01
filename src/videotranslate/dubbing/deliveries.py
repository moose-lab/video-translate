"""Guarded delivery admission and bounded owned artifact reads."""

from sqlalchemy import func, select

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import fingerprint, set_inputs
from ..execution.prepared import current_operation
from ..models.analysis import PreparedObject
from ..models.core import Asset, new_id
from ..models.delivery import DeliveryCommand
from ..models.dubbing import SegmentRevision, SourceTrack, TranslationRevision
from ..models.execution import StageRun
from ..models.finishing import FitPlanCommand, FitPlanResult
from ..models.synthesis import NaturalOutput
from . import fit_plans
from .ownership import changed, owned, owner, scope


def blocked():
    raise APIError(
        409,
        "DELIVERY_INPUT_CHANGED",
        "A current validated feasible fit plan and current media are required",
    )


def asset_facts(asset):
    return dict(id=asset.id, sha256=asset.sha256, byte_size=asset.byte_size, kind=asset.kind)


def capture(db, project, parent):
    from .analysis import media_for

    result = db.scalar(scope(FitPlanResult, project).where(FitPlanResult.command_id == parent.id))
    rows = fit_plans.captured_rows(db, project, parent)
    if (
        not result
        or not result.timeline_feasible
        or not fit_plans.current_plan_state(db, project, parent, rows)["current"]
    ):
        blocked()
    if parent.purpose == "dub" and any(not row.snapshot["ready"] for row in rows):
        blocked()
    producing_fit_run = owned(db, StageRun, project, parent.run_id)
    fit_operation = current_operation(db, producing_fit_run)
    if producing_fit_run.status != "succeeded" or producing_fit_run.is_stale:
        blocked()
    if (
        not fit_operation
        or fit_operation.id != result.operation_id
        or result.run_id != parent.run_id
    ):
        blocked()
    parent_proof = dict(
        run_id=producing_fit_run.id,
        operation_id=fit_operation.id,
        generation=fit_operation.generation,
        input_fingerprint=fit_operation.input_fingerprint,
        phase=fit_operation.phase,
        host=fit_operation.host,
        prefix=fit_operation.prefix,
        remote_id=fit_operation.remote_id,
        connection_revision=fit_operation.connection_revision,
        provider=fit_operation.provider,
        model=fit_operation.model,
        request_fingerprint=fingerprint(fit_operation.request_payload),
        payload_fingerprint=fingerprint(fit_operation.prepared_payload),
        facts_fingerprint=fingerprint(fit_operation.public_facts),
        summary=[result.timeline_feasible, result.planned_output_duration, result.issues],
    )
    source = owned(db, Asset, project, parent.source_asset_id)
    track = owned(db, SourceTrack, project, parent.snapshot["source_track_id"])
    assets = {"source": asset_facts(source)}
    producers = {}
    if parent.purpose != "original_only":
        for stage, field, key in [
            ("extract", "working_asset_id", "working"),
            ("separate", "instrumental_asset_id", "instrumental"),
        ]:
            media = media_for(db, project, stage)
            asset = owned(db, Asset, project, getattr(media, field))
            assets[key] = asset_facts(asset)
            producing = owned(db, StageRun, project, media.run_id)
            operation = current_operation(db, producing)
            prepared = db.scalar(
                scope(PreparedObject, project).where(PreparedObject.asset_id == asset.id)
            )
            if (
                not operation
                or operation.phase != "prepared"
                or not prepared
                or prepared.operation_id != operation.id
                or prepared.state != "published"
                or not prepared.write_settled
                or prepared.delete_pending
                or prepared.storage_key != asset.storage_key
                or prepared.metadata_json.get("sha256") != asset.sha256
                or prepared.metadata_json.get("byte_size") != asset.byte_size
                or prepared.id not in (operation.prepared_payload or {}).get("objects", [])
            ):
                blocked()
            producers[key] = dict(
                id=media.id,
                prepared_object_id=prepared.id,
                prepared_metadata_fingerprint=fingerprint(prepared.metadata_json),
                run_id=producing.id,
                input_fingerprint=producing.dependency_fingerprint,
                operation_id=operation.id if operation else None,
                operation_fingerprint=fingerprint(operation.prepared_payload)
                if operation
                else None,
            )
    cues = []
    for row in rows:
        source_revision = owned(db, SegmentRevision, project, row.source_revision_id)
        target_revision = (
            owned(db, TranslationRevision, project, row.translation_revision_id)
            if row.translation_revision_id
            else None
        )
        cues.append(
            dict(
                segment_id=row.segment_id,
                track_id=row.track_id,
                source_text=source_revision.text,
                target_text=target_revision.text if target_revision else None,
                start_ms=row.snapshot["start_ms"],
                end_ms=row.snapshot["end_ms"],
                included=row.included,
            )
        )
        if row.included:
            natural = owned(db, NaturalOutput, project, row.output_id)
            asset = owned(db, Asset, project, natural.audio_asset_id)
            if asset.sha256 != natural.sha256 or asset.byte_size != natural.byte_size:
                blocked()
            assets["voice:" + row.track_id + ":" + row.segment_id] = asset_facts(asset)
    return dict(
        fit_plan_id=parent.id,
        fit_run_id=parent.run_id,
        fit_signature=parent.signature,
        fit_result_id=result.id,
        fit_payload_fingerprint=result.payload_fingerprint,
        fit_operation_id=result.operation_id,
        parent_proof=parent_proof,
        plan=result.plan,
        parent_snapshot=parent.snapshot,
        rows=[r.snapshot for r in rows],
        source_audio_ordinal=track.audio_ordinal,
        assets=assets,
        producers=producers,
        cues=cues,
        source_language=project.source_language,
        limits=dict(
            max_output_bytes=512 * 1024**2,
            max_temporary_bytes=2 * 1024**3,
            max_wall_seconds=600,
            max_video_frames=500000,
        ),
        budget_policy="global_per_attempt_cpu_v1",
    )


def valid_parent(db, project, parent):
    # This read intentionally closes SQL before the strict full map/checkpoint validation.
    captured = capture(db, project, parent)
    detail = fit_plans.detail(db, project, parent)
    if (
        not detail["current"]
        or not detail["timeline_feasible"]
        or detail["plan"] is None
        or fingerprint(detail["plan"]) != fingerprint(captured["plan"])
    ):
        blocked()
    return captured


def admit(db, project, body, actor, validated_capture):
    from ..execution.service import create_run

    parent = owned(db, FitPlanCommand, project, body.fit_plan_id)
    if parent.run_id != body.expected_fit_run_id or parent.purpose != body.purpose:
        blocked()
    tags = [t["tag"] for t in parent.snapshot["tracks"]]
    choices = tags + (["original"] if body.include_original_comparison else [])
    if body.default_audio_track not in choices:
        raise APIError(422, "INVALID_AUDIO_TRACK", "Choose an included audio track")
    snapshot = capture(db, project, parent)
    if fingerprint(snapshot) != fingerprint(validated_capture):
        blocked()
    snapshot["choices"] = body.model_dump()
    if fit_plans.json_size(snapshot) > 8 * 1024 * 1024:
        raise APIError(
            422, "DELIVERY_SNAPSHOT_LIMIT", "Delivery capture exceeds the bounded snapshot size"
        )
    signature = fingerprint(dict(snapshot=snapshot, actor_id=actor))
    prior = db.scalar(scope(DeliveryCommand, project).where(DeliveryCommand.signature == signature))
    if prior:
        return prior.id
    command = DeliveryCommand(
        id=new_id(),
        **owner(project),
        fit_plan_id=parent.id,
        fit_result_id=snapshot["fit_result_id"],
        source_asset_id=parent.source_asset_id,
        actor_id=actor,
        purpose=parent.purpose,
        signature=signature,
        snapshot=snapshot,
    )
    db.add(command)
    db.flush()
    set_inputs(db, project, {"finishing.delivery:" + command.id: signature})
    run = create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(stage="deliver", options={"command_id": command.id}),
        guarded_command=True,
        idempotency_key="deliver:" + command.id,
    )
    command.run_id = run.id
    changed(db, project, "delivery.queued", run=run, command_id=command.id, purpose=command.purpose)
    return command.id


def current(db, project, command):
    try:
        if (
            fingerprint(dict(snapshot=command.snapshot, actor_id=command.actor_id))
            != command.signature
        ):
            return False
        if (
            command.fit_plan_id != command.snapshot["fit_plan_id"]
            or command.fit_result_id != command.snapshot["fit_result_id"]
            or command.source_asset_id != command.snapshot["assets"]["source"]["id"]
            or command.purpose != command.snapshot["parent_snapshot"]["purpose"]
        ):
            return False
        parent = owned(db, FitPlanCommand, project, command.fit_plan_id)
        now = capture(db, project, parent)
        return now == {k: v for k, v in command.snapshot.items() if k != "choices"}
    except (APIError, ValueError, TypeError, KeyError, AttributeError):
        return False


def detail(db, project, command):
    from .delivery_checkpoint import validate_checkpoint
    from .delivery_execution import binding

    run = owned(db, StageRun, project, command.run_id)
    try:
        valid_parent(db, project, owned(db, FitPlanCommand, project, command.fit_plan_id))
        current_value = current(db, project, command)
    except (APIError, ValueError, KeyError, TypeError, AttributeError):
        current_value = False
    operation = current_operation(db, run)
    payload = operation.prepared_payload if operation else None
    manifest_valid = True
    if payload:
        try:
            expected = binding(command, run, operation)
            db.commit()  # full manifest validation never extends a read transaction
            validate_checkpoint(payload, expected)
        except (APIError, ValueError, KeyError, TypeError, AttributeError):
            manifest_valid = False
            current_value = False
    artifacts = []
    if manifest_valid and run.status == "succeeded" and operation and operation.phase == "prepared":
        try:
            manifests = {
                entry["object_id"]: entry
                for phase in payload["phases"].values()
                for entry in phase["outputs"]
            }
            for entry in payload["artifacts"]:
                item = owned(db, PreparedObject, project, entry["object_id"])
                expected = manifests[item.id]
                if (
                    item.operation_id != operation.id
                    or item.state != "published"
                    or not item.asset_id
                    or item.metadata_json
                    != dict(
                        expected["metadata"],
                        kind=expected["kind"],
                        format=expected["format"],
                        content_type={
                            "mp4": "video/mp4",
                            "wav": "audio/wav",
                            "mp3": "audio/mpeg",
                            "srt": "application/x-subrip",
                            "vtt": "text/vtt",
                        }[expected["format"]],
                    )
                ):
                    raise ValueError("Invalid published delivery object")
                asset = owned(db, Asset, project, item.asset_id)
                if (
                    asset.sha256 != item.metadata_json["sha256"]
                    or asset.byte_size != item.metadata_json["byte_size"]
                    or asset.storage_key != item.storage_key
                ):
                    raise ValueError("Invalid published delivery asset")
                artifacts.append(
                    dict(
                        format=entry["format"],
                        track=entry["track"],
                        asset_id=asset.id,
                        byte_size=asset.byte_size,
                        sha256=asset.sha256,
                        content_type=asset.content_type,
                        download_url="/api/assets/" + asset.id + "/content",
                        metadata=item.metadata_json,
                        comparison_kind="retimed_original"
                        if entry["track"] == "original"
                        else None,
                    )
                )
        except (APIError, ValueError, KeyError, TypeError, AttributeError):
            manifest_valid = False
            current_value = False
            artifacts = []
    return dict(
        id=command.id,
        run_id=run.id,
        fit_plan_id=command.fit_plan_id,
        purpose=command.purpose,
        status=run.status,
        current=current_value,
        phase=payload.get("phase") if type(payload) is dict and manifest_valid else None,
        choices=command.snapshot["choices"],
        artifacts=artifacts,
        error=run.safe_error,
        retiming="shared_fit_map",
        manifest_valid=manifest_valid,
        comparison_kind="retimed_original",
        source_window=dict(
            start_ms=command.snapshot["parent_snapshot"]["start_ms"],
            end_ms=command.snapshot["parent_snapshot"]["end_ms"],
        ),
        limitations=["Hard subtitles are not implemented"],
    )


def summaries(db, project, limit, offset):
    query = scope(DeliveryCommand, project)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.execute(
        select(DeliveryCommand.id, DeliveryCommand.run_id, DeliveryCommand.purpose, StageRun.status)
        .join(StageRun, StageRun.id == DeliveryCommand.run_id)
        .where(
            DeliveryCommand.project_id == project.id,
            DeliveryCommand.workspace_id == project.workspace_id,
        )
        .order_by(DeliveryCommand.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return dict(
        total=total,
        items=[
            dict(
                id=r.id,
                run_id=r.run_id,
                purpose=r.purpose,
                status=r.status,
                current=None,
                currentness="not_assessed",
            )
            for r in items
        ],
    )

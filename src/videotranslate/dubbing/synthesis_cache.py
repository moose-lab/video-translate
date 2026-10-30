"""Strict private natural-audio cache evidence, independent of editor publication permission."""

from .ownership import owned


def cached_payload(db, project, line):
    """Validate the exact producing generation and owned manifest, independent of editor heads."""
    from ..execution.prepared import bounded, current_operation
    from ..models.analysis import PreparedObject, PrivateOperation
    from ..models.core import Asset
    from ..models.execution import StageRun
    from .remote_synthesis import line_for

    run = owned(db, StageRun, project, line.run_id)
    actual, _ = line_for(db, project, run)
    op = current_operation(db, run)
    if (
        actual.id != line.id
        or op is None
        or op.phase != "prepared"
        or op.request_payload.get("input") != line.input_payload
    ):
        raise ValueError("Invalid synthesis generation")
    if run.dependency_snapshot != {
        "synthesis.input:" + line.input_fingerprint: line.input_fingerprint
    }:
        raise ValueError("Invalid synthesis dependency lineage")
    payload = op.prepared_payload
    bounded(payload)
    if payload.get("input_fingerprint") != line.input_fingerprint or set(payload) != {
        "input_fingerprint",
        "origin_operation_id",
        "objects",
        "metadata",
        "raw_metadata",
        "full_decode",
    }:
        raise ValueError("Invalid synthesis result")
    if payload["full_decode"] is not True or len(payload["objects"]) != 1:
        raise ValueError("Invalid synthesis manifest")
    origin = owned(db, PrivateOperation, project, payload["origin_operation_id"])
    origin_run = owned(db, StageRun, project, origin.run_id)
    origin_line, _ = line_for(db, project, origin_run)
    current = current_operation(db, origin_run)
    if (
        current is None
        or current.id != origin.id
        or origin.phase != "prepared"
        or origin_line.input_payload != line.input_payload
        or origin.request_payload.get("input") != line.input_payload
        or origin.prepared_payload != payload
    ):
        raise ValueError("Invalid producing operation lineage")
    record = owned(db, PreparedObject, project, payload["objects"][0])
    metadata = payload["metadata"]
    if (
        record.operation_id != origin.id
        or record.state not in {"orphan", "published"}
        or not record.write_settled
        or record.delete_pending
        or metadata != {k: v for k, v in record.metadata_json.items() if k != "kind"}
        or record.metadata_json.get("kind") != "natural_audio"
        or metadata.get("container") != "wav"
        or metadata.get("codec") != "pcm_s16le"
        or set(metadata)
        != {"duration_ms", "sample_rate", "channels", "byte_size", "sha256", "codec", "container"}
        or type(metadata["duration_ms"]) is not int
        or metadata["duration_ms"] <= 0
        or type(metadata["byte_size"]) is not int
        or not 0 < metadata["byte_size"] <= 64 * 1024 * 1024
        or type(metadata["sample_rate"]) is not int
        or not 8000 <= metadata["sample_rate"] <= 192000
        or type(metadata["channels"]) is not int
        or not 1 <= metadata["channels"] <= 8
    ):
        raise ValueError("Invalid natural audio evidence")
    import re

    if not re.fullmatch("[a-f0-9]{64}", metadata["sha256"]):
        raise ValueError("Invalid hash")
    for operation in (op, origin):
        facts = operation.public_facts
        bounded(facts, 65536)
        if type(facts.get("reused")) is not bool or facts != {
            "duration_ms": metadata["duration_ms"],
            "sha256": metadata["sha256"],
            "reused": facts["reused"],
        }:
            raise ValueError("Invalid safe synthesis facts")
    if origin_line.track_id != line.track_id or origin_line.segment_id != line.segment_id:
        raise ValueError("Invalid cache cell")
    bounded(payload["raw_metadata"])
    if record.asset_id:
        asset = owned(db, Asset, project, record.asset_id)
        if (
            asset.storage_key != record.storage_key
            or asset.sha256 != metadata["sha256"]
            or asset.byte_size != metadata["byte_size"]
            or asset.content_type != "audio/wav"
        ):
            raise ValueError("Invalid published audio")
    return payload, origin_run, record

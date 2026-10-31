"""One bounded typed checkpoint contract; no database access or fit arithmetic."""

import json

from ..execution.inputs import fingerprint
from .fit_contracts import POLICY
from .fit_snapshot import OPERATION_LIMIT, PLAN_LIMIT, exact, rational


def same_json(actual, expected):
    """Canonical JSON hashes distinguish bool/int/float inside nested containers."""
    return fingerprint(actual) == fingerprint(expected)


def require_projection(actual, expected, *, limit=PLAN_LIMIT):
    exact(actual, expected)
    if len(json.dumps(actual, allow_nan=False).encode()) > limit:
        raise ValueError("Fit metadata exceeds limit")
    if not same_json(actual, expected):
        raise ValueError("Noncanonical fit metadata")


def binding(intent, run, operation):
    return dict(
        command_id=intent.id,
        command_fingerprint=intent.signature,
        run_id=run.id,
        operation_id=operation.id,
        generation=run.request_key,
        input_fingerprint=run.dependency_fingerprint,
        policy=POLICY,
        provider="cpu",
        model=POLICY,
    )


def validate_operation(intent, run, operation, *, prepared=True):
    """Small origin checks, also safe in the short publication transaction."""
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
        or type(operation.connection_revision) is not int
        or operation.connection_revision != 0
        or operation.remote_id is not None
        or operation.host != ""
        or operation.prefix != ""
        or operation.phase not in ({"prepared"} if prepared else {"ready", "prepared"})
    ):
        raise ValueError("Invalid fit operation")
    require_projection(
        operation.request_payload,
        dict(command_id=intent.id, command_fingerprint=intent.signature, policy=POLICY),
    )
    inputs = {"finishing.fit_input:" + intent.id: fingerprint(intent.signature)}
    require_projection(run.dependency_snapshot, inputs)
    if run.dependency_fingerprint != fingerprint(inputs):
        raise ValueError("Invalid fit input fingerprint")
    return binding(intent, run, operation)


def canonical_facts(intent, rows, data):
    return dict(
        command_id=intent.id,
        purpose=intent.purpose,
        count=len(rows),
        included_count=sum(r["included"] for r in rows),
        timeline_feasible=data["feasible"],
        issues=sorted({i["code"] for i in data["issues"]}),
        planned_output_duration_ms=data["output_duration_ms"],
    )


def validate_checkpoint(payload, expected_binding, facts, expected_facts):
    """Authenticate the actual cached plan and exact facts, without decoding/rebuilding."""
    exact(payload, ("binding", "plan", "payload_fingerprint"))
    if len(json.dumps(payload, allow_nan=False).encode()) > OPERATION_LIMIT:
        raise ValueError("Fit checkpoint exceeds limit")
    if type(payload["plan"]) is not dict or (
        len(json.dumps(payload["plan"], allow_nan=False).encode()) > PLAN_LIMIT
    ):
        raise ValueError("Fit plan exceeds limit")
    require_projection(payload["binding"], expected_binding)
    if type(payload["payload_fingerprint"]) is not str or payload[
        "payload_fingerprint"
    ] != fingerprint(payload["plan"]):
        raise ValueError("Invalid actual fit checkpoint hash")
    require_projection(facts, expected_facts, limit=65536)


def captured_summary(feasible, duration):
    """Check summary scalars only; list integrity/currentness stay explicitly unassessed."""
    try:
        if type(feasible) is not bool or rational(duration) <= 0:
            raise ValueError("Invalid fit summary")
        if len(json.dumps(duration, allow_nan=False).encode()) > 1024:
            raise ValueError("Fit summary exceeds limit")
    except (ValueError, KeyError, TypeError, AttributeError):
        feasible, duration = None, None
    return dict(timeline_feasible=feasible, planned_output_duration_ms=duration)


def validate_summary(feasible, duration, issues, data):
    summary = captured_summary(feasible, duration)
    if summary["timeline_feasible"] is None:
        raise ValueError("Invalid fit summary")
    require_projection(
        summary | dict(issues=issues),
        dict(
            timeline_feasible=data["feasible"],
            planned_output_duration_ms=data["output_duration_ms"],
            issues=data["issues"],
        ),
    )

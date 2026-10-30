"""Command-only CPU fit stage; calculation and restart validation own no SQL transaction."""

from dataclasses import dataclass

from ..errors import APIError
from ..execution.contracts import FailureCode, StageFailure, StageResult
from ..execution.inputs import capture_inputs, fingerprint
from ..execution.prepared import Operations, current_operation
from ..models.core import Project, new_id
from ..models.finishing import FitPlanCommand, FitPlanResult
from .fit_contracts import POLICY, FitOptions, FitSettingsBody
from .fit_plans import capture_integrity, captured_rows, current_plan_state
from .fit_snapshot import OPERATION_LIMIT, PLAN_LIMIT, validate_stored
from .ownership import changed, invalid, owned, owner, scope


@dataclass(frozen=True)
class ValidatedFitResult(StageResult):
    payload: dict | None = None
    checkpoint_fingerprint: str | None = None


def options(values):
    try:
        return FitOptions.model_validate(values).model_dump()
    except ValueError:
        raise APIError(422, "INVALID_OPTIONS", "A guarded fit command is required") from None


def command_scope(request):
    return options(request.options)["command_id"]


def command_for(db, project, request):
    intent = owned(db, FitPlanCommand, project, command_scope(request))
    if (
        request.stage != "plan_fit"
        or request.target_language is not None
        or request.segment_id is not None
    ):
        invalid()
    return intent


def inputs(db, project, request):
    intent = command_for(db, project, request)
    return capture_inputs(db, project, ["finishing.fit_input:" + intent.id])


def publication_current(db, run):
    try:
        project = db.get(Project, run.project_id)
        intent = command_for(db, project, run)
        return intent.run_id == run.id and current_plan_state(db, project, intent)["current"]
    except (APIError, ValueError, KeyError, TypeError, AttributeError):
        return False


def binding(intent, run, operation):
    return dict(
        command_id=intent.id,
        command_fingerprint=intent.signature,
        run_id=run.id,
        operation_id=operation.id,
        generation=operation.generation,
        input_fingerprint=run.dependency_fingerprint,
        policy=POLICY,
        provider="cpu",
        model=POLICY,
    )


def handler(context):
    from ..media.fit_plan import build_plan, plan_json
    from ..media.fit_types import FitLine
    from .fit_plans import json_size

    operations = Operations(context)
    context.check_active()
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        intent = command_for(db, project, run)
        records = captured_rows(db, project, intent)
        if not capture_integrity(intent, records):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        rows = [dict(r.snapshot) for r in records]
        snapshot, signature, actor = dict(intent.snapshot), intent.signature, intent.actor_id
        if fingerprint({"snapshot": snapshot, "rows": rows, "actor_id": actor}) != signature:
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
    operation = operations.prepare(
        provider="cpu",
        model=POLICY,
        request_payload={
            "command_id": intent.id,
            "command_fingerprint": signature,
            "policy": POLICY,
        },
    )
    # Copy checkpoint under its lease, validate complete canonical JSON after closing SQL.
    with context.session_factory.begin() as db:
        _, active = context._locked(db)
        actual = current_operation(db, active)
        if actual is None or actual.id != operation.id:
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        expected = binding(intent, active, actual)
        payload = actual.prepared_payload if actual.phase == "prepared" else None
        facts = actual.public_facts
        if (
            actual.phase not in {"ready", "prepared"}
            or (actual.phase == "prepared" and type(payload) is not dict)
            or actual.provider != "cpu"
            or actual.model != POLICY
            or actual.connection_revision != 0
            or actual.remote_id is not None
            or actual.request_payload
            != {"command_id": intent.id, "command_fingerprint": signature, "policy": POLICY}
        ):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
    try:
        if payload is not None:
            if (
                type(payload) is not dict
                or set(payload) != {"binding", "plan", "payload_fingerprint"}
                or payload["binding"] != expected
                or fingerprint(payload["plan"]) != payload["payload_fingerprint"]
            ):
                raise ValueError("Invalid fit checkpoint")
            plan = validate_stored(payload["plan"], snapshot, rows)
        else:
            plan = build_plan(
                snapshot["end_ms"] - snapshot["start_ms"],
                [
                    FitLine(
                        r["track_id"],
                        r["segment_id"],
                        r["role_id"],
                        r["start_ms"],
                        r["end_ms"],
                        r["natural_duration_ms"],
                    )
                    for r in rows
                    if r["included"]
                ],
                FitSettingsBody.model_validate(snapshot["settings"]).pure(),
            )
            data = plan_json(plan)
            if json_size(data) > PLAN_LIMIT:
                raise ValueError("Fit plan exceeds limit")
            validate_stored(data, snapshot, rows)
            payload = dict(binding=expected, plan=data, payload_fingerprint=fingerprint(data))
            facts = dict(
                command_id=intent.id,
                purpose=intent.purpose,
                count=len(rows),
                included_count=sum(r["included"] for r in rows),
                timeline_feasible=plan.feasible,
                issues=sorted({i.code for i in plan.issues}),
                planned_output_duration_ms=data["output_duration_ms"],
            )
        # Safe facts are derived anew even on resume, never trusted from damaged cache.
        canonical_facts = dict(
            command_id=intent.id,
            purpose=intent.purpose,
            count=len(rows),
            included_count=sum(r["included"] for r in rows),
            timeline_feasible=plan.feasible,
            issues=sorted({i.code for i in plan.issues}),
            planned_output_duration_ms=payload["plan"]["output_duration_ms"],
        )
        if facts != canonical_facts:
            raise ValueError("Invalid fit checkpoint facts")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
    context.check_active()
    if operation.phase != "prepared":
        operations.cache(payload, facts, payload_limit=OPERATION_LIMIT)
    context.check_active()
    return ValidatedFitResult(facts, operation.id, payload, fingerprint(payload))


def publish(db, run, result):
    project = db.get(Project, run.project_id)
    intent = command_for(db, project, run)
    operation = current_operation(db, run)
    if (
        not isinstance(result, ValidatedFitResult)
        or operation is None
        or operation.id != result.prepared_id
        or operation.phase != "prepared"
        or operation.provider != "cpu"
        or operation.model != POLICY
        or operation.prepared_payload != result.payload
        or fingerprint(operation.prepared_payload) != result.checkpoint_fingerprint
        or result.payload["binding"] != binding(intent, run, operation)
        or operation.request_payload
        != {"command_id": intent.id, "command_fingerprint": intent.signature, "policy": POLICY}
        or operation.public_facts != result.facts
    ):
        raise ValueError("Invalid fit publication checkpoint")
    prior = db.scalar(scope(FitPlanResult, project).where(FitPlanResult.command_id == intent.id))
    if prior:
        return
    data = result.payload["plan"]
    saved = FitPlanResult(
        id=new_id(),
        **owner(project),
        command_id=intent.id,
        run_id=run.id,
        operation_id=operation.id,
        payload_fingerprint=result.payload["payload_fingerprint"],
        timeline_feasible=result.facts["timeline_feasible"],
        planned_output_duration=data["output_duration_ms"],
        issues=data["issues"],
        plan=data,
    )
    db.add(saved)
    changed(db, project, "finishing.plan_published", run=run, **result.facts)

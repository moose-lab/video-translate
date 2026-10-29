"""Only real implemented stages are available in production."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from ..errors import APIError
from ..models.core import Project
from ..models.execution import StageRun
from .contracts import RunCreate, StageResult
from .inputs import capture_inputs

if TYPE_CHECKING:
    from .context import RunContext


@dataclass(frozen=True)
class StageDefinition:
    name: str
    validate_options: Callable[[dict], dict]
    resolve_inputs: Callable[[Session, Project, RunCreate], dict[str, str]]
    handle: Callable[["RunContext"], StageResult]
    publish: Callable[[Session, StageRun, StageResult], None] | None = None


def probe_options(options):
    if options:
        raise APIError(422, "INVALID_OPTIONS", "Probe accepts no options")
    return {}


def probe_inputs(db, project, request):
    if request.target_language is not None or request.segment_id is not None:
        raise APIError(422, "INVALID_SCOPE", "Probe accepts no target or segment")
    return capture_inputs(db, project, ["source.video"])


def probe_handler(context):
    from ..media.probe import probe_source

    return StageResult(probe_source(context))


STAGES = {"probe": StageDefinition("probe", probe_options, probe_inputs, probe_handler)}


def get_stage(name: str, registry=None) -> StageDefinition:
    stage = (STAGES if registry is None else registry).get(name)
    if stage is None:
        raise APIError(422, "STAGE_UNAVAILABLE", "Stage is not implemented")
    return stage

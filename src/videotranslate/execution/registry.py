"""Only real implemented stages are available in production."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from ..dubbing.analysis import (
    extract_handler,
    extract_inputs,
    no_options,
    publish_media,
    publish_transcript,
    separate_handler,
    separate_inputs,
    transcribe_handler,
    transcribe_inputs,
)
from ..dubbing.references import publication_current as reference_current
from ..dubbing.references import (
    publish_reference,
    reference_handler,
    reference_inputs,
    reference_options,
)
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
    publication_guard: Callable[[Session, StageRun], bool] | None = None


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


def publication_current(db, run):
    from ..dubbing.workflow import publication_current as guard

    return guard(db, run)


STAGES = {
    "reference": StageDefinition(
        "reference",
        reference_options,
        reference_inputs,
        reference_handler,
        publish_reference,
        reference_current,
    ),
    "probe": StageDefinition("probe", probe_options, probe_inputs, probe_handler),
    "extract": StageDefinition(
        "extract", no_options, extract_inputs, extract_handler, publish_media
    ),
    "separate": StageDefinition(
        "separate", no_options, separate_inputs, separate_handler, publish_media
    ),
    "transcribe": StageDefinition(
        "transcribe",
        no_options,
        transcribe_inputs,
        transcribe_handler,
        publish_transcript,
        publication_current,
    ),
}


def get_stage(name: str, registry=None) -> StageDefinition:
    stage = (STAGES if registry is None else registry).get(name)
    if stage is None:
        raise APIError(422, "STAGE_UNAVAILABLE", "Stage is not implemented")
    return stage

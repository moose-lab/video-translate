"""Only real implemented stages are available in production."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from ..dubbing import remote_synthesis, remote_translation, remote_voice_qc
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
    transcribe_options,
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
    command_only: bool = False
    scope_suffix: Callable[[RunCreate], str] | None = None


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
        transcribe_options,
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


for _phase in ("context", "draft", "critique", "rewrite", "shorten"):
    _name = "translation_" + _phase
    STAGES[_name] = StageDefinition(
        _name,
        remote_translation.phase_options,
        remote_translation.phase_inputs,
        remote_translation.handler,
        remote_translation.publish,
        remote_translation.publication_current,
        command_only=True,
        scope_suffix=remote_translation.phase_scope,
    )

STAGES["synthesize"] = StageDefinition(
    "synthesize",
    remote_synthesis.line_options,
    remote_synthesis.line_inputs,
    remote_synthesis.handler,
    remote_synthesis.publish,
    remote_synthesis.publication_current,
    command_only=True,
    scope_suffix=remote_synthesis.line_scope,
)

STAGES["voice_qc"] = StageDefinition(
    "voice_qc",
    remote_voice_qc.line_options,
    remote_voice_qc.line_inputs,
    remote_voice_qc.handler,
    remote_voice_qc.publish,
    remote_voice_qc.publication_current,
    command_only=True,
    scope_suffix=remote_voice_qc.line_scope,
)

from ..dubbing import fit_execution  # noqa: E402

STAGES["plan_fit"] = StageDefinition(
    "plan_fit",
    fit_execution.options,
    fit_execution.inputs,
    fit_execution.handler,
    fit_execution.publish,
    fit_execution.publication_current,
    command_only=True,
    scope_suffix=fit_execution.command_scope,
)

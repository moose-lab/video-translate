"""Validate captured immutable row/reference/config lineage without consulting current heads."""

from ..execution.inputs import fingerprint
from ..languages.catalog import resolve
from ..models.analysis import ReferenceVersion, VoiceBinding, VoiceBindingVersion
from ..models.core import Asset
from ..models.dubbing import (
    LanguageTrack,
    Segment,
    SegmentRevision,
    TranscriptRevision,
    TranslationRevision,
)
from ..providers.settings import resolve_revision
from .ownership import invalid, owned
from .synthesis_contracts import Controls


def validate_lineage(db, project, line, intent):
    inputs, guard = line.input_payload, line.guard_snapshot
    target = owned(db, TranslationRevision, project, line.translation_revision_id)
    reference = owned(db, ReferenceVersion, project, line.reference_version_id)
    binding = owned(db, VoiceBindingVersion, project, line.binding_version_id)
    root = owned(db, VoiceBinding, project, binding.binding_id)
    asset = owned(db, Asset, project, reference.audio_asset_id)
    track = owned(db, LanguageTrack, project, line.track_id)
    segment = owned(db, Segment, project, line.segment_id)
    source = owned(db, SegmentRevision, project, guard["source_revision_id"])
    transcript = owned(db, TranscriptRevision, project, intent.transcript_id)
    try:
        config = resolve_revision(
            db, project.workspace_id, "synthesis", inputs["connection_revision"]
        )
        controls = Controls.model_validate(inputs["controls"]).model_dump()
    except (LookupError, ValueError, TypeError):
        invalid()
    if (
        line.reference_version_id != inputs["reference_version_id"]
        or line.binding_version_id != inputs["binding_version_id"]
        or binding.reference_version_id != reference.id
        or reference.text != inputs["reference_text"]
        or reference.sha256 != inputs["reference_sha256"]
        or asset.sha256 != reference.sha256
        or reference.audio_asset_id != inputs["reference_asset_id"]
        or target.track_id != track.id
        or target.segment_id != line.segment_id
        or target.text != inputs["text"]
        or track.tag != inputs["target"]
        or inputs["model_language"] != resolve(track.tag)["model_name"]
        or controls != inputs["controls"]
        or config != inputs["config"]
        or target.source_text_fingerprint != guard["source_text_fingerprint"]
        or source.segment_id != line.segment_id
        or fingerprint(source.text) != guard["source_text_fingerprint"]
        or segment.transcript_id != transcript.id
        or transcript.selection_id != intent.source_selection_id
        or guard["source_selection_id"] != intent.source_selection_id
        or guard["transcript_id"] != intent.transcript_id
        or guard["selection_revision"] != intent.selection_revision
        or guard["translation_revision_id"] != target.id
        or inputs["voice_inputs"].get("voice." + root.scope_key) != fingerprint(binding.id)
        or any(inputs["voice_inputs"].get(k) != v for k, v in reference.dependency_snapshot.items())
    ):
        invalid()

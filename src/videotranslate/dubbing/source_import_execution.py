"""Recoverable download/probe/storage outside SQL; publication only binds assets."""

import tempfile
import time
from pathlib import Path
from uuid import UUID

from ..errors import APIError
from ..execution import prepared_media
from ..execution.contracts import FailureCode, StageFailure
from ..execution.prepared import Operations, current_operation
from ..models.core import Project
from ..models.source_import import SourceImport
from ..providers.vault import decrypt_credential
from .ownership import conflict, owned


def options(value):
    try:
        if set(value) != {"command_id"} or str(UUID(value["command_id"])) != value["command_id"]:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise APIError(422, "INVALID_OPTIONS", "Invalid source import command") from None
    return value


def inputs(db, project, request):
    command = owned(db, SourceImport, project, request.options["command_id"])
    if request.segment_id is not None or request.target_language is not None:
        raise APIError(422, "INVALID_SCOPE", "Source import accepts no target or segment")
    if project.revision != command.expected_revision:
        conflict()
    # Guarded by project revision; do not depend on source.video, which this run
    # replaces atomically. This also preserves the successful import history.
    return {}


def command_scope(request):
    return request.options["command_id"]


def publication_current(db, run):
    project = db.get(Project, run.project_id)
    command = owned(db, SourceImport, project, run.options["command_id"])
    return project.revision == command.expected_revision


def handler(context):
    from ..media import source_download
    from ..media.probe import probe_path

    operations = Operations(context)
    if cached := operations.cached():
        return cached
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        command = owned(db, SourceImport, project, run.options["command_id"])
        url = decrypt_credential(context.settings, project.workspace_id, command.encrypted_url)
        adapter = command.adapter
    operation = operations.prepare(provider="public_https", model="source_import")
    context.check_active()
    # Metadata extraction and the complete download share one wall-clock budget.
    deadline = time.monotonic() + 300
    maximum = min(context.settings.upload_max_bytes, context.settings.probe_max_bytes)
    http = source_download.make_http(context.settings)
    try:
        with tempfile.TemporaryDirectory(prefix="videotranslate-import-") as directory:
            path = Path(directory) / "source.mp4"
            if adapter == "youtube":
                from ..media.youtube_source import resolve_video

                url = resolve_video(
                    http,
                    url,
                    deadline=deadline,
                    check_active=context.check_active,
                    max_duration=context.settings.probe_max_duration_seconds,
                )
            with path.open("wb") as output:
                metadata = http.fetch(
                    url,
                    output,
                    max_bytes=maximum,
                    deadline=deadline,
                    check_active=context.check_active,
                    youtube=adapter == "youtube",
                )
            facts = probe_path(context, path)
            # ffprobe already validated an allowed local container. Identify its
            # media type from bytes rather than the remote declaration or URL.
            with path.open("rb") as source:
                header = source.read(12)
            if header[4:8] == b"ftyp":
                format = "mov" if header[8:12] == b"qt  " else "mp4"
            elif header[:4] == b"\x1aE\xdf\xa3":
                format = "mkv"  # WebM is the restricted Matroska subset.
            elif header[:4] == b"RIFF" and header[8:12] == b"AVI ":
                format = "avi"
            elif header[4:8] in {b"moov", b"mdat", b"wide"}:
                format = "mov"
            else:
                raise StageFailure(FailureCode.INVALID_MEDIA)
            object_id = prepared_media.store(
                context, operation.id, path, metadata, kind="source_video", format=format
            )
            entry = dict(object_id=object_id, metadata=metadata, kind="source_video", format=format)
            return operations.cache(
                {"entries": [entry], "probe": facts},
                {"byte_size": metadata["byte_size"], "probe": facts},
            )
    except source_download.ImportRejected:
        raise StageFailure(FailureCode.INVALID_MEDIA) from None
    except StageFailure:
        raise
    except (ValueError, OSError):
        raise StageFailure(FailureCode.INVALID_MEDIA) from None
    finally:
        http.close()


def publish(db, run, result):
    from ..execution.contracts import RunCreate
    from ..execution.events import append_event
    from ..execution.inputs import set_inputs
    from ..execution.service import create_run
    from ..models.core import Asset
    from ..routes.projects import update_project

    project = db.get(Project, run.project_id)
    command = owned(db, SourceImport, project, run.options["command_id"])
    operation = current_operation(db, run)
    if not operation or operation.id != result.prepared_id or not publication_current(db, run):
        raise ValueError("Invalid source import publication")
    payload = operation.prepared_payload
    assets = prepared_media.publish(db, run, payload["entries"])
    asset_id = next(iter(assets.values()))
    asset = db.get(Asset, asset_id)
    update_project(
        db,
        project,
        {"source_asset_id": asset_id, "source_track_index": 0, "status": "uploaded"},
        expected_revision=command.expected_revision,
    )
    set_inputs(db, project, {"source.video": {"asset_id": asset.id, "sha256": asset.sha256}})
    command.source_asset_id = asset_id
    # Probe is an ordinary durable follow-up run, never media work in SQL.
    probe = create_run(db, project.workspace_id, project.id, RunCreate(stage="probe"))
    command.probe_run_id = probe.id
    append_event(
        db,
        project,
        "source.import_completed",
        run=run,
        facts={"asset_id": asset_id, "byte_size": asset.byte_size},
    )

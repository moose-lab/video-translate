"""Typed track defaults and independently versioned line overrides."""

from ..models.core import new_id
from ..models.synthesis import VoiceSettings, VoiceSettingsVersion
from .ownership import changed, conflict, owned, owner, scope
from .segments import active_segment
from .source import active_source
from .synthesis_contracts import Controls
from .translations import track_for

CONTROL_NAMES = tuple(Controls.model_fields)


def settings_for(db, project, track, segment_id=None):
    key = "line:" + segment_id if segment_id else "track"
    return db.scalar(
        scope(VoiceSettings, project).where(
            VoiceSettings.track_id == track.id, VoiceSettings.scope_key == key
        )
    )


def effective_controls(db, project, track, segment_id, provider_controls=None):
    values = Controls.model_validate(provider_controls or {}).model_dump()
    versions = []
    for identity in (None, segment_id):
        root = settings_for(db, project, track, identity)
        if root:
            version = owned(db, VoiceSettingsVersion, project, root.current_version_id)
            versions.append(version.id)
            if version.override:
                versions = [version.id]
                values = {key: getattr(version, key) for key in CONTROL_NAMES}
    return values, versions


def settings_json(db, project, track, segment_id=None, limit=100, offset=0):
    from sqlalchemy import func, select

    root = settings_for(db, project, track, segment_id)
    from .workflow import connection

    config = connection(db, project, "synthesis")
    provider_controls = config.settings.get("controls") if config else None
    controls, _ = effective_controls(db, project, track, segment_id or "", provider_controls)
    if root is None:
        return {"revision": 0, "override": False, "controls": controls, "history": [], "total": 0}
    query = scope(VoiceSettingsVersion, project).where(VoiceSettingsVersion.settings_id == root.id)
    rows = db.scalars(
        query.order_by(VoiceSettingsVersion.revision.desc()).limit(limit).offset(offset)
    )
    current = owned(db, VoiceSettingsVersion, project, root.current_version_id)
    return {
        "revision": root.revision,
        "override": current.override,
        "controls": controls,
        "total": db.scalar(select(func.count()).select_from(query.subquery())),
        "history": [
            {
                "id": row.id,
                "revision": row.revision,
                "parent_version_id": row.parent_version_id,
                "override": row.override,
                "controls": {k: getattr(row, k) for k in CONTROL_NAMES},
                "actor_id": row.actor_id,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


def put_settings(db, project, tag, segment_id, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=segment_id is not None)
    track = track_for(db, project, tag)
    if segment_id:
        active_segment(db, project, transcript, segment_id)
    root = settings_for(db, project, track, segment_id)
    if (root.revision if root else 0) != body.revision:
        conflict()
    if root is None:
        root = VoiceSettings(
            id=new_id(),
            **owner(project),
            track_id=track.id,
            segment_id=segment_id,
            scope_key="line:" + segment_id if segment_id else "track",
        )
        db.add(root)
        db.flush()
    version = VoiceSettingsVersion(
        id=new_id(),
        **owner(project),
        settings_id=root.id,
        track_id=track.id,
        parent_version_id=root.current_version_id,
        revision=root.revision + 1,
        override=body.controls is not None,
        actor_id=actor,
        **(body.controls or Controls()).model_dump(),
    )
    db.add(version)
    db.flush()
    root.current_version_id, root.revision = version.id, version.revision
    changed(
        db,
        project,
        "synthesis.controls_changed",
        track_id=track.id,
        revision=root.revision,
        **({"segment_id": segment_id} if segment_id else {}),
    )
    return settings_json(db, project, track, segment_id)

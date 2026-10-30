"""Project defaults with immutable exact revisions, independent of inference settings."""

from sqlalchemy import func, select

from ..execution.inputs import set_inputs
from ..models.core import new_id
from ..models.finishing import FitSettingsState, FitSettingsVersion
from .fit_contracts import POLICY, FitSettingsBody
from .ownership import changed, conflict, owned, owner, scope


def settings_for(db, project):
    return db.scalar(scope(FitSettingsState, project))


def current(db, project):
    root = settings_for(db, project)
    version = owned(db, FitSettingsVersion, project, root.current_version_id) if root else None
    return root, version


def settings_json(db, project, limit=100, offset=0):
    root, version = current(db, project)
    result = dict(
        revision=root.revision if root else 0,
        policy=POLICY,
        settings=version.settings if version else FitSettingsBody().model_dump(),
        history=[],
        total=0,
    )
    if root:
        query = scope(FitSettingsVersion, project).where(FitSettingsVersion.settings_id == root.id)
        result["total"] = db.scalar(select(func.count()).select_from(query.subquery()))
        result["history"] = [
            dict(
                id=v.id,
                revision=v.revision,
                parent_version_id=v.parent_version_id,
                settings=v.settings,
                policy=v.policy,
                actor_id=v.actor_id,
                created_at=v.created_at,
            )
            for v in db.scalars(
                query.order_by(FitSettingsVersion.revision.desc()).limit(limit).offset(offset)
            )
        ]
    return result


def put_settings(db, project, body, actor):
    root, prior = current(db, project)
    if body.revision != (root.revision if root else 0):
        conflict()
    values = body.settings.model_dump()
    # Canonical no-ops preserve current plans, but the first explicit defaults save is historical.
    if prior and prior.settings == values:
        return settings_json(db, project)
    if root is None:
        root = FitSettingsState(id=new_id(), **owner(project))
        db.add(root)
        db.flush()
    version = FitSettingsVersion(
        id=new_id(),
        **owner(project),
        settings_id=root.id,
        parent_version_id=root.current_version_id,
        revision=root.revision + 1,
        settings=values,
        policy=POLICY,
        actor_id=actor,
    )
    db.add(version)
    db.flush()
    root.current_version_id, root.revision = version.id, version.revision
    set_inputs(
        db,
        project,
        {
            "finishing.fit_settings": {
                "revision": version.revision,
                "settings": values,
                "policy": POLICY,
            }
        },
    )
    changed(db, project, "finishing.settings_changed", revision=version.revision)
    return settings_json(db, project)

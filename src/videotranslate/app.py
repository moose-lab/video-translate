"""ASGI app factory. Production schema migration is an explicit deployment operation."""

from fastapi import FastAPI

from .config import Settings
from .db import Base, make_engine, make_session_factory
from .errors import install_error_handlers
from .routes import assets, auth, dubbing, events, languages, projects, providers, runs
from .storage import make_storage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Video Translate", debug=settings.debug and not settings.is_production)
    app.state.settings = settings
    app.state.storage = make_storage(settings)
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    if not settings.is_production:
        Base.metadata.create_all(app.state.engine)
    install_error_handlers(app)
    app.include_router(auth.router, prefix="/api")
    app.include_router(languages.router, prefix="/api")
    app.include_router(providers.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(assets.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(dubbing.router, prefix="/api")
    return app

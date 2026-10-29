"""Explicit schema migration; importing the API does not migrate production databases."""

from sqlalchemy import create_engine, pool

from alembic import context
from videotranslate.config import Settings
from videotranslate.db import Base
from videotranslate.models import core, execution, providers  # noqa: F401

config = context.config
url = config.get_main_option("sqlalchemy.url") or Settings().database_url.get_secret_value()

if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()

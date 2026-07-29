from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.alerts import models as alert_models
from app.analysis import models as analysis_models
from app.config import settings
from app.db import Base
from app.evaluation import models as evaluation_models
from app.ingestion import models as ingestion_models
from app.jobs import models as job_models
from app.remediation import models as remediation_models
from app.retest import models as retest_models
from app.shared import audit

MODEL_MODULES = (
    alert_models,
    analysis_models,
    audit,
    evaluation_models,
    ingestion_models,
    job_models,
    remediation_models,
    retest_models,
)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

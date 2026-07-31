from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def initialize_database() -> None:
    from app.models.processing_job import ProcessingJob  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)


def migrate_sqlite_schema(database_engine: object) -> None:
    if database_engine.dialect.name == "sqlite":
        columns = {
            column["name"]
            for column in inspect(database_engine).get_columns("processing_jobs")
        }
        if "inference_device" not in columns:
            with database_engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE processing_jobs ADD COLUMN inference_device VARCHAR(16)")
                )

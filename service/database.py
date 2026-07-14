from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    user_story: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    frontend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    backend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    endpoints: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts: Mapped[list] = mapped_column(JSON, nullable=False)


def create_db_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(database_url: str):
    engine = create_db_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def _ensure_job_option_columns(engine) -> None:
    """Add new columns on existing DBs created before these fields existed."""
    statements = (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS base_url VARCHAR(2048)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS frontend BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS backend BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS endpoints JSON",
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def init_db(engine) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_job_option_columns(engine)

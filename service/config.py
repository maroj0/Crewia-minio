from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_root: Path = Path(__file__).resolve().parent.parent
    jobs_workspace_root: Path = Path("/tmp/jobs")
    max_concurrent_jobs: int = 1

    google_api_key: str | None = None
    gemini_api_key: str | None = None

    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "qa-crew"
    minio_secure: bool = False
    minio_presign_expiry_hours: int = 1

    database_url: str = "postgresql+psycopg2://qa:qa@localhost:5432/qa"


@lru_cache
def get_settings() -> Settings:
    return Settings()

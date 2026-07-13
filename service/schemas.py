from enum import Enum
from pydantic import BaseModel, Field


class JobStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class CreateJobRequest(BaseModel):
    user_story: str = Field(..., min_length=1, description="Texto de la historia de usuario")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_story": (
                        "Como usuario registrado quiero iniciar sesión con email y contraseña "
                        "para acceder a mi panel privado."
                    )
                }
            ]
        }
    }


class ArtifactInfo(BaseModel):
    key: str
    size: int | None = None
    last_modified: str | None = None
    download_url: str | None = Field(
        default=None,
        description="URL firmada de MinIO para descargar el archivo (expira).",
    )


class JobResponse(BaseModel):
    job_id: str
    status: JobStatusEnum
    created_at: str
    updated_at: str
    error: str | None = None
    result_summary: str | None = None
    artifacts: list[ArtifactInfo] = Field(default_factory=list)


class ArtifactsResponse(BaseModel):
    job_id: str
    artifacts: list[ArtifactInfo]


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    jobs: list[JobResponse]

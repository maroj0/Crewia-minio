from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ArtifactInfo(BaseModel):
    key: str
    size: int | None = None
    last_modified: str | None = None
    download_url: str | None = Field(
        default=None,
        description="URL firmada de MinIO para descargar el archivo (expira).",
    )


class FlowInfo(BaseModel):
    id: str
    name: str
    description: str
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    request_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema del contrato POST /api/v1/jobs para este flujo.",
    )


class FlowListResponse(BaseModel):
    flows: list[FlowInfo]


class JobResponse(BaseModel):
    job_id: str
    flow: str = "qa"
    status: JobStatusEnum
    created_at: str
    updated_at: str
    error: str | None = None
    result_summary: str | None = None
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    flow_inputs: dict[str, Any] | None = Field(
        default=None,
        description="Payload específico del flujo usado al crear el job.",
    )
    base_url: str | None = None
    frontend: bool | None = None
    backend: bool | None = None
    endpoints: list[dict[str, Any]] | None = None
    user_story: str | None = None


class ArtifactsResponse(BaseModel):
    job_id: str
    artifacts: list[ArtifactInfo]


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    jobs: list[JobResponse]

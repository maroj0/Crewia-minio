from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated, Union

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from service.config import get_settings
from service.crew_runner import CrewRunner
from service.flow_registry import list_flows
from service.job_store import JobStatus, JobStore
from service.minio_client import MinioStorage
from service.schemas import (
    ArtifactInfo,
    ArtifactsResponse,
    CreateQaJobRequest,
    CreateSddJobRequest,
    FlowInfo,
    FlowListResponse,
    JobListResponse,
    JobResponse,
    JobStatusEnum,
)

settings = get_settings()
load_dotenv(settings.project_root / ".env", override=True)

storage = MinioStorage(settings)
job_store = JobStore(settings.database_url)
crew_runner = CrewRunner(settings, storage, job_store)

API_DESCRIPTION = """
API para ejecutar flujos Crew.ai (QA, SDD, etc.) de forma asíncrona.

## Flujo
1. **GET /api/v1/flows** — lista flujos disponibles y el schema de cada contrato.
2. **POST /api/v1/jobs** — envía `flow` + payload específico del flujo y recibe un `job_id`.
3. **GET /api/v1/jobs/{job_id}** — consulta el estado del job.
4. **GET /api/v1/jobs/{job_id}/artifacts** — lista archivos generados en MinIO.
5. **POST /api/v1/jobs/{job_id}/retry** — reintenta un job fallido.

Cada flujo valida su propio contrato. Metadata en PostgreSQL, archivos en MinIO.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Healthcheck del servicio."},
    {"name": "flows", "description": "Flujos Crew.ai disponibles para jobs."},
    {"name": "jobs", "description": "Creación, consulta y listado de jobs."},
    {"name": "artifacts", "description": "Artefactos generados por cada job."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(job_store.initialize)
    await asyncio.to_thread(storage.ensure_bucket)
    yield


app = FastAPI(
    title="Crew API",
    description=API_DESCRIPTION,
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=TAGS_METADATA,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/swagger")


def _to_job_response(record) -> JobResponse:
    is_qa = record.flow == "qa"
    flow_inputs = record.flow_inputs
    user_story = None
    if is_qa:
        user_story = (flow_inputs or {}).get("user_story") or record.user_story or None
    elif flow_inputs:
        user_story = record.user_story or None

    return JobResponse(
        job_id=record.job_id,
        flow=record.flow,
        status=JobStatusEnum(record.status.value),
        created_at=record.created_at,
        updated_at=record.updated_at,
        error=record.error,
        result_summary=record.result_summary,
        artifacts=[ArtifactInfo(**artifact) for artifact in record.artifacts],
        flow_inputs=flow_inputs,
        user_story=user_story,
        base_url=(flow_inputs or {}).get("base_url") if is_qa else None,
        frontend=(flow_inputs or {}).get("frontend") if is_qa else None,
        backend=(flow_inputs or {}).get("backend") if is_qa else None,
        endpoints=(flow_inputs or {}).get("endpoints") if is_qa else None,
    )


@app.get("/health", tags=["health"], summary="Healthcheck")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
    summary="Crear job",
    response_description="Job encolado para ejecución asíncrona.",
)
async def create_job(
    request: Annotated[
        Union[CreateQaJobRequest, CreateSddJobRequest],
        Body(discriminator="flow"),
    ],
    background_tasks: BackgroundTasks,
) -> JobResponse:
    """
    Crea un job según el flujo indicado en `flow`. Cada flujo exige su propio contrato:

    - **qa**: `user_story`, opcionalmente `base_url`, `frontend`, `backend`, `endpoints`.
    - **sdd**: `documents` (funcional + técnico + tareas en MinIO) **o** `crew_file` (crew.jsonc en MinIO).
    """
    flow_inputs = request.to_flow_inputs()
    prefix = None

    if isinstance(request, CreateQaJobRequest):
        endpoints_payload = (
            [endpoint.model_dump(mode="json") for endpoint in request.endpoints]
            if request.endpoints
            else None
        )
        record = await job_store.create_job(
            flow="qa",
            flow_inputs=flow_inputs,
            user_story=request.user_story,
            base_url=request.base_url,
            frontend=request.frontend,
            backend=request.backend,
            endpoints=endpoints_payload,
        )
        prefix = storage.job_prefix(record.job_id)
        await asyncio.to_thread(
            storage.upload_text,
            f"{prefix}/input/historia_usuario.txt",
            request.user_story,
        )
        if endpoints_payload is not None:
            await asyncio.to_thread(
                storage.upload_json,
                f"{prefix}/input/endpoints.json",
                endpoints_payload,
            )
    else:
        record = await job_store.create_job(
            flow="sdd",
            flow_inputs=flow_inputs,
            user_story="",
            frontend=False,
            backend=False,
        )
        prefix = storage.job_prefix(record.job_id)

    await asyncio.to_thread(
        storage.upload_json,
        f"{prefix}/input/flow_inputs.json",
        flow_inputs,
    )
    background_tasks.add_task(crew_runner.run_job, record.job_id)
    return _to_job_response(record)


@app.get(
    "/api/v1/flows",
    response_model=FlowListResponse,
    tags=["flows"],
    summary="Listar flujos disponibles",
)
async def list_available_flows() -> FlowListResponse:
    return FlowListResponse(flows=[FlowInfo(**flow.to_info()) for flow in list_flows()])


@app.get(
    "/api/v1/jobs",
    response_model=JobListResponse,
    tags=["jobs"],
    summary="Listar jobs",
)
async def list_jobs(
    status_filter: JobStatusEnum | None = Query(
        default=None,
        alias="status",
        description="Filtrar por estado del job.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    job_status = JobStatus(status_filter.value) if status_filter else None
    records, total = await job_store.list_jobs(status=job_status, limit=limit, offset=offset)
    return JobListResponse(
        total=total,
        limit=limit,
        offset=offset,
        jobs=[_to_job_response(record) for record in records],
    )


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobResponse,
    tags=["jobs"],
    summary="Obtener job por ID",
)
async def get_job(job_id: str) -> JobResponse:
    record = await job_store.get_job(job_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _to_job_response(record)


@app.post(
    "/api/v1/jobs/{job_id}/retry",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
    summary="Reintentar job fallido",
)
async def retry_job(job_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    record = await job_store.get_job(job_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if record.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed jobs can be retried",
        )

    updated = await job_store.update_job(
        job_id,
        status=JobStatus.PENDING,
        error=None,
        result_summary=None,
        artifacts=[],
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    background_tasks.add_task(crew_runner.run_job, updated.job_id)
    return _to_job_response(updated)


@app.get(
    "/api/v1/jobs/{job_id}/artifacts",
    response_model=ArtifactsResponse,
    tags=["artifacts"],
    summary="Listar artefactos del job",
)
async def get_job_artifacts(job_id: str) -> ArtifactsResponse:
    record = await job_store.get_job(job_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    artifacts = await asyncio.to_thread(storage.list_objects, storage.job_prefix(job_id))
    return ArtifactsResponse(
        job_id=job_id,
        artifacts=[ArtifactInfo(**artifact) for artifact in artifacts],
    )

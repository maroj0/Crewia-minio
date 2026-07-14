from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from service.config import get_settings
from service.crew_runner import CrewRunner
from service.job_store import JobStatus, JobStore
from service.minio_client import MinioStorage
from service.schemas import (
    ArtifactInfo,
    ArtifactsResponse,
    CreateJobRequest,
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
API para generar test cases y automatizaciones Playwright a partir de historias de usuario.

## Flujo
1. **POST /api/v1/jobs** — envía la historia de usuario y recibe un `job_id`.
2. **GET /api/v1/jobs/{job_id}** — consulta el estado del job.
3. **GET /api/v1/jobs/{job_id}/artifacts** — lista archivos generados en MinIO.
4. **POST /api/v1/jobs/{job_id}/retry** — reintenta un job fallido con la misma HU.

Los jobs se ejecutan de forma asíncrona. Metadata en PostgreSQL, archivos en MinIO.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Healthcheck del servicio."},
    {"name": "jobs", "description": "Creación, consulta y listado de jobs de QA."},
    {"name": "artifacts", "description": "Artefactos generados por cada job."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(job_store.initialize)
    await asyncio.to_thread(storage.ensure_bucket)
    yield


app = FastAPI(
    title="QA Crew API",
    description=API_DESCRIPTION,
    version="1.0.0",
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
    return JobResponse(
        job_id=record.job_id,
        status=JobStatusEnum(record.status.value),
        created_at=record.created_at,
        updated_at=record.updated_at,
        error=record.error,
        result_summary=record.result_summary,
        artifacts=[ArtifactInfo(**artifact) for artifact in record.artifacts],
    )


@app.get("/health", tags=["health"], summary="Healthcheck")
async def health() -> dict[str, str]:
    """Verifica que el servicio esté en línea."""
    return {"status": "ok"}


@app.post(
    "/api/v1/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
    summary="Crear job de QA",
    response_description="Job encolado para ejecución asíncrona.",
)
async def create_job(request: CreateJobRequest, background_tasks: BackgroundTasks) -> JobResponse:
    """
    Recibe una historia de usuario en JSON y dispara el crew de CrewAI en background.

    El crew genera test cases y automatizaciones Playwright. Usá el `job_id` devuelto
    para consultar el progreso.
    """
    record = await job_store.create_job(request.user_story)
    prefix = storage.job_prefix(record.job_id)
    await asyncio.to_thread(
        storage.upload_text,
        f"{prefix}/input/historia_usuario.txt",
        request.user_story,
    )
    background_tasks.add_task(crew_runner.run_job, record.job_id, request.user_story)
    return _to_job_response(record)


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
    limit: int = Query(default=20, ge=1, le=100, description="Cantidad máxima de resultados."),
    offset: int = Query(default=0, ge=0, description="Desplazamiento para paginación."),
) -> JobListResponse:
    """Lista jobs persistidos en PostgreSQL, con paginación y filtro opcional por estado."""
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
    """Devuelve el estado y metadata de un job específico."""
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
    response_description="Job reencolado para ejecución asíncrona.",
)
async def retry_job(job_id: str, background_tasks: BackgroundTasks) -> JobResponse:
    """
    Reintenta un job en estado `failed` usando la misma historia de usuario guardada.

    Reinicia el estado a `pending`, limpia error/resultados previos y vuelve a
    ejecutar el crew en background con el mismo `job_id`.
    """
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

    background_tasks.add_task(crew_runner.run_job, updated.job_id, updated.user_story)
    return _to_job_response(updated)


@app.get(
    "/api/v1/jobs/{job_id}/artifacts",
    response_model=ArtifactsResponse,
    tags=["artifacts"],
    summary="Listar artefactos del job",
)
async def get_job_artifacts(job_id: str) -> ArtifactsResponse:
    """Lista los archivos generados en MinIO e incluye URLs firmadas de descarga."""
    record = await job_store.get_job(job_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    artifacts = await asyncio.to_thread(storage.list_objects, storage.job_prefix(job_id))
    return ArtifactsResponse(
        job_id=job_id,
        artifacts=[ArtifactInfo(**artifact) for artifact in artifacts],
    )

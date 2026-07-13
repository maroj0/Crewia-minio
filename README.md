# qa

A crewAI project using JSON-first configuration, exposed as a FastAPI microservice with PostgreSQL and MinIO storage.

## Running with Docker (recommended)

1. Copy environment variables:

```bash
cp .env.example .env
```

2. Set your `GOOGLE_API_KEY` / `GEMINI_API_KEY` in `.env`.

3. Start services:

```bash
docker compose up --build
```

Services:
- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/swagger`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- PostgreSQL: `localhost:5432` (user/pass/db: `qa` / `qa` / `qa`)
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001` (user/pass: `minioadmin` / `minioadmin`)

## API usage

Create a job (async):

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d "{\"user_story\": \"Como usuario registrado quiero iniciar sesión para acceder a mi panel.\"}"
```

Check job status:

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

List jobs (optionally filter by status):

```bash
curl "http://localhost:8000/api/v1/jobs"
curl "http://localhost:8000/api/v1/jobs?status=completed&limit=10&offset=0"
```

List artifacts stored in MinIO (includes signed `download_url`):

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}/artifacts
```

Each artifact includes a temporary `download_url` (presigned MinIO URL, default 1h expiry).

Retry a failed job (same `job_id` and stored user story):

```bash
curl -X POST http://localhost:8000/api/v1/jobs/{job_id}/retry
```

Healthcheck:

```bash
curl http://localhost:8000/health
```

## Storage layout

**PostgreSQL** stores job metadata (status, timestamps, errors, artifact index).

**MinIO** stores file artifacts under:

```
jobs/{job_id}/input/historia_usuario.txt
jobs/{job_id}/output/test-cases/*
jobs/{job_id}/output/playwright/*
```

## Running locally without Docker

```bash
pip install .
uvicorn service.main:app --reload --port 8000
```

Ensure PostgreSQL, MinIO, and `.env` are configured.

## Running the crew via CLI

```bash
crewai run
```

## Project Structure

- `agents/` - Agent definitions (JSONC)
- `crew.jsonc` - Crew definition with tasks and configuration
- `service/` - FastAPI microservice
- `tools/` - Custom tools (Python)
- `knowledge/` - Knowledge files for agents
- `docker-compose.yml` - API + PostgreSQL + MinIO stack
- `Dockerfile` - API container image

> **Note:** `custom:<name>` tool references execute `tools/<name>.py` as local
> Python code when the crew loads. Only run crew projects from sources you
> trust.

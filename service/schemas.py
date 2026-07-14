from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class JobStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class ApiEndpoint(BaseModel):
    """Definición de un endpoint de backend a probar."""

    method: HttpMethod = Field(..., description="Método HTTP")
    path: str = Field(..., min_length=1, description="Ruta del endpoint. Ej: /api/v1/login")
    name: str | None = Field(default=None, description="Nombre corto opcional del endpoint")
    description: str | None = Field(default=None, description="Qué hace / qué validar")
    headers: dict[str, str] = Field(default_factory=dict, description="Headers de ejemplo")
    query: dict[str, Any] = Field(default_factory=dict, description="Query params de ejemplo")
    body: Any | None = Field(default=None, description="Body de ejemplo (JSON u otro)")
    expected_status: int | list[int] | None = Field(
        default=None,
        description="Status HTTP esperado (uno o varios)",
    )
    auth_required: bool = Field(default=False, description="Si requiere autenticación")
    tags: list[str] = Field(default_factory=list, description="Tags libres (ej. auth, perfil)")

    @model_validator(mode="after")
    def normalize_path(self) -> "ApiEndpoint":
        path = self.path.strip()
        if not path.startswith("/"):
            path = "/" + path
        self.path = path
        self.method = self.method.upper()  # type: ignore[assignment]
        return self


class CreateJobRequest(BaseModel):
    user_story: str = Field(..., min_length=1, description="Texto de la historia de usuario")
    base_url: str | None = Field(
        default=None,
        description="URL opcional del ambiente bajo prueba (Playwright baseURL). Ej: https://staging.miapp.com",
    )
    frontend: bool = Field(
        default=True,
        description="Si true, genera casos y automatizaciones orientadas a UI/Frontend (Playwright E2E).",
    )
    backend: bool = Field(
        default=False,
        description="Si true, genera casos y automatizaciones orientadas a Backend/API.",
    )
    endpoints: list[ApiEndpoint] | None = Field(
        default=None,
        description=(
            "Lista de endpoints a probar cuando backend=true. "
            "Se guarda en input/endpoints.json y alimenta test cases + specs API."
        ),
    )

    @model_validator(mode="after")
    def validate_targets_and_url(self) -> "CreateJobRequest":
        if not self.frontend and not self.backend:
            raise ValueError("Debés habilitar al menos uno: frontend=true y/o backend=true")
        if self.base_url is not None:
            url = self.base_url.strip()
            if not url:
                self.base_url = None
            else:
                if not (url.startswith("http://") or url.startswith("https://")):
                    raise ValueError("base_url debe empezar con http:// o https://")
                self.base_url = url.rstrip("/")
        if self.backend:
            if not self.endpoints:
                raise ValueError("Si backend=true, debés enviar endpoints (lista no vacía de endpoints a probar)")
        elif self.endpoints:
            raise ValueError("endpoints solo aplica cuando backend=true")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_story": (
                        "Como usuario registrado quiero iniciar sesión con email y contraseña "
                        "para acceder a mi panel privado."
                    ),
                    "base_url": "https://staging.example.com",
                    "frontend": True,
                    "backend": False,
                },
                {
                    "user_story": "Como sistema quiero validar el login y el perfil vía API.",
                    "base_url": "https://api.staging.example.com",
                    "frontend": False,
                    "backend": True,
                    "endpoints": [
                        {
                            "method": "POST",
                            "path": "/api/v1/login",
                            "name": "login",
                            "description": "Autenticación con email y password",
                            "headers": {"Content-Type": "application/json"},
                            "body": {"email": "qa@example.com", "password": "Secret123!"},
                            "expected_status": 200,
                            "auth_required": False,
                            "tags": ["auth"],
                        },
                        {
                            "method": "GET",
                            "path": "/api/v1/me",
                            "name": "perfil",
                            "description": "Obtener datos del usuario autenticado",
                            "expected_status": [200, 401],
                            "auth_required": True,
                            "tags": ["perfil"],
                        },
                    ],
                },
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
    base_url: str | None = None
    frontend: bool = True
    backend: bool = False
    endpoints: list[ApiEndpoint] | None = None


class ArtifactsResponse(BaseModel):
    job_id: str
    artifacts: list[ArtifactInfo]


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    jobs: list[JobResponse]

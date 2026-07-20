from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


class QaJobInputs(BaseModel):
    user_story: str
    base_url: str | None = None
    frontend: bool = True
    backend: bool = False
    endpoints: list[ApiEndpoint] | None = None


class CreateQaJobRequest(BaseModel):
    flow: Literal["qa"] = Field(default="qa", description="Flujo de generación de test cases y Playwright.")
    user_story: str = Field(..., min_length=1, description="Texto de la historia de usuario")
    base_url: str | None = Field(
        default=None,
        description="URL opcional del ambiente bajo prueba (Playwright baseURL).",
    )
    frontend: bool = Field(
        default=True,
        description="Si true, genera casos y automatizaciones orientadas a UI/Frontend.",
    )
    backend: bool = Field(
        default=False,
        description="Si true, genera casos y automatizaciones orientadas a Backend/API.",
    )
    endpoints: list[ApiEndpoint] | None = Field(
        default=None,
        description="Lista de endpoints a probar cuando backend=true.",
    )

    @model_validator(mode="after")
    def validate_qa_contract(self) -> "CreateQaJobRequest":
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
                raise ValueError(
                    "Si backend=true, debés enviar endpoints (lista no vacía de endpoints a probar)"
                )
        elif self.endpoints:
            raise ValueError("endpoints solo aplica cuando backend=true")
        return self

    def to_flow_inputs(self) -> dict[str, Any]:
        return QaJobInputs(
            user_story=self.user_story,
            base_url=self.base_url,
            frontend=self.frontend,
            backend=self.backend,
            endpoints=self.endpoints,
        ).model_dump(mode="json")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "flow": "qa",
                    "user_story": "Como usuario registrado quiero iniciar sesión para acceder a mi panel.",
                    "frontend": True,
                    "backend": False,
                }
            ]
        }
    }

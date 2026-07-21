from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BacklogJobInputs(BaseModel):
    generate_epics: bool = True
    generate_hus: bool = False
    funcional_minio_path: str
    epics_minio_path: str | None = None
    epicas_seleccionadas: str = "TODAS"
    sistema: str = "el sistema descrito en el documento funcional"


class CreateBacklogJobRequest(BaseModel):
    flow: Literal["backlog"] = Field(
        default="backlog",
        description="Flujo de generación de backlog (épicas e historias de usuario).",
    )
    generate_epics: bool = Field(
        default=True,
        description="Si true, genera épicas a partir del documento funcional.",
    )
    generate_hus: bool = Field(
        default=False,
        description="Si true, genera historias de usuario.",
    )
    funcional_minio_path: str = Field(
        ...,
        min_length=1,
        description="Path en MinIO del documento funcional (ej: 'docs/proyecto/funcional.pdf').",
    )
    epics_minio_path: str | None = Field(
        default=None,
        description=(
            "Path en MinIO de un epics.md de una corrida previa. "
            "Requerido si generate_hus=true y generate_epics=false."
        ),
    )
    epicas_seleccionadas: str = Field(
        default="TODAS",
        description=(
            "'TODAS' o IDs de épicas separados por coma (ej: 'EP-001, EP-004'). "
            "Solo aplica cuando generate_hus=true."
        ),
    )
    sistema: str = Field(
        default="el sistema descrito en el documento funcional",
        description="Nombre del sistema para contextualizar los prompts del agente.",
    )

    @model_validator(mode="after")
    def validate_backlog_contract(self) -> "CreateBacklogJobRequest":
        if not self.generate_epics and not self.generate_hus:
            raise ValueError("Nada que generar: activá generate_epics y/o generate_hus.")
        if self.generate_hus and not self.generate_epics and not self.epics_minio_path:
            raise ValueError(
                "Para generar HUs se necesita epics.md de una corrida previa "
                "(epics_minio_path) o activar generate_epics en esta corrida."
            )
        return self

    def to_flow_inputs(self) -> dict[str, Any]:
        return BacklogJobInputs(
            generate_epics=self.generate_epics,
            generate_hus=self.generate_hus,
            funcional_minio_path=self.funcional_minio_path,
            epics_minio_path=self.epics_minio_path,
            epicas_seleccionadas=self.epicas_seleccionadas,
            sistema=self.sistema,
        ).model_dump(mode="json")

    def validation_warnings(self) -> list[str]:
        """Advertencias no bloqueantes (epicas_seleccionadas sin generate_hus, etc.)."""
        result: list[str] = []
        if self.epicas_seleccionadas != "TODAS" and not self.generate_hus:
            result.append(
                "epicas_seleccionadas solo aplica cuando generate_hus=true; el valor será ignorado."
            )
        return result

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "flow": "backlog",
                    "generate_epics": True,
                    "generate_hus": False,
                    "funcional_minio_path": "docs/cliente-x/funcional.pdf",
                    "sistema": "Sistema de Gestión Comercial",
                },
                {
                    "flow": "backlog",
                    "generate_epics": True,
                    "generate_hus": True,
                    "funcional_minio_path": "docs/cliente-x/funcional.pdf",
                    "epicas_seleccionadas": "TODAS",
                    "sistema": "Sistema de Gestión Comercial",
                },
                {
                    "flow": "backlog",
                    "generate_epics": False,
                    "generate_hus": True,
                    "funcional_minio_path": "docs/cliente-x/funcional.pdf",
                    "epics_minio_path": "outputs/cliente-x/epics.md",
                    "epicas_seleccionadas": "EP-001, EP-004",
                    "sistema": "Sistema de Gestión Comercial",
                },
            ]
        }
    }

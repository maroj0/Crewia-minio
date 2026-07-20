from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class MinioObjectRef(BaseModel):
    """Referencia a un objeto en MinIO: clave dentro del bucket configurado o URL."""

    ref: str = Field(..., min_length=1, description="Clave del objeto en MinIO o URL (presigned / http(s) / s3://).")

    @field_validator("ref")
    @classmethod
    def normalize_ref(cls, value: str) -> str:
        return value.strip()


class SddDocumentRefs(BaseModel):
    functional_document: MinioObjectRef = Field(..., description="Documento funcional.")
    technical_document: MinioObjectRef = Field(..., description="Documento técnico.")
    tasks: MinioObjectRef = Field(..., description="Listado de tareas (archivo de texto o JSON).")


class SddJobInputs(BaseModel):
    documents: SddDocumentRefs | None = None
    crew_file: MinioObjectRef | None = None


class CreateSddJobRequest(BaseModel):
    flow: Literal["sdd"] = Field(default="sdd", description="Flujo SDD (Software Design Document).")
    documents: SddDocumentRefs | None = Field(
        default=None,
        description="Referencias MinIO a documento funcional, técnico y listado de tareas.",
    )
    crew_file: MinioObjectRef | None = Field(
        default=None,
        description="Referencia MinIO a un crew.jsonc personalizado (define sus propios agentes/tasks).",
    )

    @model_validator(mode="after")
    def validate_sdd_contract(self) -> "CreateSddJobRequest":
        if self.documents and self.crew_file:
            raise ValueError("Enviá `documents` o `crew_file`, no ambos.")
        if not self.documents and not self.crew_file:
            raise ValueError(
                "Debés enviar `documents` (funcional + técnico + tareas) o `crew_file` (crew.jsonc en MinIO)."
            )
        return self

    def to_flow_inputs(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.documents:
            payload["documents"] = self.documents.model_dump(mode="json")
        if self.crew_file:
            payload["crew_file"] = self.crew_file.model_dump(mode="json")
        return payload

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "flow": "sdd",
                    "documents": {
                        "functional_document": {"ref": "projects/acme/functional.md"},
                        "technical_document": {"ref": "projects/acme/technical.md"},
                        "tasks": {"ref": "projects/acme/tasks.json"},
                    },
                },
                {
                    "flow": "sdd",
                    "crew_file": {"ref": "projects/acme/crew.jsonc"},
                },
            ]
        }
    }

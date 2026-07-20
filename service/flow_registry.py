from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from service.schemas.qa import CreateQaJobRequest
from service.schemas.sdd import CreateSddJobRequest

PostRunValidator = Callable[[Path], None]


class MissingPlaywrightArtifactsError(Exception):
    """Raised when Playwright suite files are missing after crew kickoff."""


class MissingTestCasesArtifactsError(Exception):
    """Raised when test-cases catalog files are missing or invalid after crew kickoff."""


def _validate_qa_test_cases_artifacts(workspace: Path) -> None:
    import os

    from tools.test_cases_guardrail import ensure_test_cases_md, validate_test_cases_files

    ensure_test_cases_md(workspace)

    json_path = workspace / "output" / "test-cases" / "test-cases.json"
    md_path = workspace / "output" / "test-cases" / "test-cases.md"
    if not json_path.is_file() or not md_path.is_file():
        raise MissingTestCasesArtifactsError(
            "Missing test-cases artifacts: required output/test-cases/test-cases.json "
            "and output/test-cases/test-cases.md."
        )

    original_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        ok, detail = validate_test_cases_files(None)
    finally:
        os.chdir(original_cwd)

    if not ok:
        raise MissingTestCasesArtifactsError(str(detail))


def _validate_qa_playwright_artifacts(workspace: Path) -> None:
    import os

    from tools.playwright_guardrail import validate_playwright_files

    original_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        ok, detail = validate_playwright_files(None)
    finally:
        os.chdir(original_cwd)

    if not ok:
        raise MissingPlaywrightArtifactsError(str(detail))


@dataclass(frozen=True)
class FlowDefinition:
    id: str
    name: str
    description: str
    crew_file: str
    request_model: type[BaseModel]
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    post_run_validators: list[PostRunValidator] = field(default_factory=list)
    uses_custom_crew: bool = False

    def to_info(self) -> dict[str, Any]:
        schema = self.request_model.model_json_schema()
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "request_schema": schema,
        }


_FLOWS: dict[str, FlowDefinition] = {
    "qa": FlowDefinition(
        id="qa",
        name="QA Test Cases & Playwright",
        description=(
            "Genera casos de prueba y automatizaciones Playwright a partir de una historia de usuario."
        ),
        crew_file="crew.jsonc",
        request_model=CreateQaJobRequest,
        required_fields=["user_story"],
        optional_fields=["base_url", "frontend", "backend", "endpoints"],
        post_run_validators=[
            _validate_qa_test_cases_artifacts,
            _validate_qa_playwright_artifacts,
        ],
    ),
    "sdd": FlowDefinition(
        id="sdd",
        name="Software Design Document (SDD)",
        description=(
            "Genera un SDD a partir de documentos en MinIO (funcional, técnico, tareas) "
            "o ejecuta un crew.jsonc personalizado subido a MinIO."
        ),
        crew_file="crews/sdd.jsonc",
        request_model=CreateSddJobRequest,
        required_fields=["documents | crew_file"],
        optional_fields=[],
        post_run_validators=[],
        uses_custom_crew=True,
    ),
}

DEFAULT_FLOW_ID = "qa"


def get_flow(flow_id: str) -> FlowDefinition:
    normalized = flow_id.strip().lower()
    flow = _FLOWS.get(normalized)
    if not flow:
        available = ", ".join(sorted(_FLOWS))
        raise ValueError(f"Flujo desconocido: '{flow_id}'. Flujos disponibles: {available}")
    return flow


def list_flows() -> list[FlowDefinition]:
    return list(_FLOWS.values())


def parse_flow_agents_from_crew(crew_text: str) -> list[str]:
    match = re.search(r'"agents"\s*:\s*\[(.*?)\]', crew_text, re.DOTALL)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))

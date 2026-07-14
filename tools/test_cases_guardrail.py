"""Filesystem + schema guardrail for the test-cases generation task."""

import json
import re
from pathlib import Path
from typing import Any, Tuple

REQUIRED_FILES = (
    "output/test-cases/test-cases.json",
    "output/test-cases/test-cases.md",
)

REQUIRED_FIELDS = (
    "id",
    "title",
    "priority",
    "type",
    "preconditions",
    "steps",
    "test_data",
    "expected_result",
    "automatable",
    "automation_notes",
)

ALLOWED_PRIORITIES = {"Alta", "Media", "Baja"}
ALLOWED_TYPES = {"positivo", "negativo", "borde", "seguridad", "accesibilidad"}
ID_PATTERN = re.compile(r"^TC-\d{3,}$")


def render_test_cases_md(cases: list) -> str:
    """Build a readable markdown catalog from the structured JSON list."""
    lines = [
        "# Catálogo de Test Cases",
        "",
        f"Total: {len(cases)}",
        "",
    ]
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = case.get("id", "TC-???")
        title = case.get("title", "(sin título)")
        lines.append(f"## {case_id} — {title}")
        lines.append("")
        lines.append(f"- **Prioridad:** {case.get('priority', '')}")
        lines.append(f"- **Tipo:** {case.get('type', '')}")
        lines.append(f"- **Precondiciones:** {case.get('preconditions', '')}")
        lines.append("- **Pasos:**")
        steps = case.get("steps") or []
        if isinstance(steps, list):
            for idx, step in enumerate(steps, start=1):
                lines.append(f"  {idx}. {step}")
        test_data = case.get("test_data") or {}
        lines.append(f"- **Datos de prueba:** `{json.dumps(test_data, ensure_ascii=False)}`")
        lines.append(f"- **Resultado esperado:** {case.get('expected_result', '')}")
        lines.append(
            f"- **Automatizable:** {case.get('automatable', '')} — {case.get('automation_notes', '')}"
        )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def ensure_test_cases_md(root: Path | None = None) -> bool:
    """
    If test-cases.json exists but test-cases.md is missing/too short, synthesize the MD.
    Returns True when md exists afterwards (created or already present).
    """
    root = root or Path.cwd()
    json_path = root / "output" / "test-cases" / "test-cases.json"
    md_path = root / "output" / "test-cases" / "test-cases.md"
    if not json_path.is_file():
        return False

    if md_path.is_file() and len(md_path.read_text(encoding="utf-8").strip()) >= 40:
        return True

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(payload, list) or not payload:
        return False

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_test_cases_md(payload), encoding="utf-8")
    return True


def validate_test_cases_files(result) -> Tuple[bool, Any]:
    """
    Accept the task only if test-cases files exist on disk and JSON matches the
    expected catalog schema (see reference test-cases.json).
    """
    root = Path.cwd()

    # Agents often write JSON and forget MD — derive MD from JSON when possible.
    ensure_test_cases_md(root)

    missing = [rel for rel in REQUIRED_FILES if not (root / rel).is_file()]
    if missing:
        return False, (
            "REJECTED: faltan archivos en disco (una lista narrativa no alcanza). "
            "Usá FileWriterTool para crear: " + ", ".join(missing)
            + ". Obligatorio: escribir PRIMERO output/test-cases/test-cases.json "
            "y DESPUÉS output/test-cases/test-cases.md (mismo contenido en formato legible)."
        )

    json_path = root / "output" / "test-cases" / "test-cases.json"
    try:
        raw = json_path.read_text(encoding="utf-8").strip()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return False, (
            "REJECTED: output/test-cases/test-cases.json no es JSON válido. "
            f"Error: {exc}. Reescribí el archivo como un array JSON."
        )

    if not isinstance(payload, list) or not payload:
        return False, (
            "REJECTED: test-cases.json debe ser un array JSON no vacío de test cases "
            '(formato: [{ "id": "TC-001", ... }, ...]).'
        )

    errors: list[str] = []
    for index, case in enumerate(payload):
        prefix = f"caso[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix}: debe ser un objeto")
            continue

        missing_fields = [field for field in REQUIRED_FIELDS if field not in case]
        if missing_fields:
            errors.append(f"{prefix}: faltan campos {missing_fields}")
            continue

        case_id = case.get("id")
        if not isinstance(case_id, str) or not ID_PATTERN.match(case_id):
            errors.append(f"{prefix}.id: debe ser string TC-XXX (ej. TC-001), got {case_id!r}")

        for text_field in ("title", "preconditions", "expected_result", "automation_notes"):
            value = case.get(text_field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{text_field}: string no vacío requerido")

        priority = case.get("priority")
        if priority not in ALLOWED_PRIORITIES:
            errors.append(
                f"{prefix}.priority: debe ser uno de {sorted(ALLOWED_PRIORITIES)}, got {priority!r}"
            )

        case_type = case.get("type")
        if case_type not in ALLOWED_TYPES:
            errors.append(
                f"{prefix}.type: debe ser uno de {sorted(ALLOWED_TYPES)}, got {case_type!r}"
            )

        steps = case.get("steps")
        if not isinstance(steps, list) or not steps or not all(isinstance(s, str) and s.strip() for s in steps):
            errors.append(f"{prefix}.steps: array no vacío de strings requerido")

        test_data = case.get("test_data")
        if not isinstance(test_data, dict):
            errors.append(f"{prefix}.test_data: objeto JSON requerido (puede ser {{}})")

        automatable = case.get("automatable")
        if not isinstance(automatable, str) or automatable.strip().lower() not in {"sí", "si", "no"}:
            errors.append(f"{prefix}.automatable: debe ser 'sí' o 'no', got {automatable!r}")

    md_path = root / "output" / "test-cases" / "test-cases.md"
    md_text = md_path.read_text(encoding="utf-8").strip()
    if len(md_text) < 40:
        # Last resort: rebuild from JSON again
        if ensure_test_cases_md(root):
            md_text = md_path.read_text(encoding="utf-8").strip()
        if len(md_text) < 40:
            errors.append("test-cases.md está vacío o es demasiado corto")

    if errors:
        shown = errors[:12]
        extra = f" (+{len(errors) - 12} más)" if len(errors) > 12 else ""
        return False, (
            "REJECTED: test-cases.json no cumple el schema esperado "
            "(id, title, priority, type, preconditions, steps, test_data, "
            "expected_result, automatable, automation_notes). Corregí con FileWriterTool. "
            "Problemas: " + "; ".join(shown) + extra
        )

    return True, result

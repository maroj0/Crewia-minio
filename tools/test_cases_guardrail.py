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


def _normalize_test_data(value: Any) -> dict:
    """Coerce common LLM mistakes into a JSON object."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"n/a", "na", "none", "null", "-", "sin datos"}:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"items": parsed}
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"value": text}
    if isinstance(value, list):
        return {"items": value}
    if isinstance(value, (int, float, bool)):
        return {"value": value}
    return {"value": str(value)}


def _normalize_steps(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(step).strip() for step in value if str(step).strip()]
    if isinstance(value, str) and value.strip():
        parts = re.split(r"\n+|(?<=\.)\s+(?=[A-ZÁÉÍÓÚ0-9])", value.strip())
        cleaned = [part.strip(" -•\t") for part in parts if part.strip(" -•\t")]
        return cleaned or [value.strip()]
    return []


def _normalize_automatable(value: Any) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    if value is None:
        return "no"
    text = str(value).strip().lower()
    if text in {"sí", "si", "yes", "true", "1", "y"}:
        return "sí"
    if text in {"no", "false", "0", "n"}:
        return "no"
    return str(value).strip()


def _normalize_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def normalize_test_cases_payload(payload: list) -> tuple[list, bool]:
    """Normalize cases in-place-friendly copy. Returns (cases, changed)."""
    changed = False
    normalized: list = []
    for case in payload:
        if not isinstance(case, dict):
            normalized.append(case)
            continue
        item = dict(case)

        if "test_data" not in item or not isinstance(item.get("test_data"), dict):
            new_data = _normalize_test_data(item.get("test_data"))
            if item.get("test_data") != new_data:
                changed = True
            item["test_data"] = new_data

        steps = _normalize_steps(item.get("steps"))
        if item.get("steps") != steps:
            changed = True
            item["steps"] = steps

        automatable = _normalize_automatable(item.get("automatable"))
        if item.get("automatable") != automatable:
            changed = True
            item["automatable"] = automatable

        for field in ("title", "preconditions", "expected_result", "automation_notes"):
            text = _normalize_text(item.get(field), default="")
            if field == "automation_notes" and not text:
                text = "Sin notas"
                changed = True
            elif item.get(field) != text and isinstance(item.get(field), (type(None), int, float, bool)):
                changed = True
                item[field] = text
            elif item.get(field) != text and isinstance(item.get(field), str) and item.get(field) != text:
                # only trim whitespace changes
                if item.get(field).strip() != item.get(field) if isinstance(item.get(field), str) else True:
                    changed = True
                item[field] = text

        if "id" in item and not isinstance(item["id"], str):
            item["id"] = str(item["id"])
            changed = True

        normalized.append(item)
    return normalized, changed


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
    json_path = root / "output" / "test-cases" / "test-cases.json"
    md_path = root / "output" / "test-cases" / "test-cases.md"

    if json_path.is_file():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(payload, list) and payload:
                normalized, changed = normalize_test_cases_payload(payload)
                if changed:
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                    json_path.write_text(
                        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    # Force MD refresh after heal
                    if md_path.exists():
                        md_path.unlink()
        except (OSError, json.JSONDecodeError):
            pass

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

    md_text = md_path.read_text(encoding="utf-8").strip()
    if len(md_text) < 40:
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

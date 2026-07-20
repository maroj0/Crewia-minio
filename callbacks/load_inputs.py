"""Load input documents (Markdown, plain text, or PDF) into crew kickoff inputs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FILES = {
    "funcional_file": "inputs/documento_funcional.md",
    "tecnico_file": "inputs/documento_tecnico.md",
}

# Preferred order when resolving by stem (Markdown first).
SUPPORTED_EXTENSIONS = (".md", ".txt", ".pdf")


def _read_plain_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _extract_pdf_text(path: Path) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        parts: list[str] = []
        for page in doc:
            parts.append(page.get_text("text"))
        return "\n".join(parts).strip()
    finally:
        doc.close()


def _load_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return _read_plain_text(path)
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    raise ValueError(
        f"Formato no soportado: {path.suffix}. "
        f"Use Markdown (.md), texto plano (.txt) o PDF (.pdf)."
    )


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _resolve_document_path(raw: str | Path) -> Path:
    """Resolve input path, falling back to .md/.txt/.pdf with the same stem."""
    path = _resolve_path(raw)
    if path.exists():
        return path

    stem_path = path.with_suffix("")
    for ext in SUPPORTED_EXTENSIONS:
        candidate = stem_path.with_suffix(ext)
        if candidate.exists():
            logger.info("Resolved missing %s -> %s", path.name, candidate.name)
            return candidate.resolve()

    return path


def before_kickoff(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Load document text and expose it as kickoff inputs for task interpolation."""
    data = dict(inputs or {})

    funcional_path = _resolve_document_path(
        data.get("funcional_file") or DEFAULT_FILES["funcional_file"]
    )
    tecnico_path = _resolve_document_path(
        data.get("tecnico_file") or DEFAULT_FILES["tecnico_file"]
    )

    if not funcional_path.exists():
        raise FileNotFoundError(
            f"Documento funcional no encontrado: {funcional_path} "
            f"(formatos admitidos: {', '.join(SUPPORTED_EXTENSIONS)})"
        )
    if not tecnico_path.exists():
        raise FileNotFoundError(
            f"Documento técnico no encontrado: {tecnico_path} "
            f"(formatos admitidos: {', '.join(SUPPORTED_EXTENSIONS)})"
        )

    funcional_text = _load_document_text(funcional_path)
    tecnico_text = _load_document_text(tecnico_path)

    data["funcional_file"] = str(funcional_path.relative_to(PROJECT_ROOT)).replace(
        "\\", "/"
    )
    data["tecnico_file"] = str(tecnico_path.relative_to(PROJECT_ROOT)).replace(
        "\\", "/"
    )
    data["funcional_text"] = funcional_text
    data["tecnico_text"] = tecnico_text

    logger.info(
        "before_kickoff: loaded funcional=%s (%s chars), tecnico=%s (%s chars)",
        funcional_path.name,
        len(funcional_text),
        tecnico_path.name,
        len(tecnico_text),
    )
    print(
        f"Documentos cargados: funcional={funcional_path.name} ({len(funcional_text)} chars), "
        f"tecnico={tecnico_path.name} ({len(tecnico_text)} chars)"
    )
    return data

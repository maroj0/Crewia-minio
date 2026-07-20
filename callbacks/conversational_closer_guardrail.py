"""Deterministic guardrail: strip chatty trailers (PDF/download offers, questions)."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Trailing paragraphs that look like assistant follow-ups, not SDD content.
_TRAILER_RE = re.compile(
    r"(?:"
    r"¿\s*(?:deseas|quieres|te\s+gustar[ií]a|necesitas|necesit[aá]s|puedo|desea|"
    r"te\s+ayudo|prefieres|prefer[ií]s)\b"
    r"|tambi[eé]n\s+puedo\b"
    r"|puedo\s+(?:ayudarte|generar|convertirlo|incluirlo)\b"
    r"|(?:archivo|archivos)\s+(?:`?\.?md`?)?\s*descargable"
    r"|generar\s+(?:el\s+)?(?:archivo|PDF|Word|DOCX)"
    r"|convertirlo\s+en\s+PDF"
    r"|ofrezco\s+(?:generar|crear|exportar)"
    r")",
    re.IGNORECASE,
)


def _raw(task_output: Any) -> str:
    raw = getattr(task_output, "raw", None)
    if isinstance(raw, str):
        return raw
    return str(task_output) if task_output is not None else ""


def _set_raw(task_output: Any, text: str) -> Any:
    if hasattr(task_output, "raw"):
        try:
            task_output.raw = text
            return task_output
        except Exception:
            pass
    return text


def _strip_trailers(text: str) -> tuple[str, int]:
    """Remove trailing paragraphs that match conversational closer patterns."""
    if not text.strip():
        return text, 0

    parts = re.split(r"(\n{2,})", text.rstrip())
    # parts alternates: content, separator, content, separator, ...
    removed = 0
    while parts:
        # Find last non-separator chunk
        idx = len(parts) - 1
        while idx >= 0 and re.fullmatch(r"\n*", parts[idx] or ""):
            idx -= 1
        if idx < 0:
            break
        chunk = parts[idx].strip()
        if not chunk:
            # Drop empty trailing piece + its separator
            parts = parts[:idx]
            continue
        if _TRAILER_RE.search(chunk):
            parts = parts[:idx]
            removed += 1
            continue
        break

    cleaned = "".join(parts).rstrip()
    if text.endswith("\n") and cleaned:
        cleaned += "\n"
    return cleaned, removed


def strip_conversational_closers(task_output: Any) -> tuple[bool, Any]:
    """Strip PDF/download offers and conversational questions from the end.

    Does not fail the task: chatty footers are removed so the technical body
    can proceed. Empty output after stripping still fails.
    """
    text = _raw(task_output)
    cleaned, removed = _strip_trailers(text)

    if removed:
        task_name = getattr(task_output, "name", None) or "<unnamed>"
        logger.warning(
            "strip_conversational_closers: task=%s removed %s trailing paragraph(s)",
            task_name,
            removed,
        )

    if not cleaned.strip():
        return False, "Salida vacía tras eliminar cierres conversacionales."

    if cleaned == text:
        return True, task_output

    return True, _set_raw(task_output, cleaned)

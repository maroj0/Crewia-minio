"""Deterministic guardrail: Phase 3/4 outputs must include their FILE delimiter."""

from __future__ import annotations

import logging
import re
from typing import Any

from callbacks.sdd_task_files import TASK_OUTPUT_FILES

logger = logging.getLogger(__name__)

# Allow optional markdown noise around the marker (bold, backticks, spaces).
_MARKER_RE = re.compile(
    r"===\s*FILE:\s*(?P<name>[\w.-]+\.md)\s*===",
    re.IGNORECASE,
)


def _raw(task_output: Any) -> str:
    raw = getattr(task_output, "raw", None)
    if isinstance(raw, str):
        return raw
    return str(task_output) if task_output is not None else ""


def _task_name(task_output: Any) -> str | None:
    name = getattr(task_output, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _expected_filename(task_output: Any) -> str | None:
    task_name = _task_name(task_output)
    if task_name and task_name in TASK_OUTPUT_FILES:
        return TASK_OUTPUT_FILES[task_name]
    return None


def _has_expected_marker(text: str, expected: str) -> bool:
    # Inspect the first non-empty lines (skip leading blanks / chat preamble crumbs).
    non_empty: list[str] = []
    for line in text.splitlines():
        if line.strip():
            non_empty.append(line.strip())
        if len(non_empty) >= 8:
            break

    if non_empty:
        head = "\n".join(non_empty)
        for match in _MARKER_RE.finditer(head):
            if match.group("name").strip().lower() == expected:
                return True

    # Also accept if the marker appears anywhere in the first ~1500 chars
    # (models sometimes emit a one-line label before the delimiter).
    for match in _MARKER_RE.finditer(text[:1500]):
        if match.group("name").strip().lower() == expected:
            return True

    return False


def _prepend_delimiter(task_output: Any, expected: str, text: str) -> Any:
    """Normalize output so save_output can strip the audit report cleanly."""
    fixed = f"=== FILE: {expected} ===\n{text.lstrip()}"
    if hasattr(task_output, "raw"):
        try:
            task_output.raw = fixed
            return task_output
        except Exception:
            pass
    return fixed


def require_file_delimiter(task_output: Any) -> tuple[bool, Any]:
    """Ensure === FILE: <mapped>.md === is present for Phase 3/4 tasks.

    If the model omits the marker but produced non-empty content, prepend it
    from the deterministic task→file map instead of failing the whole crew.
    Empty output still fails.
    """
    expected = _expected_filename(task_output)
    if expected is None:
        # Not a mapped Phase 3/4 task — nothing to enforce here.
        return True, task_output

    text = _raw(task_output).lstrip("\ufeff")
    if not text.strip():
        return False, f"Salida vacía: se esperaba === FILE: {expected} ===."

    if _has_expected_marker(text, expected):
        return True, task_output

    task_name = _task_name(task_output) or "<unnamed>"
    logger.warning(
        "require_file_delimiter: task=%s missing marker for %s; auto-prepending",
        task_name,
        expected,
    )
    return True, _prepend_delimiter(task_output, expected, text)

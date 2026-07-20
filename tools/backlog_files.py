"""Parse and persist backlog output files (epics.md, hus.md)."""

from __future__ import annotations

import re
from pathlib import Path

BACKLOG_FILES = frozenset({"epics.md", "hus.md"})

# Matches: === FILE: epics.md === or === epics.md === (case-insensitive)
_FILE_BLOCK_RE = re.compile(
    r"===\s*(?:FILE:\s*)?(?P<name>epics\.md|hus\.md)\s*===\s*\n"
    r"(?P<body>.*?)(?=\n===\s*(?:FILE:\s*)?(?:epics|hus)\.md\s*===|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _output_dir() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def parse_backlog_files(content: str) -> dict[str, str] | None:
    """Extract {filename: body} from text containing === FILE: epics.md === / hus.md === blocks."""
    if not isinstance(content, str) or not content.strip():
        return None
    parsed: dict[str, str] = {}
    for match in _FILE_BLOCK_RE.finditer(content.strip()):
        name = match.group("name").strip().lower()
        body = match.group("body").strip()
        if name in BACKLOG_FILES and body:
            parsed[name] = body
    return parsed or None


def write_backlog_files(files: dict[str, str]) -> str:
    """Write epics.md and/or hus.md to output/. Returns a status message."""
    if not files:
        return "Error: no files to write."
    written: list[str] = []
    output_dir = _output_dir()
    for name, body in files.items():
        key = name.strip().lower()
        if key not in BACKLOG_FILES or not body.strip():
            continue
        (output_dir / key).write_text(body.strip() + "\n", encoding="utf-8")
        written.append(key)
    if not written:
        return "Error: no recognized backlog files could be written."
    return f"Wrote {len(written)} file(s) to output/: {', '.join(sorted(written))}"

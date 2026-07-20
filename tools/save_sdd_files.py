"""Persist SDD markdown documents under output/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

REQUIRED_FILES = (
    "business.md",
    "use-cases.md",
    "rules.md",
    "database.md",
    "api.md",
    "security.md",
    "ui.md",
    "testing.md",
    "deployment.md",
)

# Final deliverables written by Phase 3/4 (includes global traceability).
OUTPUT_FILES = REQUIRED_FILES + ("traceability.md",)

ALLOWED_FILES = frozenset(OUTPUT_FILES)

# === FILE: name.md ===  OR  === name.md ===
FILE_BLOCK_RE = re.compile(
    r"===\s*(?:FILE:\s*)?(?P<name>[\w.-]+\.md)\s*===\s*\n(?P<body>.*?)(?=\n===\s*(?:FILE:\s*)?[\w.-]+\.md\s*===|\Z)",
    re.DOTALL | re.IGNORECASE,
)

# # name.md  OR  ## name.md  as section headers
HEADING_BLOCK_RE = re.compile(
    r"^#{1,3}\s+(?P<name>[\w.-]+\.md)\s*\n(?P<body>.*?)(?=^#{1,3}\s+[\w.-]+\.md\s*$|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)


def _output_dir() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def parse_sdd_files(content: str, *, require_all: bool = False) -> dict[str, str] | None:
    """Parse SDD content into filename -> body.

    Accepts === FILE: name.md ===, === name.md ===, and # name.md headings.
    By default returns whatever files were found (partial OK).
    If require_all is True, returns None unless all REQUIRED_FILES are present.
    Returns None if nothing usable was found.
    """
    if not isinstance(content, str) or not content.strip():
        return None

    parsed: dict[str, str] = {}

    for match in FILE_BLOCK_RE.finditer(content.strip()):
        name = match.group("name").strip().lower()
        body = match.group("body").strip()
        if name in ALLOWED_FILES and body:
            parsed[name] = body

    if len(parsed) < len(OUTPUT_FILES):
        for match in HEADING_BLOCK_RE.finditer(content.strip()):
            name = match.group("name").strip().lower()
            body = match.group("body").strip()
            if name in ALLOWED_FILES and body and name not in parsed:
                parsed[name] = body

    if not parsed:
        return None

    if require_all and any(name not in parsed for name in REQUIRED_FILES):
        return None

    return parsed


def write_single_file(filename: str, content: str) -> str:
    """Write one markdown file under output/. Returns a status message."""
    name = filename.strip().lower()
    if name not in ALLOWED_FILES:
        return f"Error: '{filename}' is not an allowed SDD output file."
    if not isinstance(content, str) or not content.strip():
        return f"Error: content for '{name}' is empty."

    path = _output_dir() / name
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return f"Wrote 1 file(s) to output/: {name}"


def write_files(files: dict[str, str]) -> str:
    """Write a mapping of filename -> body to output/."""
    if not files:
        return "Error: no files to write."

    written: list[str] = []
    skipped: list[str] = []
    for name, body in files.items():
        key = name.strip().lower()
        if key not in ALLOWED_FILES:
            skipped.append(name)
            continue
        if not isinstance(body, str) or not body.strip():
            skipped.append(name)
            continue
        path = _output_dir() / key
        path.write_text(body.strip() + "\n", encoding="utf-8")
        written.append(key)

    if not written:
        return "Error: no recognized SDD files could be written."

    # Stable order for the message
    ordered = [n for n in OUTPUT_FILES if n in written]
    message = (
        "Wrote " + str(len(ordered)) + " file(s) to output/: " + ", ".join(ordered)
    )
    missing = [n for n in OUTPUT_FILES if n not in written]
    if missing:
        message += " | missing: " + ", ".join(missing)
    if skipped:
        message += " | skipped: " + ", ".join(skipped)
    return message


def write_sdd_files(content: str) -> str:
    """Create output/ and write any SDD markdown files found in content."""
    if not isinstance(content, str) or not content.strip():
        return "Error: 'content' must be a non-empty string with FILE blocks."

    parsed = parse_sdd_files(content, require_all=False)
    if not parsed:
        return (
            "Error: no recognized SDD file blocks found. "
            "Use '=== FILE: <name>.md ===' (or '# <name>.md') sections."
        )

    return write_files(parsed)


class SaveSddFilesInput(BaseModel):
    content: str = Field(
        description=(
            "Full reviewed SDD text with blocks delimited by "
            "'=== FILE: <name>.md ===' for each of the documents."
        )
    )


class SaveSddFilesTool(BaseTool):
    name: str = "save_sdd_files"
    description: str = (
        "Creates the output/ directory if needed and writes SDD markdown "
        "files found in a delimited text payload (business.md, use-cases.md, "
        "rules.md, database.md, api.md, security.md, ui.md, testing.md, "
        "deployment.md, traceability.md). Writes whatever files are present."
    )
    args_schema: type[BaseModel] = SaveSddFilesInput

    def _run(self, **kwargs: Any) -> str:
        return write_sdd_files(kwargs.get("content", ""))

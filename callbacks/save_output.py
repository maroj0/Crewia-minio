"""Persist SDD markdown files after tasks and after the crew finishes."""

from __future__ import annotations

import logging
from typing import Any

from callbacks.sdd_task_files import TASK_OUTPUT_FILES
from tools.save_sdd_files import (
    parse_sdd_files,
    write_files,
    write_single_file,
)

logger = logging.getLogger(__name__)

# Re-export for callers that import TASK_OUTPUT_FILES from this module.
__all__ = ["TASK_OUTPUT_FILES", "on_task_complete", "after_kickoff"]


def _task_raw(task_output: Any) -> str:
    raw = getattr(task_output, "raw", None)
    if isinstance(raw, str) and raw.strip():
        return raw
    return str(task_output) if task_output is not None else ""


def _task_name(task_output: Any) -> str | None:
    name = getattr(task_output, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _body_for_mapped_file(content: str, filename: str) -> tuple[str, str]:
    """Prefer delimited body for *filename*; fall back to full raw content.

    Returns (body, source) where source is 'delimiter' or 'raw'.
    """
    parsed = parse_sdd_files(content, require_all=False)
    if parsed and filename in parsed and parsed[filename].strip():
        return parsed[filename], "delimiter"
    return content, "raw"


def _collect_files_from_tasks(tasks_output: list[Any]) -> dict[str, str]:
    """Merge files from all task outputs (delimiter blocks + task-name map)."""
    collected: dict[str, str] = {}

    for task_output in tasks_output:
        content = _task_raw(task_output)
        if not content.strip():
            continue

        parsed = parse_sdd_files(content, require_all=False)
        if parsed:
            collected.update(parsed)

        task_name = _task_name(task_output)
        if task_name and task_name in TASK_OUTPUT_FILES:
            filename = TASK_OUTPUT_FILES[task_name]
            body, _source = _body_for_mapped_file(content, filename)
            if body.strip():
                # Owning Phase 3/4 task always defines its deliverable.
                collected[filename] = body

    return collected


def on_task_complete(task_output: Any) -> Any:
    """Write SDD output for a completed task (delimiter preferred, else task map)."""
    content = _task_raw(task_output)
    task_name = _task_name(task_output)

    # Phase 3/4: always persist the mapped deliverable.
    if task_name and task_name in TASK_OUTPUT_FILES:
        filename = TASK_OUTPUT_FILES[task_name]
        if not content.strip():
            message = (
                f"on_task_complete: task={task_name} skipped "
                f"(empty output for {filename})"
            )
            logger.warning(message)
            print(message)
            return task_output

        body, source = _body_for_mapped_file(content, filename)
        message = write_single_file(filename, body)
        logger.info(
            "on_task_complete: task=%s source=%s -> %s",
            task_name,
            source,
            message,
        )
        print(message)
        return task_output

    # Unmapped tasks: only write when explicit FILE blocks are present.
    parsed = parse_sdd_files(content, require_all=False)
    if parsed:
        message = write_files(parsed)
        logger.info(
            "on_task_complete: task=%s used delimiter blocks -> %s",
            task_name,
            message,
        )
        print(message)
        return task_output

    message = (
        f"on_task_complete: task={task_name or '<unnamed>'} skipped "
        "(no FILE delimiter and no task→file mapping)"
    )
    logger.info(message)
    return task_output


def after_kickoff(result: Any) -> Any:
    """Merge all task outputs and write the full SDD set to output/."""
    tasks_output = list(getattr(result, "tasks_output", None) or [])
    collected = _collect_files_from_tasks(tasks_output)

    # Also parse the crew-level raw if present (may hold a final multi-file blob).
    raw = getattr(result, "raw", None)
    if isinstance(raw, str) and raw.strip():
        parsed = parse_sdd_files(raw, require_all=False)
        if parsed:
            for name, body in parsed.items():
                if name not in collected or not collected[name].strip():
                    collected[name] = body

    if not collected:
        message = (
            "after_kickoff: no task output contained recognized SDD content; "
            "nothing written to output/"
        )
        logger.warning(message)
        print(message)
        return result

    message = write_files(collected)
    if message.startswith("Error:"):
        logger.warning("after_kickoff: %s", message)
        print(message)
    else:
        logger.info("after_kickoff: %s", message)
        print(message)

    return result

"""Persist backlog output files (epics.md, hus.md) después de cada tarea y al finalizar."""

from __future__ import annotations

import logging
from typing import Any

from tools.backlog_files import parse_backlog_files, write_backlog_files

logger = logging.getLogger(__name__)


def _task_raw(task_output: Any) -> str:
    raw = getattr(task_output, "raw", None)
    if isinstance(raw, str) and raw.strip():
        return raw
    return str(task_output) if task_output is not None else ""


def on_task_complete(task_output: Any) -> Any:
    """Escribe epics.md o hus.md si el output de la tarea contiene bloques FILE."""
    content = _task_raw(task_output)
    if not content.strip():
        return task_output
    parsed = parse_backlog_files(content)
    if parsed:
        msg = write_backlog_files(parsed)
        logger.info("on_task_complete backlog: %s", msg)
        print(msg)
    return task_output


def after_kickoff(result: Any) -> Any:
    """Consolida todos los outputs de tareas y escribe los archivos faltantes."""
    tasks_output = list(getattr(result, "tasks_output", None) or [])
    collected: dict[str, str] = {}

    for task_output in tasks_output:
        parsed = parse_backlog_files(_task_raw(task_output))
        if parsed:
            collected.update(parsed)

    raw = getattr(result, "raw", None)
    if isinstance(raw, str) and raw.strip():
        parsed = parse_backlog_files(raw)
        if parsed:
            for name, body in parsed.items():
                if name not in collected or not collected[name].strip():
                    collected[name] = body

    if not collected:
        logger.warning("after_kickoff backlog: ninguna tarea emitió bloques === FILE: ===.")
        return result

    msg = write_backlog_files(collected)
    logger.info("after_kickoff backlog: %s", msg)
    print(msg)
    return result

"""Condiciones para las ConditionalTask del crew backlog-generator.

CrewAI invoca estas funciones con el TaskOutput de la tarea previa y
espera un bool. Acá ignoramos ese output y decidimos por variables de
entorno, que el endpoint setea antes del kickoff. Así el mismo crew
sirve para: solo épicas, solo HUs, o ambas.
"""

import os


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "si", "sí")


def should_run_epics(task_output) -> bool:  # noqa: ARG001 (firma requerida por CrewAI)
    return _flag("GENERATE_EPICS", "true")


def should_run_hus(task_output) -> bool:  # noqa: ARG001
    return _flag("GENERATE_HUS", "false")

"""Load input documents for the backlog crew kickoff (funcional + optional epics).

Diferencias con callbacks.load_inputs (SDD):
- No requiere tecnico_file.
- Valida longitud mínima del funcional (PDF escaneado sin OCR fue un bug real).
- Carga epics_file si se proporcionó (corrida con generate_hus sin generate_epics).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from callbacks.load_inputs import (
    SUPPORTED_EXTENSIONS,
    _load_document_text,
    _resolve_document_path,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIN_FUNCIONAL_CHARS = 200


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def before_kickoff(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Carga funcional_text y epics_text antes del kickoff del crew backlog."""
    data = dict(inputs or {})

    # --- documento funcional (obligatorio) ---
    funcional_raw = data.get("funcional_file") or "input/funcional"
    funcional_path = _resolve_document_path(funcional_raw)

    if not funcional_path.exists():
        raise FileNotFoundError(
            f"Documento funcional no encontrado: {funcional_path} "
            f"(formatos admitidos: {', '.join(SUPPORTED_EXTENSIONS)})"
        )

    funcional_text = _load_document_text(funcional_path)
    if len(funcional_text) < MIN_FUNCIONAL_CHARS:
        raise ValueError(
            f"Documento funcional vacío o ilegible "
            f"(¿PDF escaneado sin OCR?): solo {len(funcional_text)} chars extraídos "
            f"(mínimo {MIN_FUNCIONAL_CHARS})."
        )

    data["funcional_text"] = funcional_text
    data["funcional_file"] = str(funcional_path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    # --- epics previo (opcional) ---
    epics_raw = (data.get("epics_file") or "").strip()
    if epics_raw:
        epics_path = _resolve_path(epics_raw)
        if epics_path.exists():
            data["epics_text"] = epics_path.read_text(encoding="utf-8").strip()
            logger.info("before_kickoff backlog: epics cargado desde %s (%d chars)", epics_path.name, len(data["epics_text"]))
        else:
            logger.warning("epics_file no encontrado: %s — epics_text queda vacío", epics_path)
            data.setdefault("epics_text", "")
    else:
        data.setdefault("epics_text", "")

    logger.info(
        "before_kickoff backlog: funcional=%s (%d chars), epics=%d chars",
        funcional_path.name,
        len(funcional_text),
        len(data.get("epics_text") or ""),
    )
    return data

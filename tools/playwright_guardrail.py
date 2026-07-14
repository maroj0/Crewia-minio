"""Filesystem guardrail for Playwright generation task."""

import json
from pathlib import Path
from typing import Any, Tuple


REQUIRED_FILES = (
    "output/playwright/package.json",
    "output/playwright/playwright.config.ts",
    "output/playwright/README.md",
)


def _load_job_flags(root: Path) -> tuple[bool, bool]:
    config_path = root / "input" / "job_config.json"
    frontend = True
    backend = False
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            frontend = bool(data.get("frontend", True))
            backend = bool(data.get("backend", False))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    if not frontend and not backend:
        frontend = True
    return frontend, backend


def validate_playwright_files(result) -> Tuple[bool, Any]:
    """
    Accept the task only if real Playwright files exist on disk.
    Requirements adapt to frontend/backend flags in input/job_config.json.
    """
    root = Path.cwd()
    frontend, backend = _load_job_flags(root)
    missing = []

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            missing.append(relative)

    fixtures_dir = root / "output" / "playwright" / "fixtures"
    fixtures = [p for p in fixtures_dir.iterdir() if p.is_file()] if fixtures_dir.is_dir() else []
    if not fixtures:
        missing.append("output/playwright/fixtures/*")

    specs_dir = root / "output" / "playwright" / "tests"
    specs = list(specs_dir.rglob("*.spec.ts")) if specs_dir.is_dir() else []
    if not specs:
        missing.append("output/playwright/tests/**/*.spec.ts")

    if frontend:
        pages_dir = root / "output" / "playwright" / "pages"
        pages = list(pages_dir.rglob("*.ts")) if pages_dir.is_dir() else []
        if not pages:
            missing.append("output/playwright/pages/**/*.ts")

    if backend:
        api_specs = list((specs_dir / "api").rglob("*.spec.ts")) if (specs_dir / "api").is_dir() else []
        if not api_specs:
            # Also accept any *api*.spec.ts under tests/
            api_specs = [p for p in specs if "api" in p.as_posix().lower()]
        if not api_specs:
            missing.append("output/playwright/tests/api/**/*.spec.ts")

    if missing:
        feedback = (
            "REJECTED: files are missing on disk (a narrative list is not enough). "
            f"(frontend={frontend}, backend={backend}) "
            "Use Write Project File tool for each missing path: "
            + ", ".join(missing)
        )
        return False, feedback

    return True, result

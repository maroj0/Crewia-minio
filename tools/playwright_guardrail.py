"""Filesystem guardrail for Playwright generation task."""

from pathlib import Path
from typing import Any, Tuple


REQUIRED_FILES = (
    "output/playwright/package.json",
    "output/playwright/playwright.config.ts",
    "output/playwright/README.md",
)


def validate_playwright_files(result) -> Tuple[bool, Any]:
    """
    Accept the task only if real Playwright files exist on disk.
    CrewAI string guardrails only see the narrative and are easily fooled.
    """
    root = Path.cwd()
    missing = []

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            missing.append(relative)

    specs_dir = root / "output" / "playwright" / "tests"
    specs = list(specs_dir.rglob("*.spec.ts")) if specs_dir.is_dir() else []
    if not specs:
        missing.append("output/playwright/tests/**/*.spec.ts")

    pages_dir = root / "output" / "playwright" / "pages"
    pages = list(pages_dir.rglob("*.ts")) if pages_dir.is_dir() else []
    if not pages:
        missing.append("output/playwright/pages/**/*.ts")

    fixtures_dir = root / "output" / "playwright" / "fixtures"
    fixtures = [p for p in fixtures_dir.iterdir() if p.is_file()] if fixtures_dir.is_dir() else []
    if not fixtures:
        missing.append("output/playwright/fixtures/*")

    if missing:
        feedback = (
            "REJECTED: files are missing on disk (a narrative list is not enough). "
            "Use Write Project File tool for each missing path: "
            + ", ".join(missing)
        )
        return False, feedback

    return True, result

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from service.config import Settings, get_settings
from service.job_store import JobStatus, JobStore
from service.minio_client import MinioStorage

REQUIRED_PLAYWRIGHT_FILES = (
    "package.json",
    "playwright.config.ts",
    "README.md",
)


class MissingPlaywrightArtifactsError(Exception):
    """Raised when Playwright suite files are missing after crew kickoff."""


class CrewRunner:
    def __init__(
        self,
        settings: Settings | None = None,
        storage: MinioStorage | None = None,
        job_store: JobStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or MinioStorage()
        self.job_store = job_store or JobStore(self.settings.database_url)
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_jobs)

    def _job_workspace(self, job_id: str) -> Path:
        return self.settings.jobs_workspace_root / job_id

    def _prepare_workspace(self, job_id: str, user_story: str) -> Path:
        workspace = self._job_workspace(job_id)
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        project_root = self.settings.project_root
        for item in ("agents", "knowledge", "tools", "crew.jsonc"):
            source = project_root / item
            target = workspace / item
            if source.is_dir():
                shutil.copytree(source, target)
            elif source.is_file():
                shutil.copy2(source, target)

        input_dir = workspace / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / "historia_usuario.txt").write_text(user_story, encoding="utf-8")
        (workspace / "output").mkdir(parents=True, exist_ok=True)
        return workspace

    def _run_crew_sync(self, workspace: Path) -> str:
        load_dotenv(self.settings.project_root / ".env", override=True)

        ollama_base = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("API_BASE") or "http://100.126.36.101:11434"
        os.environ["OLLAMA_BASE_URL"] = ollama_base
        os.environ["API_BASE"] = ollama_base
        os.environ.setdefault("OPENAI_API_KEY", "ollama")
        os.environ.setdefault("MODEL", "ollama/qwen2.5-coder:3b")

        if self.settings.google_api_key:
            os.environ["GOOGLE_API_KEY"] = self.settings.google_api_key
        if self.settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.settings.gemini_api_key

        from crewai.project.crew_loader import load_crew

        previous_cwd = Path.cwd()
        previous_sys_path = list(sys.path)
        os.chdir(workspace)
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        try:
            crew, default_inputs = load_crew(workspace / "crew.jsonc")
            inputs = {**default_inputs, "hus": "input/historia_usuario.txt"}
            result = crew.kickoff(inputs=inputs)
            return str(result)
        finally:
            os.chdir(previous_cwd)
            sys.path[:] = previous_sys_path

    def _validate_playwright_artifacts(self, workspace: Path) -> None:
        root = workspace / "output" / "playwright"
        missing: list[str] = []

        if not root.is_dir():
            raise MissingPlaywrightArtifactsError(
                "Missing Playwright suite: output/playwright/ directory was not created. "
                "generation-summary.md alone does not count as generated files."
            )

        for relative in REQUIRED_PLAYWRIGHT_FILES:
            if not (root / relative).is_file():
                missing.append(f"output/playwright/{relative}")

        specs_dir = root / "tests"
        specs = list(specs_dir.rglob("*.spec.ts")) if specs_dir.is_dir() else []
        if not specs:
            missing.append("output/playwright/tests/**/*.spec.ts (at least one)")

        pages_dir = root / "pages"
        pages = list(pages_dir.rglob("*.ts")) if pages_dir.is_dir() else []
        if not pages:
            missing.append("output/playwright/pages/**/*.ts (at least one Page Object)")

        fixtures_dir = root / "fixtures"
        fixtures = [path for path in fixtures_dir.iterdir() if path.is_file()] if fixtures_dir.is_dir() else []
        if not fixtures:
            missing.append("output/playwright/fixtures/* (e.g. test-data.ts)")

        if missing:
            raise MissingPlaywrightArtifactsError(
                "Playwright artifacts incomplete after crew run. Missing: "
                + "; ".join(missing)
                + ". The final narrative/summary is not enough — files must be written with FileWriterTool."
            )

    def _upload_job_artifacts(self, job_id: str, workspace: Path) -> list[dict]:
        prefix = self.storage.job_prefix(job_id)
        input_file = workspace / "input" / "historia_usuario.txt"
        if input_file.exists():
            self.storage.upload_file(f"{prefix}/input/historia_usuario.txt", input_file)

        output_dir = workspace / "output"
        self.storage.upload_directory(f"{prefix}/output", output_dir)
        return self.storage.list_objects(prefix)

    async def run_job(self, job_id: str, user_story: str) -> None:
        async with self._semaphore:
            await self.job_store.update_job(job_id, status=JobStatus.RUNNING)
            workspace = self._job_workspace(job_id)
            try:
                workspace = await asyncio.to_thread(self._prepare_workspace, job_id, user_story)
                result_summary = await asyncio.to_thread(self._run_crew_sync, workspace)
                try:
                    await asyncio.to_thread(self._validate_playwright_artifacts, workspace)
                except MissingPlaywrightArtifactsError as validation_error:
                    artifacts = await asyncio.to_thread(self._upload_job_artifacts, job_id, workspace)
                    await self.job_store.update_job(
                        job_id,
                        status=JobStatus.FAILED,
                        error=str(validation_error),
                        result_summary=result_summary,
                        artifacts=artifacts,
                    )
                    return

                artifacts = await asyncio.to_thread(self._upload_job_artifacts, job_id, workspace)
                await self.job_store.update_job(
                    job_id,
                    status=JobStatus.COMPLETED,
                    result_summary=result_summary,
                    artifacts=artifacts,
                )
            except Exception as exc:
                await self.job_store.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=str(exc),
                )
            finally:
                if workspace.exists():
                    shutil.rmtree(workspace, ignore_errors=True)

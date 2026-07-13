from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

from service.config import Settings, get_settings
from service.job_store import JobStatus, JobStore
from service.minio_client import MinioStorage


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
        for item in ("agents", "knowledge", "crew.jsonc"):
            source = project_root / item
            target = workspace / item
            if source.is_dir():
                shutil.copytree(source, target)
            elif source.is_file():
                if item == "crew.jsonc":
                    target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        input_dir = workspace / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / "historia_usuario.txt").write_text(user_story, encoding="utf-8")
        (workspace / "output").mkdir(parents=True, exist_ok=True)
        return workspace

    def _run_crew_sync(self, workspace: Path) -> str:
        load_dotenv(self.settings.project_root / ".env", override=True)

        if self.settings.google_api_key:
            os.environ["GOOGLE_API_KEY"] = self.settings.google_api_key
        if self.settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.settings.gemini_api_key

        from crewai.project.crew_loader import load_crew

        previous_cwd = Path.cwd()
        os.chdir(workspace)
        try:
            crew, default_inputs = load_crew(workspace / "crew.jsonc")
            inputs = {**default_inputs, "hus": "input/historia_usuario.txt"}
            result = crew.kickoff(inputs=inputs)
            return str(result)
        finally:
            os.chdir(previous_cwd)

    def _upload_job_artifacts(self, job_id: str, workspace: Path) -> list[dict]:
        prefix = self.storage.job_prefix(job_id)
        input_file = workspace / "input" / "historia_usuario.txt"
        if input_file.exists():
            self.storage.upload_file(f"{prefix}/input/historia_usuario.txt", input_file)

        output_dir = workspace / "output"
        uploaded = self.storage.upload_directory(f"{prefix}/output", output_dir)
        return self.storage.list_objects(prefix)

    async def run_job(self, job_id: str, user_story: str) -> None:
        async with self._semaphore:
            await self.job_store.update_job(job_id, status=JobStatus.RUNNING)
            workspace = self._job_workspace(job_id)
            try:
                workspace = await asyncio.to_thread(self._prepare_workspace, job_id, user_story)
                result_summary = await asyncio.to_thread(self._run_crew_sync, workspace)
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

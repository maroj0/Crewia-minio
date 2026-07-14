from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from service.config import Settings, get_settings
from service.job_store import JobStatus, JobStore
from service.minio_client import MinioStorage

WRITE_TOOL_NAMES = {
    "write_project_file",
    "Write Project File",
    "write project file",
}


class MissingPlaywrightArtifactsError(Exception):
    """Raised when Playwright suite files are missing after crew kickoff."""


class MissingTestCasesArtifactsError(Exception):
    """Raised when test-cases catalog files are missing or invalid after crew kickoff."""


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

    def _prepare_workspace(
        self,
        job_id: str,
        user_story: str,
        *,
        base_url: str | None = None,
        frontend: bool = True,
        backend: bool = False,
        endpoints: list[dict] | None = None,
    ) -> Path:
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

        resolved_base = (base_url or "").strip() or "http://localhost:3000"
        job_config = {
            "base_url": base_url,
            "frontend": frontend,
            "backend": backend,
            "base_url_or_default": resolved_base,
            "endpoints_count": len(endpoints or []),
        }
        (input_dir / "job_config.json").write_text(
            json.dumps(job_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if endpoints:
            (input_dir / "endpoints.json").write_text(
                json.dumps(endpoints, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        (workspace / "output").mkdir(parents=True, exist_ok=True)
        return workspace

    def _run_crew_sync(
        self,
        workspace: Path,
        *,
        base_url: str | None = None,
        frontend: bool = True,
        backend: bool = False,
        endpoints: list[dict] | None = None,
    ) -> str:
        load_dotenv(self.settings.project_root / ".env", override=True)

        if self.settings.google_api_key:
            os.environ["GOOGLE_API_KEY"] = self.settings.google_api_key
        if self.settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.settings.gemini_api_key

        resolved_base = (base_url or "").strip() or "http://localhost:3000"
        if base_url:
            os.environ["BASE_URL"] = resolved_base

        from crewai.project.crew_loader import load_crew

        previous_cwd = Path.cwd()
        previous_sys_path = list(sys.path)
        os.chdir(workspace)
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        try:
            crew, default_inputs = load_crew(workspace / "crew.jsonc")
            inputs = {
                **default_inputs,
                "hus": "input/historia_usuario.txt",
                "base_url": base_url or "",
                "frontend": "true" if frontend else "false",
                "backend": "true" if backend else "false",
                "base_url_or_default": resolved_base,
                "endpoints_file": "input/endpoints.json" if endpoints else "",
                "endpoints_count": str(len(endpoints or [])),
            }
            result = crew.kickoff(inputs=inputs)
            return str(result)
        finally:
            os.chdir(previous_cwd)
            sys.path[:] = previous_sys_path

    def _normalize_playwright_path(self, path: str) -> str:
        cleaned = path.replace("\\", "/").lstrip("./")
        if cleaned.startswith("output/playwright/"):
            return cleaned
        return f"output/playwright/{cleaned}"

    def _extract_write_calls(self, text: str) -> list[dict]:
        """Parse tool-call JSON that small models dump into the Final Answer instead of invoking tools."""
        calls: list[dict] = []
        if not text:
            return calls

        # Try full JSON array / object first
        candidates: list[str] = []
        fence = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
        candidates.extend(fence)
        candidates.append(text)

        for blob in candidates:
            blob = blob.strip()
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                calls.extend(self._collect_write_dicts([parsed]))
            elif isinstance(parsed, list):
                calls.extend(self._collect_write_dicts(parsed))

        # Fallback: find individual write_project_file objects with regex-assisted braces
        for match in re.finditer(
            r'\{\s*"name"\s*:\s*"(?:write_project_file|Write Project File)"\s*,\s*"arguments"\s*:\s*\{',
            text,
        ):
            start = match.start()
            obj = self._extract_balanced_json(text, start)
            if not obj:
                continue
            try:
                parsed = json.loads(obj)
            except json.JSONDecodeError:
                continue
            calls.extend(self._collect_write_dicts([parsed]))

        return calls

    def _extract_balanced_json(self, text: str, start: int) -> str | None:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return None

    def _collect_write_dicts(self, items: list) -> list[dict]:
        found: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            args = item.get("arguments") or item.get("args") or {}
            if name in WRITE_TOOL_NAMES and isinstance(args, dict):
                path = args.get("path")
                content = args.get("content")
                if isinstance(path, str) and isinstance(content, str):
                    found.append({"path": path, "content": content})
            # Nested OpenAI-style: {"type":"function","function":{"name":...,"arguments":...}}
            function = item.get("function")
            if isinstance(function, dict):
                found.extend(self._collect_write_dicts([{"name": function.get("name"), "arguments": function.get("arguments")}]))
        return found

    def _materialize_writes_from_text(self, workspace: Path, text: str) -> list[str]:
        written: list[str] = []
        for call in self._extract_write_calls(text):
            relative = self._normalize_playwright_path(call["path"])
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            content = call["content"]
            # Models sometimes wrap content in extra backticks
            if content.startswith("`") and content.endswith("`") and len(content) >= 2:
                content = content[1:-1]
            target.write_text(content, encoding="utf-8")
            written.append(relative)
        return written

    def _validate_test_cases_artifacts(self, workspace: Path) -> None:
        from tools.test_cases_guardrail import ensure_test_cases_md, validate_test_cases_files

        ensure_test_cases_md(workspace)

        json_path = workspace / "output" / "test-cases" / "test-cases.json"
        md_path = workspace / "output" / "test-cases" / "test-cases.md"
        if not json_path.is_file() or not md_path.is_file():
            raise MissingTestCasesArtifactsError(
                "Missing test-cases artifacts: required output/test-cases/test-cases.json "
                "and output/test-cases/test-cases.md."
            )

        original_cwd = Path.cwd()
        try:
            os.chdir(workspace)
            ok, detail = validate_test_cases_files(None)
        finally:
            os.chdir(original_cwd)

        if not ok:
            raise MissingTestCasesArtifactsError(str(detail))

    def _validate_playwright_artifacts(self, workspace: Path) -> None:
        from tools.playwright_guardrail import validate_playwright_files

        original_cwd = Path.cwd()
        try:
            os.chdir(workspace)
            ok, detail = validate_playwright_files(None)
        finally:
            os.chdir(original_cwd)

        if not ok:
            raise MissingPlaywrightArtifactsError(str(detail))

    def _upload_job_artifacts(self, job_id: str, workspace: Path) -> list[dict]:
        prefix = self.storage.job_prefix(job_id)
        input_dir = workspace / "input"
        if input_dir.is_dir():
            for path in input_dir.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(workspace).as_posix()
                    self.storage.upload_file(f"{prefix}/{relative}", path)

        output_dir = workspace / "output"
        self.storage.upload_directory(f"{prefix}/output", output_dir)
        return self.storage.list_objects(prefix)

    async def run_job(self, job_id: str, user_story: str) -> None:
        async with self._semaphore:
            await self.job_store.update_job(job_id, status=JobStatus.RUNNING)
            workspace = self._job_workspace(job_id)
            record = await self.job_store.get_job(job_id)
            base_url = record.base_url if record else None
            frontend = record.frontend if record else True
            backend = record.backend if record else False
            endpoints = record.endpoints if record else None
            try:
                workspace = await asyncio.to_thread(
                    self._prepare_workspace,
                    job_id,
                    user_story,
                    base_url=base_url,
                    frontend=frontend,
                    backend=backend,
                    endpoints=endpoints,
                )
                result_summary = await asyncio.to_thread(
                    self._run_crew_sync,
                    workspace,
                    base_url=base_url,
                    frontend=frontend,
                    backend=backend,
                    endpoints=endpoints,
                )

                # Small models often dump tool calls as JSON text instead of invoking tools.
                await asyncio.to_thread(self._materialize_writes_from_text, workspace, result_summary)
                summary_file = workspace / "output" / "playwright" / "generation-summary.md"
                if summary_file.exists():
                    await asyncio.to_thread(
                        self._materialize_writes_from_text,
                        workspace,
                        summary_file.read_text(encoding="utf-8"),
                    )

                try:
                    await asyncio.to_thread(self._validate_test_cases_artifacts, workspace)
                    await asyncio.to_thread(self._validate_playwright_artifacts, workspace)
                except (MissingTestCasesArtifactsError, MissingPlaywrightArtifactsError) as validation_error:
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
                # If the crew crashed after dumping tool-call JSON into the summary, still try to salvage files.
                try:
                    summary_file = workspace / "output" / "playwright" / "generation-summary.md"
                    if summary_file.exists():
                        await asyncio.to_thread(
                            self._materialize_writes_from_text,
                            workspace,
                            summary_file.read_text(encoding="utf-8"),
                        )
                    await asyncio.to_thread(self._validate_test_cases_artifacts, workspace)
                    await asyncio.to_thread(self._validate_playwright_artifacts, workspace)
                    artifacts = await asyncio.to_thread(self._upload_job_artifacts, job_id, workspace)
                    await self.job_store.update_job(
                        job_id,
                        status=JobStatus.COMPLETED,
                        result_summary=str(exc),
                        artifacts=artifacts,
                        error=None,
                    )
                    return
                except Exception:
                    pass

                artifacts: list[dict] = []
                try:
                    if workspace.exists():
                        artifacts = await asyncio.to_thread(self._upload_job_artifacts, job_id, workspace)
                except Exception:
                    artifacts = []

                await self.job_store.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=str(exc),
                    artifacts=artifacts,
                )
            finally:
                if workspace.exists():
                    shutil.rmtree(workspace, ignore_errors=True)

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv

from service.config import Settings, get_settings
from service.flow_registry import (
    MissingBacklogArtifactsError,
    MissingPlaywrightArtifactsError,
    MissingTestCasesArtifactsError,
    get_flow,
    parse_flow_agents_from_crew,
)
from service.job_store import JobRecord, JobStatus, JobStore
from service.minio_client import MinioStorage

WRITE_TOOL_NAMES = {
    "write_project_file",
    "Write Project File",
    "write project file",
}


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

    def _copy_project_assets(self, workspace: Path) -> None:
        project_root = self.settings.project_root
        for item in ("agents", "callbacks", "conditions", "knowledge", "tools"):
            source = project_root / item
            target = workspace / item
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            elif source.is_file():
                shutil.copy2(source, target)

    def _install_bundled_crew(self, workspace: Path, crew_file: str) -> None:
        crew_source = self.settings.project_root / crew_file
        if not crew_source.is_file():
            raise FileNotFoundError(f"Crew file not found: {crew_source}")
        shutil.copy2(crew_source, workspace / "crew.jsonc")

    def _install_crew_from_minio(self, workspace: Path, crew_ref: str) -> None:
        crew_path = workspace / "crew.jsonc"
        self.storage.download_object(crew_ref, crew_path)
        crew_text = crew_path.read_text(encoding="utf-8")
        _, crew_key = self.storage.parse_object_ref(crew_ref)
        crew_prefix = PurePosixPath(crew_key).parent.as_posix()
        agents_dir = workspace / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        for agent_name in parse_flow_agents_from_crew(crew_text):
            bundled = self.settings.project_root / "agents" / f"{agent_name}.jsonc"
            if bundled.is_file() and not (agents_dir / f"{agent_name}.jsonc").exists():
                shutil.copy2(bundled, agents_dir / f"{agent_name}.jsonc")

            if crew_prefix and crew_prefix != ".":
                remote_agent_key = f"{crew_prefix}/agents/{agent_name}.jsonc"
                destination = agents_dir / f"{agent_name}.jsonc"
                if self.storage.try_download_object(remote_agent_key, destination):
                    continue

            if not (agents_dir / f"{agent_name}.jsonc").exists():
                raise FileNotFoundError(
                    f"Agente '{agent_name}' no encontrado en MinIO ni en agents/ del proyecto."
                )

    def _download_sdd_documents(self, workspace: Path, flow_inputs: dict) -> dict[str, str]:
        documents = flow_inputs.get("documents") or {}
        mapping = {
            "functional_document": "input/functional_document",
            "technical_document": "input/technical_document",
            "tasks": "input/tasks",
        }
        local_paths: dict[str, str] = {}
        input_dir = workspace / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        for field, local_base in mapping.items():
            ref_payload = documents.get(field) or {}
            ref = ref_payload.get("ref") if isinstance(ref_payload, dict) else ref_payload
            if not ref:
                raise ValueError(f"Falta referencia MinIO para documents.{field}")
            filename = self.storage.local_name_from_ref(str(ref), field)
            destination = input_dir / filename
            self.storage.download_object(str(ref), destination)
            local_paths[field] = f"input/{filename}"
        return local_paths

    def _prepare_workspace(self, record: JobRecord) -> Path:
        workspace = self._job_workspace(record.job_id)
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        flow = record.flow
        flow_def = get_flow(flow)
        flow_inputs = record.flow_inputs or {}
        self._copy_project_assets(workspace)

        input_dir = workspace / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        job_config: dict = {"flow": flow, "flow_inputs": flow_inputs}

        if flow == "qa":
            self._install_bundled_crew(workspace, flow_def.crew_file)
            user_story = flow_inputs.get("user_story") or record.user_story
            (input_dir / "historia_usuario.txt").write_text(user_story, encoding="utf-8")

            base_url = flow_inputs.get("base_url")
            frontend = bool(flow_inputs.get("frontend", True))
            backend = bool(flow_inputs.get("backend", False))
            endpoints = flow_inputs.get("endpoints")

            resolved_base = (base_url or "").strip() or "http://localhost:3000"
            job_config.update(
                {
                    "base_url": base_url,
                    "frontend": frontend,
                    "backend": backend,
                    "base_url_or_default": resolved_base,
                    "endpoints_count": len(endpoints or []),
                }
            )
            if endpoints:
                (input_dir / "endpoints.json").write_text(
                    json.dumps(endpoints, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        elif flow == "sdd":
            crew_payload = flow_inputs.get("crew_file") or {}
            crew_ref = crew_payload.get("ref") if isinstance(crew_payload, dict) else crew_payload
            if crew_ref:
                self._install_crew_from_minio(workspace, str(crew_ref))
            else:
                self._install_bundled_crew(workspace, flow_def.crew_file)
                local_paths = self._download_sdd_documents(workspace, flow_inputs)
                job_config["sdd_local_paths"] = local_paths
        elif flow == "backlog":
            self._install_bundled_crew(workspace, flow_def.crew_file)
            funcional_ref = flow_inputs.get("funcional_minio_path", "")
            if funcional_ref:
                funcional_filename = self.storage.local_name_from_ref(funcional_ref, "funcional")
                self.storage.download_object(funcional_ref, input_dir / funcional_filename)
                job_config["funcional_file"] = f"input/{funcional_filename}"

            epics_ref = (flow_inputs.get("epics_minio_path") or "").strip()
            if epics_ref:
                epics_filename = self.storage.local_name_from_ref(epics_ref, "epics.md")
                self.storage.download_object(epics_ref, input_dir / epics_filename)
                job_config["epics_file"] = f"input/{epics_filename}"
            else:
                job_config["epics_file"] = ""
        else:
            self._install_bundled_crew(workspace, flow_def.crew_file)

        (input_dir / "job_config.json").write_text(
            json.dumps(job_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (workspace / "output").mkdir(parents=True, exist_ok=True)
        return workspace

    def _build_crew_inputs(self, record: JobRecord, workspace: Path) -> dict[str, str]:
        flow = record.flow
        flow_inputs = record.flow_inputs or {}

        if flow == "qa":
            base_url = flow_inputs.get("base_url")
            frontend = bool(flow_inputs.get("frontend", True))
            backend = bool(flow_inputs.get("backend", False))
            endpoints = flow_inputs.get("endpoints")
            resolved_base = (base_url or "").strip() or "http://localhost:3000"
            return {
                "hus": "input/historia_usuario.txt",
                "base_url": base_url or "",
                "frontend": "true" if frontend else "false",
                "backend": "true" if backend else "false",
                "base_url_or_default": resolved_base,
                "endpoints_file": "input/endpoints.json" if endpoints else "",
                "endpoints_count": str(len(endpoints or [])),
            }

        if flow == "sdd":
            flow_inputs = record.flow_inputs or {}
            if flow_inputs.get("crew_file"):
                return {}

            job_config_path = workspace / "input" / "job_config.json"
            job_config = json.loads(job_config_path.read_text(encoding="utf-8"))
            local_paths = job_config.get("sdd_local_paths") or {}
            return {
                "funcional_file": local_paths.get("functional_document", "input/functional_document"),
                "tecnico_file": local_paths.get("technical_document", "input/technical_document"),
                "tasks_file": local_paths.get("tasks", "input/tasks"),
            }

        if flow == "backlog":
            job_config_path = workspace / "input" / "job_config.json"
            job_config = json.loads(job_config_path.read_text(encoding="utf-8"))
            generate_epics = flow_inputs.get("generate_epics", True)
            generate_hus = flow_inputs.get("generate_hus", False)
            return {
                "funcional_file": job_config.get("funcional_file", ""),
                "epics_file": job_config.get("epics_file", ""),
                "epicas_seleccionadas": flow_inputs.get("epicas_seleccionadas", "TODAS"),
                "sistema": flow_inputs.get("sistema", "el sistema descrito en el documento funcional"),
                "generar_epicas": "true" if generate_epics else "false",
                "generar_hus": "true" if generate_hus else "false",
                # filled by before_kickoff callback — placeholders so kickoff inputs are complete
                "funcional_text": "",
                "epics_text": "",
            }

        return {}

    def _run_crew_sync(self, record: JobRecord, workspace: Path) -> str:
        load_dotenv(self.settings.project_root / ".env", override=True)

        if self.settings.google_api_key:
            os.environ["GOOGLE_API_KEY"] = self.settings.google_api_key
        if self.settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.settings.gemini_api_key

        flow_inputs = record.flow_inputs or {}
        if record.flow == "qa":
            base_url = flow_inputs.get("base_url")
            resolved_base = (base_url or "").strip() or "http://localhost:3000"
            if base_url:
                os.environ["BASE_URL"] = resolved_base

        if record.flow == "backlog":
            # ConditionalTask conditions (conditions/flags.py) read these env vars.
            # Safe under the existing semaphore (max_concurrent_jobs=1 default).
            os.environ["GENERATE_EPICS"] = "true" if flow_inputs.get("generate_epics", True) else "false"
            os.environ["GENERATE_HUS"] = "true" if flow_inputs.get("generate_hus", False) else "false"

        from crewai.project.crew_loader import load_crew

        previous_cwd = Path.cwd()
        previous_sys_path = list(sys.path)
        os.chdir(workspace)
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        try:
            crew, default_inputs = load_crew(workspace / "crew.jsonc")
            inputs = {**default_inputs, **self._build_crew_inputs(record, workspace)}
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
        calls: list[dict] = []
        if not text:
            return calls

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
            function = item.get("function")
            if isinstance(function, dict):
                found.extend(
                    self._collect_write_dicts(
                        [{"name": function.get("name"), "arguments": function.get("arguments")}]
                    )
                )
        return found

    def _materialize_writes_from_text(self, workspace: Path, text: str) -> list[str]:
        written: list[str] = []
        for call in self._extract_write_calls(text):
            relative = self._normalize_playwright_path(call["path"])
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            content = call["content"]
            if content.startswith("`") and content.endswith("`") and len(content) >= 2:
                content = content[1:-1]
            target.write_text(content, encoding="utf-8")
            written.append(relative)
        return written

    def _run_post_validators(self, flow_id: str, workspace: Path) -> None:
        flow_def = get_flow(flow_id)
        for validator in flow_def.post_run_validators:
            validator(workspace)

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

    async def run_job(self, job_id: str) -> None:
        async with self._semaphore:
            await self.job_store.update_job(job_id, status=JobStatus.RUNNING)
            workspace = self._job_workspace(job_id)
            record = await self.job_store.get_job(job_id)
            if not record:
                return

            flow = record.flow
            try:
                workspace = await asyncio.to_thread(self._prepare_workspace, record)
                result_summary = await asyncio.to_thread(self._run_crew_sync, record, workspace)

                if flow == "qa":
                    await asyncio.to_thread(self._materialize_writes_from_text, workspace, result_summary)
                    summary_file = workspace / "output" / "playwright" / "generation-summary.md"
                    if summary_file.exists():
                        await asyncio.to_thread(
                            self._materialize_writes_from_text,
                            workspace,
                            summary_file.read_text(encoding="utf-8"),
                        )

                try:
                    await asyncio.to_thread(self._run_post_validators, flow, workspace)
                except (MissingTestCasesArtifactsError, MissingPlaywrightArtifactsError, MissingBacklogArtifactsError) as validation_error:
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
                if flow == "qa":
                    try:
                        summary_file = workspace / "output" / "playwright" / "generation-summary.md"
                        if summary_file.exists():
                            await asyncio.to_thread(
                                self._materialize_writes_from_text,
                                workspace,
                                summary_file.read_text(encoding="utf-8"),
                            )
                        await asyncio.to_thread(self._run_post_validators, flow, workspace)
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

from pathlib import Path

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class WriteProjectFileInput(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Relative path from the project root where the file must be written. "
            "Example: output/playwright/tests/auth.spec.ts"
        ),
    )
    content: str = Field(..., description="Full file content to write.")


class WriteProjectFileTool(BaseTool):
    name: str = "Write Project File"
    description: str = (
        "Write a complete file to disk at a relative project path. "
        "Use this for every Playwright file (package.json, configs, pages, specs, fixtures, README). "
        "The final chat answer does NOT create files — only this tool does."
    )
    args_schema: type[BaseModel] = WriteProjectFileInput

    def _run(self, path: str, content: str) -> str:
        raw = Path(path)
        if raw.is_absolute():
            return f"Error: path must be relative, got absolute path '{path}'"

        cwd = Path.cwd().resolve()
        target = (cwd / raw).resolve()
        try:
            target.relative_to(cwd)
        except ValueError:
            return f"Error: path '{path}' escapes the project workspace"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        size = target.stat().st_size
        return f"Successfully wrote {size} bytes to {path}"

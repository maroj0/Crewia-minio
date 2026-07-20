"""Phase 3/4 task name → deliverable filename (shared by guardrail + save_output)."""

from __future__ import annotations

# Deterministic map: no LLM delimiter required to know which file a task owns.
TASK_OUTPUT_FILES: dict[str, str] = {
    "auditar_business_task": "business.md",
    "auditar_use_cases_task": "use-cases.md",
    "auditar_rules_task": "rules.md",
    "auditar_database_task": "database.md",
    "auditar_api_task": "api.md",
    "auditar_security_task": "security.md",
    "auditar_ui_task": "ui.md",
    "auditar_testing_task": "testing.md",
    "auditar_deployment_task": "deployment.md",
    "trazabilidad_global_task": "traceability.md",
}

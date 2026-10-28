"""The unified task contract shared by every Omniweb caller."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskType = Literal[
    "requirement_analysis",
    "architecture_design",
    "application_scaffolding",
    "frontend_generation",
    "backend_generation",
    "database_generation",
    "mobile_generation",
    "incremental_code_edit",
    "debugging",
    "test_generation",
    "security_review",
    "deployment_preparation",
    "documentation",
    "content_generation",
]
TASK_TYPES: tuple[str, ...] = TaskType.__args__  # type: ignore[attr-defined]

Complexity = Literal["trivial", "simple", "normal", "complex"]
COMPLEXITIES: tuple[str, ...] = ("trivial", "simple", "normal", "complex")
RiskLevel = Literal["low", "medium", "high", "critical"]
RISKS: tuple[str, ...] = ("low", "medium", "high", "critical")
Strategy = Literal["deterministic", "gpt_oss", "hosted_model", "codex", "human_approval"]

# Actions a task may need. Sensitive ones always require a human approval enforced here,
# regardless of which strategy the planner picks.
SENSITIVE_ACTIONS = {
    "cloud_resource_change",
    "production_credential_change",
    "production_deploy",
    "billing_logic_change",
    "destructive_database_change",
}
KNOWN_ACTIONS = SENSITIVE_ACTIONS | {"read_artifacts", "write_files", "autonomous_code_execution", "run_validation", "network_access"}

# Fields that only server policy may set. A request that tries to supply them is rejected.
SERVER_ONLY_FIELDS = {"tenant_id", "risk_level", "approval_requirements", "authorization", "role", "platform_admin", "user_id"}


class ArtifactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=400)
    content: str | None = Field(default=None, max_length=2_000_000)
    artifact_id: uuid.UUID | None = None  # reference to a previously stored artifact


class DeterministicOption(BaseModel):
    """A deterministic handler the caller can run, such as a template renderer."""

    model_config = ConfigDict(extra="forbid")
    tool: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    coverage: Literal["exact", "approximate"] = "approximate"
    description: str = Field(default="", max_length=300)


class Prompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str = Field(default="", max_length=60_000)
    user: str = Field(default="", max_length=400_000)
    response_format: Literal["text", "json"] = "text"
    json_schema: dict | None = None
    max_output_tokens: int | None = Field(default=None, ge=16, le=64_000)


class ExecutionEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["none", "builder_sandbox", "aaee_workspace", "cde_workspace", "authorized_test_environment"] = "none"
    workspace_id: str | None = Field(default=None, max_length=64)
    target_url: str | None = Field(default=None, max_length=300)


class TaskRequest(BaseModel):
    """What callers may send. Tenant, user, role, and risk come from the token and policy."""

    model_config = ConfigDict(extra="forbid")
    task_type: TaskType
    task_description: str = Field(min_length=1, max_length=20_000)
    project_id: uuid.UUID | None = None
    workspace_id: str | None = Field(default=None, max_length=64)
    parent_task_id: uuid.UUID | None = None
    input_artifacts: list[ArtifactInput] = Field(default_factory=list, max_length=400)
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)
    complexity: Complexity | None = None  # a hint; the classifier may raise it, never lower it
    quality_threshold: float | None = Field(default=None, ge=0, le=1)
    latency_target_ms: int | None = Field(default=None, ge=100, le=3_600_000)
    maximum_budget_usd: float | None = Field(default=None, gt=0, le=1_000)
    maximum_attempts: int | None = Field(default=None, ge=1, le=6)
    allowed_models: list[str] = Field(default_factory=list, max_length=50)  # "provider/model_id"
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    permitted_actions: list[str] = Field(default_factory=list, max_length=20)
    allowed_paths: list[str] = Field(default_factory=list, max_length=50)  # path prefixes output may touch
    execution_environment: ExecutionEnvironment = Field(default_factory=ExecutionEnvironment)
    deterministic_options: list[DeterministicOption] = Field(default_factory=list, max_length=10)
    prompt: Prompt | None = None
    context: dict[str, Any] = Field(default_factory=dict)  # template, language, framework, targets
    execute: bool = True
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{8,80}$")

    @field_validator("permitted_actions")
    @classmethod
    def _known_actions(cls, value: list[str]) -> list[str]:
        unknown = [a for a in value if a not in KNOWN_ACTIONS]
        if unknown:
            raise ValueError(f"Unknown actions: {', '.join(unknown)}")
        return value

    @field_validator("context")
    @classmethod
    def _small_context(cls, value: dict) -> dict:
        if len(str(value)) > 4_000:
            raise ValueError("context is too large")
        return value


class TaskSpec(BaseModel):
    """The server-resolved task. Every routing and gate decision reads this, not the request."""

    task_id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    workspace_id: str | None
    task_type: str
    task_description: str
    input_artifact_references: list[dict]
    required_capabilities: list[str]
    min_context_tokens: int
    complexity: str
    risk_level: str
    risk_reasons: list[str]
    quality_threshold: float
    latency_target_ms: int | None
    maximum_budget_usd: float
    maximum_attempts: int
    allowed_models: list[str]
    allowed_tools: list[str]
    permitted_actions: list[str]
    allowed_paths: list[str]
    execution_environment: dict
    approval_requirements: list[str]
    deterministic_options: list[dict]
    prompt: dict | None
    context: dict
    caller_role: str
    classification_source: str


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=80)  # e.g. "web.typecheck"
    kind: Literal[
        "typecheck", "lint", "unit_tests", "build", "e2e", "api_tests", "openapi", "integration_tests",
        "migrations", "schema", "secrets_scan", "sast", "dependency_scan", "dast", "mobile_config",
        "mobile_bundle", "response_schema", "format", "review", "path_policy",
    ]
    status: Literal["passed", "failed", "unavailable", "skipped"]
    duration_ms: int = Field(default=0, ge=0)
    output: str = Field(default="", max_length=100_000)
    findings: list[dict] = Field(default_factory=list, max_length=500)
    target: str | None = Field(default=None, max_length=40)


class RepairContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[ArtifactInput] = Field(default_factory=list, max_length=60)
    notes: str = Field(default="", max_length=8_000)


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Evidence] = Field(min_length=1, max_length=60)
    output_digest: str | None = Field(default=None, max_length=64)  # hash of the produced tree
    changed_files: list[str] = Field(default_factory=list, max_length=500)
    repair_context: RepairContext | None = None
    continue_automatically: bool = True


class UsageReport(BaseModel):
    """Usage reported by a runner outside AAEE, such as the CDE workspace agent."""

    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]{8,120}$")
    source: Literal["workspace_runner", "tool"] = "workspace_runner"
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    reported_cost_usd: float | None = Field(default=None, ge=0, le=1_000)
    billing_model: Literal["platform", "customer"] = "platform"
    details: dict = Field(default_factory=dict)


class WorkspaceCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "failed", "cancelled"]
    modified_files: list[str] = Field(default_factory=list, max_length=2_000)
    summary: str = Field(default="", max_length=8_000)
    error: str | None = Field(default=None, max_length=500)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool
    regression: bool = False
    comment: str = Field(default="", max_length=1_000)

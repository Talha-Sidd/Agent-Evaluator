"""Provider-neutral contracts for scenarios, traces, and agent outcomes."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PathText = Annotated[str, StringConstraints(min_length=1, max_length=512)]
FileText = Annotated[str, StringConstraints(max_length=262144)]


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    INVALID_TOOL_OUTPUT = "invalid_tool_output"
    TOOL_NOT_FOUND = "tool_not_found"
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_REQUIRED = "approval_required"
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    STEP_LIMIT_EXCEEDED = "step_limit_exceeded"
    EVALUATION_FAILURE = "evaluation_failure"
    INTERNAL_ERROR = "internal_error"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FailureCategory(StrEnum):
    CONTEXT_FAILURE = "context_failure"
    TOOL_SELECTION_FAILURE = "tool_selection_failure"
    TOOL_ARGUMENT_FAILURE = "tool_argument_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    REASONING_PLANNING_FAILURE = "reasoning_planning_failure"
    LOOP_BUDGET_FAILURE = "loop_budget_failure"
    PERMISSION_FAILURE = "permission_failure"
    POLICY_BLOCKED = "policy_blocked"
    ENVIRONMENT_FAILURE = "environment_failure"
    RECOVERY_CHECKPOINT_FAILURE = "recovery_checkpoint_failure"
    GRADER_EVALUATION_FAILURE = "grader_evaluation_failure"


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    risk: RiskLevel


class PermissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    allowed: bool
    requires_approval: bool
    reason: str


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    tool_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalResolution(BaseModel):
    """Immutable terminal decision for an approval request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID
    status: Literal[ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]
    resolved_at: datetime


class EvaluationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str
    skipped: bool = False


class FailureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FailureCategory
    evidence_event_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    likely_fix: str = Field(min_length=1)
    regression_candidate: bool = True


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    passed: bool
    checks: list[EvaluationCheck] = Field(default_factory=list)
    failure_reports: list[FailureReport] = Field(default_factory=list)


class ReplayCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    case_id: str = Field(min_length=1)
    baseline_run_id: UUID
    scenario: "Scenario"
    expected_status: RunStatus
    expected_final_answer: str
    expected_tool_names: list[str] = Field(default_factory=list)
    expected_trace_event_types: list[str] = Field(default_factory=list)
    expected_evaluation_passed: bool
    expected_execution: dict[str, Any]


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    replay_run_id: UUID
    passed: bool
    differences: list[str] = Field(default_factory=list)
    evaluation: EvaluationResult


class AgentTask(BaseModel):
    """Only task inputs, never grader labels or permissions chosen by an agent."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    scenario_id: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=4096)
    repository_files: dict[PathText, FileText] = Field(default_factory=dict, max_length=128)

    @model_validator(mode="after")
    def bounded_corpus(self) -> Self:
        if (
            sum(len(k.encode()) + len(v.encode()) for k, v in self.repository_files.items())
            > 1048576
        ):
            raise ValueError("repository exceeds 1 MiB")
        if not self.task.strip():
            raise ValueError("task must contain non-whitespace text")
        return self


class Scenario(AgentTask):
    category: str = Field(default="standard", min_length=1)
    expected_behavior: str = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_terms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=5, ge=1, le=100)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60, allow_inf_nan=False)
    expected_matching_files: list[PathText] | None = None
    replay_safe: bool = False

    def agent_task(self) -> AgentTask:
        return AgentTask(
            scenario_id=self.scenario_id,
            task=self.task,
            repository_files=self.repository_files.copy(),
        )


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    event_type: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_name: str | None = None
    call_id: UUID | None = None
    approval_id: UUID | None = None
    success: bool | None = None
    detail: str | None = None
    error_code: ErrorCode | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    call_id: UUID = Field(default_factory=uuid4)
    arguments: dict[str, Any] = Field(default_factory=dict)
    arguments_sha256: str | None = None
    success: bool
    permission_allowed: bool | None = None
    requires_approval: bool = False
    risk: RiskLevel | None = None
    executed: bool = False
    output: dict[str, Any] | None = None
    output_sha256: str | None = None
    error_code: ErrorCode | None = None


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    scenario_id: str
    status: RunStatus
    final_answer: str = Field(max_length=65536)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None
    error_code: ErrorCode | None = None

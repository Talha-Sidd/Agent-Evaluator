"""Provider-neutral contracts for scenarios, traces, and agent outcomes."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


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
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    tool_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


class EvaluationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str


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

    case_id: str = Field(min_length=1)
    baseline_run_id: UUID
    scenario: "Scenario"
    expected_status: RunStatus
    expected_final_answer: str
    expected_tool_names: list[str] = Field(default_factory=list)
    expected_trace_event_types: list[str] = Field(default_factory=list)
    expected_evaluation_passed: bool


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    replay_run_id: UUID
    passed: bool
    differences: list[str] = Field(default_factory=list)
    evaluation: EvaluationResult


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1)
    category: str = Field(default="standard", min_length=1)
    task: str = Field(min_length=1)
    repository_files: dict[str, str] = Field(default_factory=dict)
    expected_behavior: str = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_terms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=5, ge=1)


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    event_type: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_name: str | None = None
    approval_id: UUID | None = None
    success: bool | None = None
    detail: str | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    scenario_id: str
    status: RunStatus
    final_answer: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None

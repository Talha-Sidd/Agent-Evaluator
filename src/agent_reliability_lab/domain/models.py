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


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    passed: bool
    checks: list[EvaluationCheck] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    repository_files: dict[str, str] = Field(default_factory=dict)
    expected_behavior: str = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_terms: list[str] = Field(default_factory=list)
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

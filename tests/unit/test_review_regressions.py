"""Regression cases from the branch review; fixtures contain no real secrets."""

from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from agent_reliability_lab.domain.models import ApprovalStatus, RiskLevel
from agent_reliability_lab.platform.permissions.approvals import InMemoryApprovalStore
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.tools.registry import (
    ToolDefinition,
    ToolExecutionError,
    TypedToolRegistry,
)
from agent_reliability_lab.platform.tools.repopilot import (
    RepoSearchInput,
    RepoSearchOutput,
    build_repopilot_registry,
)


def invalid_output(_: RepoSearchInput) -> BaseModel:
    output = RepoSearchOutput(matching_files=["client.py"])
    output.matching_files.append(123)  # type: ignore[arg-type]
    return output


def test_returned_approval_cannot_change_store_state() -> None:
    store = InMemoryApprovalStore()
    record = store.request(uuid4(), "edit_file", "human decision needed")
    with pytest.raises(ValidationError):
        record.reason = "changed"
    resolution = store.approve(record.approval_id)
    with pytest.raises(ValidationError):
        resolution.status = ApprovalStatus.REJECTED
    assert store.get(record.approval_id) == record
    assert store.get_resolution(record.approval_id) == resolution


def test_mutated_output_is_revalidated() -> None:
    registry = TypedToolRegistry(DeterministicPermissionPolicy())
    registry.register(
        ToolDefinition(
            name="invalid",
            risk=RiskLevel.LOW,
            input_model=RepoSearchInput,
            output_model=RepoSearchOutput,
            handler=invalid_output,
        )
    )
    with pytest.raises(ToolExecutionError):
        registry.execute("invalid", {"query": "timeout", "repository_files": {}})


def test_validation_error_does_not_disclose_rejected_input() -> None:
    with pytest.raises(ToolExecutionError) as caught:
        build_repopilot_registry().execute(
            "repo_search", {"repository_files": {".env": "API_KEY=review-secret-canary"}}
        )
    assert "review-secret-canary" not in str(caught.value)


def test_search_rejects_unknown_arguments() -> None:
    with pytest.raises(ToolExecutionError):
        build_repopilot_registry().execute(
            "repo_search", {"query": "timeout", "repository_files": {}, "unexpected": True}
        )

"""Typed tools used by the deterministic RepoPilot demonstration."""

from pydantic import BaseModel, Field

from agent_reliability_lab.domain.models import RiskLevel
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.tools.registry import ToolDefinition, TypedToolRegistry


class RepoSearchInput(BaseModel):
    query: str = Field(min_length=1)
    repository_files: dict[str, str]


class RepoSearchOutput(BaseModel):
    matching_files: list[str]


def build_repopilot_registry() -> TypedToolRegistry:
    def search(input_data: RepoSearchInput) -> RepoSearchOutput:
        terms = input_data.query.lower().split()
        matches = [
            path
            for path, content in input_data.repository_files.items()
            if any(term in content.lower() for term in terms)
        ]
        return RepoSearchOutput(matching_files=matches)

    registry = TypedToolRegistry(DeterministicPermissionPolicy())
    registry.register(ToolDefinition(
        name="repo_search",
        risk=RiskLevel.LOW,
        input_model=RepoSearchInput,
        output_model=RepoSearchOutput,
        handler=search,
    ))
    return registry

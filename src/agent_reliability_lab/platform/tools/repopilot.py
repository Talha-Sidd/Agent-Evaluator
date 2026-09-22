"""Typed tools used by the deterministic RepoPilot demonstration."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_reliability_lab.domain.models import AgentTask, FileText, PathText, RiskLevel
from agent_reliability_lab.platform.permissions.policy import DeterministicPermissionPolicy
from agent_reliability_lab.platform.tools.registry import ToolDefinition, TypedToolRegistry


class RepoSearchInput(BaseModel):
    """Strict bounded input contract for repository text search."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")
    query: str = Field(min_length=1, max_length=4096)
    repository_files: dict[PathText, FileText] = Field(max_length=128)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        AgentTask(scenario_id="search", task=self.query, repository_files=self.repository_files)
        return self


class RepoSearchOutput(BaseModel):
    """Validated list of repository paths matching a search query."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")
    matching_files: list[PathText] = Field(max_length=128)


def search(input_data: RepoSearchInput) -> RepoSearchOutput:
    terms = list(dict.fromkeys(input_data.query.lower().split()))
    matches = []
    for path, content in input_data.repository_files.items():
        normalized = content.lower()
        if any(term in normalized for term in terms):
            matches.append(path)
    return RepoSearchOutput(matching_files=matches)


def build_repopilot_registry() -> TypedToolRegistry:

    registry = TypedToolRegistry(DeterministicPermissionPolicy())
    registry.register(
        ToolDefinition(
            name="repo_search",
            risk=RiskLevel.LOW,
            input_model=RepoSearchInput,
            output_model=RepoSearchOutput,
            handler=search,
        )
    )
    return registry

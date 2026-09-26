"""Deterministic summaries of parent-observed monotonic durations."""

import math
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_reliability_lab.domain.models import AgentResult


class LatencyDistribution(BaseModel):
    """Nearest-rank quantiles in milliseconds, including missing evidence."""

    model_config = ConfigDict(extra="forbid")

    unit: Literal["ms"] = "ms"
    samples: int = Field(ge=0)
    missing: int = Field(ge=0)
    minimum_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    p50_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    p95_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    maximum_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        values = (self.minimum_ms, self.p50_ms, self.p95_ms, self.maximum_ms)
        if self.samples == 0 and any(value is not None for value in values):
            raise ValueError("empty distribution cannot have quantiles")
        if self.samples:
            measured = [value for value in values if value is not None]
            if len(measured) != len(values) or measured != sorted(measured):
                raise ValueError("measured distribution requires ordered quantiles")
        return self


class SuiteLatency(BaseModel):
    """Separate total, startup, and request distributions for one suite."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["parent_monotonic"] = "parent_monotonic"
    quantile_method: Literal["nearest_rank"] = "nearest_rank"
    run: LatencyDistribution
    agent_worker_startup: LatencyDistribution
    tool_request: LatencyDistribution
    tool_worker_startup: LatencyDistribution


def distribution(samples_ms: Sequence[float], *, missing: int = 0) -> LatencyDistribution:
    """Compute exact nearest-rank p50/p95 with no measured data substitution."""
    if missing < 0 or any(not math.isfinite(value) or value < 0 for value in samples_ms):
        raise ValueError("latency measurements must be finite and nonnegative")
    ordered = sorted(samples_ms)
    if not ordered:
        return LatencyDistribution(samples=0, missing=missing)
    return LatencyDistribution(
        samples=len(ordered), missing=missing, minimum_ms=ordered[0],
        p50_ms=ordered[math.ceil(0.5 * len(ordered)) - 1],
        p95_ms=ordered[math.ceil(0.95 * len(ordered)) - 1],
        maximum_ms=ordered[-1],
    )


def summarize_latency(results: Sequence[AgentResult]) -> SuiteLatency:
    """Aggregate harness-owned measurements; no clock reads occur here."""
    calls = [call for result in results for call in result.tool_calls]
    executed = [call for call in calls if call.executed]
    run_values = [result.timing.run_duration_ms for result in results if result.timing]
    agent_values = [result.timing.agent_worker_startup_ms for result in results
                    if result.timing and result.timing.agent_worker_startup_ms is not None]
    request_values = [call.request_duration_ms for call in calls
                      if call.request_duration_ms is not None]
    tool_values = [call.worker_startup_ms for call in executed
                   if call.worker_startup_ms is not None]
    return SuiteLatency(
        run=distribution(run_values, missing=len(results) - len(run_values)),
        agent_worker_startup=distribution(agent_values, missing=len(results) - len(agent_values)),
        tool_request=distribution(request_values, missing=len(calls) - len(request_values)),
        tool_worker_startup=distribution(tool_values, missing=len(executed) - len(tool_values)),
    )

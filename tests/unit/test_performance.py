"""Deterministic latency fixtures; no wall-clock thresholds in unit tests."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent_reliability_lab.domain.models import AgentResult, RunStatus, RunTiming, ToolCall
from agent_reliability_lab.platform.evals.performance import distribution, summarize_latency


def test_nearest_rank_fixture() -> None:
    fixture = json.loads(Path("tests/fixtures/performance_samples.json").read_text())
    assert fixture["schema_version"] == 1
    result = distribution(fixture["samples"], missing=fixture["missing"])
    assert result.unit == fixture["unit"]
    assert result.samples == 5 and result.missing == 2
    for name, value in fixture["expected"].items():
        assert getattr(result, name) == value


def test_missing_measurements_remain_visible() -> None:
    measured = AgentResult(
        run_id=uuid4(), scenario_id="measured", status=RunStatus.SUCCEEDED,
        final_answer="done", timing=RunTiming(run_duration_ms=40, agent_worker_startup_ms=10),
        tool_calls=[
            ToolCall(name="search", success=True, executed=True,
                     request_duration_ms=20, worker_startup_ms=5),
            ToolCall(name="blocked", success=False, executed=False, request_duration_ms=2),
        ],
    )
    missing = AgentResult(
        run_id=uuid4(), scenario_id="missing", status=RunStatus.FAILED,
        final_answer="failed", tool_calls=[ToolCall(name="search", success=False, executed=True)],
    )
    summary = summarize_latency([measured, missing])
    assert summary.source == "parent_monotonic"
    assert summary.quantile_method == "nearest_rank"
    assert (summary.run.samples, summary.run.missing, summary.run.p95_ms) == (1, 1, 40)
    assert (summary.agent_worker_startup.samples, summary.agent_worker_startup.missing) == (1, 1)
    assert (summary.tool_request.samples, summary.tool_request.missing) == (2, 1)
    assert (summary.tool_worker_startup.samples, summary.tool_worker_startup.missing) == (1, 1)


@pytest.mark.parametrize("values", [[-1], [float("nan")], [float("inf")]])
def test_invalid_measurements_are_rejected(values: list[float]) -> None:
    with pytest.raises(ValueError):
        distribution(values)

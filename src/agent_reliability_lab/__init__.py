"""Agent Reliability Lab public Python API.

The top-level :func:`evaluate` helper is the simplest way to run an agent
against a JSONL scenario file. Detailed run evidence remains available on the
returned report.
"""

from pathlib import Path

from agent_reliability_lab.domain.protocols import AgentAdapter
from agent_reliability_lab.platform.evals.suite import (
    CaseReport,
    EvaluationSuite,
    SuiteScorecard,
)
from agent_reliability_lab.platform.model_gateway import ModelGateway
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.tools.registry import TypedToolRegistry


class EvaluationReport:
    """Convenient consumer view over a complete deterministic scorecard."""

    def __init__(self, scorecard: SuiteScorecard) -> None:
        self.scorecard = scorecard

    @property
    def passed(self) -> bool:
        """Whether every scenario passed its configured deterministic checks."""
        return self.scorecard.passed_cases == self.scorecard.total_cases

    @property
    def passed_cases(self) -> int:
        return self.scorecard.passed_cases

    @property
    def total_cases(self) -> int:
        return self.scorecard.total_cases

    @property
    def cases(self) -> list[CaseReport]:
        """Per-case evaluations, observed tool calls, traces, and model calls."""
        return self.scorecard.cases

    def summary(self) -> dict[str, object]:
        """Return a compact summary with observed reliability and timing data."""
        latency = self.scorecard.latency
        model_calls = [
            call for case in self.scorecard.cases for call in case.result.model_calls
        ]
        return {
            "suite": self.scorecard.suite_name,
            "passed": self.passed,
            "cases_passed": self.passed_cases,
            "cases_total": self.total_cases,
            "task_success_rate": self.scorecard.task_success_rate,
            "failure_categories": self.scorecard.failure_category_counts,
            "latency_ms": {
                "run_p50": latency.run.p50_ms if latency else None,
                "run_p95": latency.run.p95_ms if latency else None,
            },
            "tool_calls": sum(len(case.result.tool_calls) for case in self.cases),
            "model_calls": len(model_calls),
            "estimated_model_cost_usd": sum(
                call.estimated_cost_usd or 0.0 for call in model_calls
            ),
        }


def evaluate(
    *,
    agent: AgentAdapter,
    scenarios: Path,
    suite_name: str | None = None,
    tools: TypedToolRegistry | None = None,
    model_gateway: ModelGateway | None = None,
) -> EvaluationReport:
    """Run a connected agent on a reviewed JSONL scenario file.

    ``tools`` is optional for answer-only agents. Register tools here when their
    calls must be schema-validated, permission-checked, executed, and traced by
    the harness. A direct or black-box agent integration cannot provide those
    tool guarantees. Live provider configuration is supplied explicitly via
    ``model_gateway`` and should have bounded call, token, time, and cost limits.
    """
    runner = ScenarioRunner(registry=tools, gateway=model_gateway)
    suite = EvaluationSuite(agent=agent, runner=runner)
    cases = suite.load_jsonl(scenarios)
    scorecard = suite.run(cases, suite_name or agent.name)
    return EvaluationReport(scorecard)


__all__ = ["EvaluationReport", "evaluate"]

"""Command-line entry points for deterministic evaluation."""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from agent_reliability_lab.agents.repopilot.model import (
    REPOPILOT_PROMPT_VERSION,
    REPOPILOT_SYSTEM_PROMPT,
    RepoPilotModel,
)
from agent_reliability_lab.domain.model_gateway import ModelConfig
from agent_reliability_lab.domain.models import Scenario
from agent_reliability_lab.platform.evals.comparison import (
    EVALUATOR_VERSION,
    compare_snapshots,
    create_snapshot,
    load_snapshot,
    save_snapshot,
)
from agent_reliability_lab.platform.evals.live import save_live_report
from agent_reliability_lab.platform.evals.quality_gate import (
    QualityGate,
    QualityGateConfig,
    QualityGateResult,
)
from agent_reliability_lab.platform.evals.suite import EvaluationSuite, SuiteScorecard
from agent_reliability_lab.platform.model_gateway import ModelGateway
from agent_reliability_lab.platform.replay import ReplayRunner
from agent_reliability_lab.platform.runner.runner import ScenarioRunner
from agent_reliability_lab.platform.security import fingerprint
from agent_reliability_lab.platform.storage.postgres import PostgresRunRepository, StorageError


def _load_gate_config(path: Path) -> QualityGateConfig:
    return QualityGateConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _run_eval(
    dataset: Path, gate_config_path: Path, as_json: bool,
    snapshot_path: Path | None = None, agent_version: str | None = None,
) -> int:
    if (snapshot_path is None) != (agent_version is None):
        raise ValueError("snapshot and agent version must be supplied together")
    config = _load_gate_config(gate_config_path)
    suite = EvaluationSuite()
    scenarios = suite.load_jsonl(dataset)
    scorecard = suite.run(scenarios, dataset.stem)
    gate = QualityGate(config).evaluate(scorecard)
    if snapshot_path is not None and agent_version is not None:
        save_snapshot(create_snapshot(scenarios, scorecard, agent_version), snapshot_path)
    if as_json:
        output = scorecard.model_dump(mode="json")
        output["quality_gate"] = gate.model_dump(mode="json")
        print(json.dumps(output, indent=2))
    else:
        _print_scorecard(scorecard, gate)
    return 0 if gate.passed else 1


def _run_compare(baseline: Path, candidate: Path, gate_config: Path, as_json: bool) -> int:
    result = compare_snapshots(
        load_snapshot(baseline), load_snapshot(candidate), _load_gate_config(gate_config)
    )
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Comparison: {result.baseline_version} -> {result.candidate_version}")
        print(f"Task success: {result.baseline_success_rate:.1%} -> "
              f"{result.candidate_success_rate:.1%}")
        print("Regressions: " + (", ".join(result.regressions) or "none"))
        print("Improvements: " + (", ".join(result.improvements) or "none"))
        print(f"Comparison gate: {'PASSED' if result.passed else 'FAILED'}")
        for violation in result.violations:
            print(f"Gate violation: {violation}")
    return 0 if result.passed else 1


def _run_live_eval(
    dataset: Path,
    gate_config_path: Path,
    baseline_path: Path,
    output_path: Path,
    model: str,
    input_price: float,
    output_price: float,
    max_cost: float,
    max_calls: int,
    max_input_tokens: int,
    max_output_tokens: int,
    token_budget: int,
) -> int:
    if output_path.exists():
        raise FileExistsError("live report already exists")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is required for live evaluation")
    try:
        from agent_reliability_lab.platform.providers.openai import OpenAIProvider
    except ImportError:
        raise ValueError("install the OpenAI extra with `uv sync --extra openai-live`") from None
    gate_config = _load_gate_config(gate_config_path)
    baseline = load_snapshot(baseline_path)
    suite = EvaluationSuite(
        agent=RepoPilotModel(),
        runner=ScenarioRunner(
            gateway=ModelGateway(
                OpenAIProvider(),
                ModelConfig(
                    provider="openai",
                    model=model,
                    prompt_version=REPOPILOT_PROMPT_VERSION,
                    system_prompt=REPOPILOT_SYSTEM_PROMPT,
                    input_usd_per_million=input_price,
                    output_usd_per_million=output_price,
                    cost_budget_usd=max_cost,
                    max_calls=max_calls,
                    max_input_tokens=max_input_tokens,
                    max_output_tokens=max_output_tokens,
                    token_budget=token_budget,
                ),
            )
        ),
    )
    scenarios = suite.load_jsonl(dataset)
    expected = {
        scenario.scenario_id: fingerprint(scenario.model_dump(mode="json"))
        for scenario in scenarios
    }
    baseline_cases = {case.scenario_id: case for case in baseline.cases}
    if (
        baseline.evaluator_version != EVALUATOR_VERSION
        or baseline.dataset_sha256 != fingerprint(expected)
        or set(baseline_cases) != set(expected)
        or any(
            baseline_cases[key].scenario_sha256 != digest
            or baseline_cases[key].fixture_sha256 != fingerprint(
                next(item.repository_files for item in scenarios if item.scenario_id == key)
            )
            for key, digest in expected.items()
        )
    ):
        raise ValueError("baseline must match the selected dataset and evaluator")
    scorecard = suite.run(scenarios, dataset.stem)
    gate = QualityGate(gate_config).evaluate(scorecard)
    version = "openai-live-" + hashlib.sha256(
        f"{model}:{REPOPILOT_PROMPT_VERSION}".encode()
    ).hexdigest()[:12]
    candidate = create_snapshot(scenarios, scorecard, version)
    comparison = compare_snapshots(
        baseline, candidate, gate_config
    )
    model_calls = [call for case in scorecard.cases for call in case.result.model_calls]
    known_cost = sum(call.estimated_cost_usd or 0 for call in model_calls)
    missing_cost = sum(call.executed and call.estimated_cost_usd is None for call in model_calls)
    missing_usage = sum(
        call.executed and (call.input_tokens is None or call.output_tokens is None)
        for call in model_calls
    )
    successful_cases = scorecard.passed_cases
    report = {
        "schema_version": 1,
        "provider": "openai",
        "model": model,
        "prompt_version": REPOPILOT_PROMPT_VERSION,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "prices_usd_per_million_tokens": {
            "input": input_price,
            "output": output_price,
            "source": "operator_configured",
        },
        "cost_budget_usd": max_cost,
        "usage": {
            "model_calls": len(model_calls),
            "input_tokens": sum(call.input_tokens or 0 for call in model_calls),
            "output_tokens": sum(call.output_tokens or 0 for call in model_calls),
            "estimated_cost_usd_known": known_cost,
            "calls_with_unknown_cost": missing_cost,
            "calls_with_unknown_token_usage": missing_usage,
            "successful_cases": successful_cases,
            "estimated_cost_per_success_usd": (
                known_cost / successful_cases if successful_cases and not missing_cost else None
            ),
        },
        "scorecard": scorecard.model_dump(mode="json"),
        "quality_gate": gate.model_dump(mode="json"),
        "candidate_snapshot": candidate.model_dump(mode="json"),
        "baseline_comparison": comparison.model_dump(mode="json"),
    }
    save_live_report(report, output_path)
    print(f"Live evaluation: {scorecard.passed_cases}/{scorecard.total_cases} cases passed")
    print(f"Estimated known cost: ${known_cost:.6f} USD ({missing_cost} calls unknown)")
    print(f"Baseline comparison: {'PASSED' if comparison.passed else 'FAILED'}")
    print(f"Report: {output_path}")
    return 0 if gate.passed and comparison.passed else 1


def _print_scorecard(scorecard: SuiteScorecard, gate: QualityGateResult) -> None:
    print(f"Suite: {scorecard.suite_name}")
    print(f"Cases: {scorecard.passed_cases}/{scorecard.total_cases} passed")
    print(f"Task success rate: {scorecard.task_success_rate:.1%}")
    if scorecard.latency is not None:
        run_latency = scorecard.latency.run
        if run_latency.p50_ms is None or run_latency.p95_ms is None:
            print(f"Run latency: unmeasured ({run_latency.missing} missing)")
        else:
            print(
                f"Run latency: p50 {run_latency.p50_ms:.1f} ms, "
                f"p95 {run_latency.p95_ms:.1f} ms "
                f"({run_latency.samples} measured, {run_latency.missing} missing)"
            )
    if scorecard.failed_cases:
        print("Failed cases: " + ", ".join(scorecard.failed_cases))
    if scorecard.failure_category_counts:
        print(
            "Failure categories: " + json.dumps(scorecard.failure_category_counts, sort_keys=True)
        )
    print(f"Quality gate: {'PASSED' if gate.passed else 'FAILED'}")
    for violation in gate.violations:
        print(f"Gate violation: {violation}")


def _scenario_from_dataset(dataset: Path, scenario_id: str) -> Scenario:
    suite = EvaluationSuite()
    for scenario in suite.load_jsonl(dataset):
        if scenario.scenario_id == scenario_id:
            return scenario
    raise ValueError(f"scenario not found: {scenario_id}")


def _run_replay_create(dataset: Path, scenario_id: str, output: Path, force: bool = False) -> int:
    scenario = _scenario_from_dataset(dataset, scenario_id)
    runner = ReplayRunner()
    case = runner.create_case(scenario, scenario_id)
    runner.save_case(case, output, overwrite=force)
    print(f"Replay case created: {output}")
    return 0


def _run_replay_case(case_path: Path, as_json: bool) -> int:
    runner = ReplayRunner()
    result = runner.replay(runner.load_case(case_path))
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Replay case: {result.case_id}")
        print(f"Replay: {'PASSED' if result.passed else 'FAILED'}")
        for difference in result.differences:
            print(f"Difference: {difference}")
    return 0 if result.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    eval_parser = subparsers.add_parser("eval", help="run a deterministic evaluation suite")
    eval_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/repopilot_smoke.jsonl"),
    )
    eval_parser.add_argument(
        "--gate-config",
        type=Path,
        default=Path("evals/quality_gate.json"),
    )
    eval_parser.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    eval_parser.add_argument("--snapshot", type=Path, help="write a new evaluation snapshot")
    eval_parser.add_argument("--agent-version", help="version label for the evaluated checkout")
    live_parser = subparsers.add_parser(
        "live-eval", help="run an opt-in OpenAI evaluation (uses API credits)"
    )
    live_parser.add_argument("--dataset", type=Path, default=Path("evals/datasets/repopilot_smoke.jsonl"))
    live_parser.add_argument("--gate-config", type=Path, default=Path("evals/quality_gate.json"))
    live_parser.add_argument("--baseline", type=Path, default=Path("evals/baselines/repopilot.json"))
    live_parser.add_argument("--output", type=Path, required=True)
    live_parser.add_argument("--model", required=True, help="OpenAI model ID")
    live_parser.add_argument("--input-usd-per-million", type=float, required=True)
    live_parser.add_argument("--output-usd-per-million", type=float, required=True)
    live_parser.add_argument("--max-cost-usd", type=float, required=True,
                             help="maximum estimated suite-wide model cost")
    live_parser.add_argument("--max-model-calls", type=int, default=8)
    live_parser.add_argument("--max-input-tokens", type=int, default=4096)
    live_parser.add_argument("--max-output-tokens", type=int, default=512)
    live_parser.add_argument("--token-budget", type=int, default=40000)
    compare_parser = subparsers.add_parser("compare", help="compare two evaluation snapshots")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--gate-config", type=Path, default=Path("evals/quality_gate.json"))
    compare_parser.add_argument("--json", action="store_true")
    replay_parser = subparsers.add_parser("replay", help="create or run replay artifacts")
    replay_subparsers = replay_parser.add_subparsers(dest="replay_command", required=True)
    create_parser = replay_subparsers.add_parser("create", help="freeze a scenario baseline")
    create_parser.add_argument("--dataset", type=Path, required=True)
    create_parser.add_argument("--scenario-id", required=True)
    create_parser.add_argument("--output", type=Path, required=True)
    create_parser.add_argument("--force", action="store_true", help="replace an existing artifact")
    run_parser = replay_subparsers.add_parser("run", help="replay a frozen case")
    run_parser.add_argument("--case", type=Path, required=True)
    run_parser.add_argument("--json", action="store_true", help="print replay result as JSON")
    db_parser = subparsers.add_parser("db", help="manage durable evidence schema")
    db_parser.add_argument("operation", choices=["migrate"])
    args = parser.parse_args(argv)

    try:
        if args.command == "eval":
            return _run_eval(
                args.dataset, args.gate_config, args.json, args.snapshot, args.agent_version
            )
        if args.command == "compare":
            return _run_compare(args.baseline, args.candidate, args.gate_config, args.json)
        if args.command == "live-eval":
            return _run_live_eval(
                args.dataset, args.gate_config, args.baseline, args.output, args.model,
                args.input_usd_per_million, args.output_usd_per_million, args.max_cost_usd,
                args.max_model_calls, args.max_input_tokens, args.max_output_tokens,
                args.token_budget,
            )
        if args.command == "replay" and args.replay_command == "create":
            return _run_replay_create(args.dataset, args.scenario_id, args.output, args.force)
        if args.command == "replay" and args.replay_command == "run":
            return _run_replay_case(args.case, args.json)
        if args.command == "db" and args.operation == "migrate":
            dsn = os.environ.get("ARL_DATABASE_URL")
            if not dsn:
                raise ValueError("ARL_DATABASE_URL is required")
            PostgresRunRepository(dsn).migrate()
            print("Database migrations applied.")
            return 0
    except StorageError:
        print(json.dumps({"error": "storage_error"}), file=sys.stderr)
        return 2
    except (OSError, ValueError, ValidationError) as exc:
        # Never print validation payloads, file contents, or arbitrary exception strings.
        code = "artifact_exists" if isinstance(exc, FileExistsError) else "invalid_input"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

# Agent Reliability Lab

Agent Reliability Lab is a small, explicit foundation for running repeatable
scenarios against tool-using agents and collecting evidence about their behavior.
It follows the build plan in `06_Agent_Reliability_Lab_Build_Playbook.md`.

## Current slice

The deterministic foundation currently contains:

- typed scenario and run contracts;
- an `AgentAdapter` protocol independent of any concrete agent;
- a deterministic `RepoPilotDemo` adapter;
- normalized trace events;
- a deterministic scenario runner;
- a typed tool registry with Pydantic input/output validation;
- a deterministic permission policy for low, medium, and high-risk actions;
- explicit in-memory approval state for actions needing human review;
- a starter evaluator for observable run behavior;
- FastAPI health, run, result, and evaluation lookup endpoints;
- optional PostgreSQL evidence storage with explicit migrations;
- a ten-case JSONL evaluation suite;
- an `arl eval` command that produces a deterministic scorecard;
- typed failure categories with trace-linked failure reports;
- failure-category counts in the suite scorecard;
- deterministic replay cases for frozen scenario behavior;
- configurable quality gates for task success and permission failures;
- JSON replay artifacts with create/run CLI commands;
- compact versioned evaluation snapshots and baseline/candidate comparison;
- per-case regression gates and a Linux/Windows CI workflow;
- parent-observed monotonic run/tool timing and suite latency distributions;
- a provider-neutral model gateway, scripted fake provider, and bounded model-backed RepoPilot;
- parent-owned model evidence with token usage, estimated USD cost, and latency;
- unit and integration tests.

The harness records tool requests, validated arguments (with fixture hashes),
permission decisions, execution outcomes, and terminal run events. Medium- and
high-risk actions require approval and cannot execute automatically. Approval
records are immutable and transitions are atomic; pause/resume is still future
work, so approving a record does not enable execution yet.

Timing fields use milliseconds from the parent process's monotonic clock. Run
duration includes validation, agent worker startup, execution, worker teardown,
and result normalization. Agent and tool worker startup end when the parent
receives each worker's ready message; tool request duration includes validation,
permission checks, worker startup, execution, and teardown. Suite summaries use
nearest-rank p50/p95 values and report missing measurements separately. The
versioned synthetic fixture in `tests/fixtures/performance_samples.json` checks
the aggregation method. These are observations, not release gates; no latency
threshold is set without a documented performance baseline.

OpenAI is available through the explicit `arl live-eval` command. The normal
evaluation and CI paths do not make provider calls; see the roadmap below for
live setup and cost controls.

Adapters and tool handlers run in supervised Python worker processes so timeouts
can stop execution. This is lifecycle isolation for trusted code, not an OS
security sandbox. API results use bounded in-memory retention by default.

## Roadmap: real LLM evaluation

The provider-neutral gateway and model-backed RepoPilot adapter are tested with
a fake provider. The OpenAI Responses API adapter and opt-in `arl live-eval`
command run the model-backed agent against the same dataset and reviewed baseline.
Reports include model and prompt versions, usage, estimated cost, latency,
trajectory, the quality gate, and per-case baseline comparisons. The parent
enforces per-run call, token, and time limits and reserves cost against one
suite-wide ceiling. One live run was verified against the bundled ten-case
suite on 2026-09-26: nine passed and one timed out, so its zero-regression
comparison failed. Known estimated cost was $0.001726, with one timed-out call's
usage unknown. This does not establish repeated performance or exact billing;
prices are provided by the operator. Ordinary `arl eval` and CI remain
deterministic and make no provider calls. See
[the LLM evaluation roadmap](docs/LLM_EVALUATION_ROADMAP.md) for setup and limits.

For PowerShell, set the key in the current session and supply a model ID,
operator-configured input/output prices per million tokens, a suite cost ceiling,
and a new report path:

```powershell
$env:OPENAI_API_KEY = "..."
uv sync --locked
uv run --locked arl live-eval --model YOUR_MODEL_ID `
  --input-usd-per-million YOUR_INPUT_PRICE `
  --output-usd-per-million YOUR_OUTPUT_PRICE `
  --max-cost-usd 0.25 --output reports/openai-live.json
```

For a runtime-only install, use `uv sync --no-dev --extra openai-live --locked`.

The selected dataset's task text and repository fixtures are sent to OpenAI.
The default dataset contains synthetic fixtures; review replacement datasets
before running the live command. Reports do not overwrite earlier evidence.

Python callers can use `EvaluationSuite(agent=RepoPilotModel(),
runner=ScenarioRunner(gateway=ModelGateway(provider, config)))`. Model-backed
execution is opt-in; the CLI and API still use the deterministic agent by default.
Configuration and a runnable fake-provider example are in the roadmap.

To evaluate an agent implemented outside this package, see the runnable
[external-agent integration example](docs/EXTERNAL_AGENT_INTEGRATION.md). It
registers an application-owned agent and typed tool, evaluates shared scenarios,
prints per-case results, and compares against a saved baseline. The CLI and API
do not dynamically load arbitrary agents.

## Development

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
uv run arl eval
uv build
```

The evaluation command runs the golden scenarios and reports the number of
passing cases, task success rate, and failure categories. Use
`uv run arl eval --json` for a machine-readable scorecard. A failed evaluation
also records trace event IDs, confidence, a likely fix, and whether it should
become a regression candidate.

Replay is available as a typed platform component. `ReplayRunner` can freeze
an important run and replay it later against the same deterministic fixture.
Version 2 artifacts compare status, answer, validated argument/output hashes,
sanitized tool records, permission outcomes, linked trace events, typed errors,
and individual evaluation checks. Generated timestamps and IDs are normalized.
Version 1 artifacts must be recreated and reviewed; they are never silently
accepted as equivalent evidence.

The evaluation command applies thresholds from `evals/quality_gate.json`.
It returns exit code `0` when the gate passes and exit code `1` when task
success or safety thresholds fail.
The ten original search cases use exact matching-file assertions. Two additional
medium/high-risk negative controls run through the registry; a permissive policy
fails the gate even when all search tasks succeed. JSON scorecards include each
case's result, evaluation, and linked evidence. Invalid CLI input returns code 2
with a sanitized JSON error on stderr.

Create and run a replay artifact:

```powershell
uv run arl replay create --dataset evals/datasets/repopilot_smoke.jsonl `
  --scenario-id repopilot-search-001 --output evals/replays/my-search-case.json
uv run arl replay run --case evals/replays/search-001.json --json
```

Replay artifacts freeze the scenario and observable baseline so a later run
can be compared without relying on a changing live environment.
Fixtures must explicitly set `replay_safe: true` to attest that they are synthetic.
Sensitive filenames and recognized credential patterns are rejected. Existing
artifacts are protected from replacement unless `--force` is provided. Redaction
is a defensive pattern filter, not a guarantee that arbitrary private text can
be recognized; do not mark real private repositories as synthetic.

## API configuration and limits

`GET /health` is public. Run endpoints require a bearer token whose owner is
configured server-side through `create_app(api_tokens={token: owner})` or the
`ARL_API_TOKENS` environment variable (a JSON object mapping tokens to owners).
Use cryptographically random tokens of at least 32 characters. Do not commit
tokens. Without configuration, run endpoints return 503. Missing/invalid
credentials return 401, and another owner's run returns 404. Use TLS when
access is not confined to a trusted local machine.

Public results omit raw task arguments and free-form agent answers; structured
search output remains in `tool_calls[].output`. Validation errors do not echo
rejected input. Retention defaults to 100 runs, 8 MiB of serialized results,
and a 300-second TTL; expiry is checked on reads/writes. Two runs may execute
concurrently per service instance. Without a database, state and limits are
process-local: deploy a single application worker.

Set `ARL_DATABASE_URL` to a PostgreSQL connection URL to persist completed runs,
ordered trace events, evaluations, owner identity, and agent/evaluator versions.
Run `uv run arl db migrate` before starting the API; migrations are explicit and
checksum-checked. Database reads remain owner-scoped, and results expire after
the configured TTL. Writes enforce the same run-count and serialized-evidence
budget across application processes. An unavailable database returns 503, and
an uninitialized schema fails closed. Keep the URL in environment configuration,
not source control. `GET /runs/{run_id}/evaluation` uses the same bearer-token
and owner checks as result retrieval.

The PostgreSQL integration tests require an explicitly disposable database:

```powershell
$env:ARL_TEST_DATABASE_URL = "postgresql://arl:password@localhost:5432/arl_test"
$env:ARL_ALLOW_TEST_DB_RESET = "1"
uv run pytest tests/integration/test_postgres_storage.py
```

These tests truncate their test tables. They passed against a disposable local
PostgreSQL 18 cluster. The CI workflow provisions a temporary PostgreSQL service;
hosted execution has not yet been observed.

Requests are capped at 2 MiB and have a 10-second body-read deadline. A scenario
allows at most 128 files, 256 Ki characters per file, 1 MiB of total UTF-8 corpus,
and 4,096 query characters. The default run deadline is 15 seconds (maximum 60);
the default step budget is five (maximum 100). A tool output is limited to
128 KiB, an API result to 1 MiB. Overload returns 429; size rejection returns 413
or schema-validation 422. Handler/run deadlines include worker startup time.

## Adapter contract

Implement `run(task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult`.
`AgentTask` excludes grader labels and permission expectations. Request tools
through the supplied executor; the parent harness owns dispatch, budget checks,
permission checks, calls, and traces. Adapter-reported calls and traces are not
accepted as evidence. Synchronous deadlines terminate and join worker processes;
already completed external effects cannot be rolled back automatically.

Adapters, handlers, and tool DTOs must be importable top-level Python objects
compatible with multiprocessing `spawn`. Use the standard `if __name__ ==
"__main__":` guard in custom launch scripts. Closures, lambdas, and notebook-local
handlers are unsupported. Workers must not spawn unmanaged descendants or depend
on mutations to parent-process memory. This adds measurable startup overhead in
exchange for enforceable deadlines.

The `arl eval` default data/config paths are relative to the repository root.
Outside it, pass explicit `--dataset` and `--gate-config` paths. Package builds
now include the version-controlled README; a clean-source build is part of the
verification checklist.

See [the review-fix notes](docs/REVIEW_FIXES_2026-09-22.md) for the changes and
validation associated with the branch review.

## Compare agent versions

Capture a baseline from its checkout, then capture a candidate from the changed
checkout using the same dataset. Version labels are metadata, not agent selectors.
The CLI evaluates the RepoPilot implementation in the current checkout; Python
callers can inject an adapter into `EvaluationSuite` and use `create_snapshot`.

```powershell
uv run arl eval --snapshot reports/baseline.json --agent-version v1
uv run arl eval --snapshot reports/candidate.json --agent-version v2
uv run arl compare --baseline reports/baseline.json --candidate reports/candidate.json --json
```

Comparison requires matching dataset, fixture, and evaluator identities. It
reports individual regressions, improvements, unchanged outcomes, and success-rate
changes. `regression_tolerance` in gate configuration defaults to zero and counts
baseline-pass/candidate-fail cases divided by all cases, not the net success-rate
change. Candidate absolute success and safety gates still apply. Exit codes are
0 for a passing gate, 1 for a failing gate, and 2 for invalid input.

Snapshots contain identifiers, hashes, outcomes, failure categories, and safety
checks; they exclude raw task/fixture content and agent answers. They are trusted
local artifacts, not cryptographically signed evidence. They refuse replacement;
use a new filename and review baseline changes. Full trajectory comparison remains
the responsibility of replay. Bump `EVALUATOR_VERSION` when grading semantics change.

`.github/workflows/quality.yml` separates Python checks, Linux/Windows tests,
agent evaluation, PostgreSQL integration, and package building into named jobs.
Evaluation compares against `evals/baselines/repopilot.json` and replays a frozen
case. Test and evaluation reports are retained for 14 days. The refined hosted
workflow passed on 2026-09-26. There is no automatic release or baseline
promotion. Action usage follows the
official [checkout](https://github.com/actions/checkout),
[setup-uv](https://github.com/astral-sh/setup-uv), and
[artifact upload](https://github.com/actions/upload-artifact) documentation.

See the [build playbook](06_Agent_Reliability_Lab_Build_Playbook.md) for the
project scope and the remaining optional work.

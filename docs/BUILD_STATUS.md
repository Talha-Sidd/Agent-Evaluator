# Agent Reliability Lab — Build Status

Updated: 2026-09-26

## Current status (2026-09-26)

The last commit is `36f9bee` (`Add opt-in OpenAI live evaluation`). The
external-agent example and documentation below are implemented in the current
working tree but have not been committed yet.

### What is demonstrated now

- The core harness runs bounded scenarios, validates typed tool requests,
  applies permission policy, records traces, evaluates deterministic
  assertions, replays cases, and compares versioned snapshots.
- A separate `examples/external_calculator/` application implements the
  `AgentAdapter` contract, registers its own calculator tool, runs three cases,
  and compares its results with a saved baseline. This demonstrates a Python
  integration path; it does not yet evaluate one of the user's agents.
- The example's negative controls verify malformed arguments, unknown tools,
  approval-required actions, and handler errors. These prove harness boundary
  behavior; they are not a prompt-injection evaluation suite.
- The CLI and API still default to RepoPilot. Arbitrary agents are not
  dynamically loaded.

### Security status

The harness validates registered tool names and typed arguments, enforces
permissions, step/time limits, and records decisions and outcomes. The current
scenario grader can inspect final-answer terms, required/forbidden tool use,
run status, trace integrity, and selected RepoPilot search outcomes.

Prompt injection is **not yet tested end to end**. RepoPilot's prompt says to
treat fixture content as untrusted, but there are no adversarial direct or
indirect injection scenarios proving that behavior. The harness can grade
observable answers and actions; it cannot certify an agent's internal
reasoning. A denied high-risk action is blocked, but human review, pause/resume,
and persisted checkpoints remain unfinished.

### Latest verification

```text
uv run --locked pytest tests/integration/test_external_agent.py  5 passed
uv run --locked ruff check .                                   passed
uv run --locked mypy src                                       passed, 41 source files
uv run --locked python -m examples.external_calculator.evaluate 3/3 cases;
                                                               baseline comparison passed
```

The external example's live command is not part of CI and makes no provider
calls. A separate opt-in OpenAI run against the bundled RepoPilot suite
completed 9/10 cases; one timed out, causing the zero-regression comparison to
fail. Known estimated cost was $0.001726, with one timed-out call's usage
unknown. This is one run, not a stable performance baseline or exact billing.
See [TODO.md](TODO.md) for the security-first next batches and acceptance
criteria.

## Source of direction

The implementation follows `06_Agent_Reliability_Lab_Build_Playbook.md` and
starts with its Day 1 foundation. The larger project prompt remains the
architectural guardrail: explicit contracts, deterministic checks, observable
runs, and incremental delivery.

## Completed in the first building block

- [x] Added a `pyproject.toml` for uv-managed Python 3.12 development.
- [x] Added provider-neutral `Scenario`, `TraceEvent`, `ToolCall`, and
  `AgentResult` Pydantic models.
- [x] Added an `AgentAdapter` protocol so the runner does not depend on RepoPilot.
- [x] Added an in-memory trace sink and a scenario runner that owns run IDs and
  lifecycle events.
- [x] Added deterministic `RepoPilotDemo` behavior using repository content
  supplied by a scenario fixture.
- [x] Added two small version-controlled JSONL smoke scenarios.
- [x] Added initial unit tests for result normalization, trace ordering, and the
  dataset shape.
- [x] Added a README with reproducible local commands and explicit limitations.

## Completed in the second building block

- [x] Added a deterministic permission policy: low-risk actions run
  automatically; medium/high-risk actions require approval.
- [x] Added typed tool definitions and a registry with Pydantic input/output
  validation and structured execution errors.
- [x] Routed `RepoPilotDemo` through the typed low-risk `repo_search` tool.
- [x] Added a starter evaluator for execution status, required tools, forbidden
  tools, maximum steps, and expected answer terms.
- [x] Added unit tests for permission decisions, tool validation, and evaluator
  behavior.

## Completed in the third building block

- [x] Added FastAPI application construction with dependency-injected run
  service state.
- [x] Added `GET /health`.
- [x] Added `POST /runs` to execute a typed scenario through the existing
  runner and RepoPilot demo agent.
- [x] Added `GET /runs/{run_id}` for in-memory result retrieval.
- [x] Added API integration tests for health, execution, retrieval, and 404
  behavior.
- [x] Added FastAPI and HTTP test-client dependencies through uv.

## Completed in the fourth building block

- [x] Added explicit `ApprovalRequest` and `ApprovalStatus` domain models.
- [x] Added an in-memory approval store with pending, approved, and rejected
  transitions.
- [x] Added a typed `ApprovalRequired` tool failure for policy-blocked actions.
- [x] Added a `permission.checked` trace event to the RepoPilot execution path.
- [x] Added unit coverage for approval state and trace ordering.
- [x] Updated the README to describe the implemented architecture and limits.

## Completed in the fifth building block

- [x] Expanded the RepoPilot golden dataset from two to ten deterministic
  scenarios.
- [x] Added standard, edge-case, documentation, and safety scenario tags.
- [x] Added a reusable deterministic evaluation-suite runner.
- [x] Added a scorecard with total cases, passed cases, failed case IDs, and
  task success rate.
- [x] Added the `uv run arl eval` command and JSON output mode.
- [x] Added integration coverage for the complete ten-case suite and CLI.

## Completed in the sixth building block

- [x] Added a typed failure taxonomy based on the playbook categories.
- [x] Added evidence-linked `FailureReport` objects to failed evaluations.
- [x] Added likely-fix guidance and regression-candidate marking.
- [x] Added failure-category counts to the suite scorecard and CLI output.
- [x] Added a regression test proving retrieval failures include trace evidence.

## Completed in the seventh building block

- [x] Added `ReplayCase` for frozen scenario and observable expectations.
- [x] Added `ReplayRunner` to freeze and replay deterministic runs.
- [x] Added replay comparison for status, answer, tools, trace events, and
  evaluation outcome.
- [x] Added unit coverage for successful replay.

## Completed in the eighth building block

- [x] Added version-controlled quality-gate configuration.
- [x] Added deterministic task-success and permission-failure gates.
- [x] Added quality-gate results and violations to CLI output.
- [x] Made `arl eval` return a failing exit code when the gate fails.
- [x] Added a regression test proving permission failures block release.

## Completed in the ninth building block

- [x] Added JSON serialization for frozen replay cases.
- [x] Added replay artifact loading and saving.
- [x] Added `arl replay create` for freezing a scenario baseline.
- [x] Added `arl replay run` for replaying a saved case.
- [x] Added round-trip and CLI integration tests.

## Completed in the tenth building block: execution and API hardening

- [x] Added harness-owned tool evidence and agent inputs without grader labels.
- [x] Added supervised worker deadlines and parent-owned step budgets.
- [x] Added authenticated, owner-scoped API access and bounded in-memory retention.
- [x] Added request, fixture, output, and concurrency limits.
- [x] Made approval records immutable and transitions atomic.
- [x] Added exact search assertions and medium/high-risk negative controls.
- [x] Added replay schema v2 with normalized execution evidence and safe exports.
- [x] Added regression tests for the 15 branch-review findings.

See REVIEW_FIXES_2026-09-22.md for the detailed changes.

## Completed in the eleventh building block: comparison and automation

- [x] Added compact versioned evaluation snapshots with explicit agent labels.
- [x] Added dataset/scenario/fixture fingerprints and evaluator version matching.
- [x] Added per-case regressions, improvements, unchanged outcomes, and rate deltas.
- [x] Added a regression tolerance (default zero); improvements cannot offset regressions.
- [x] Applied the existing absolute task-success and safety gates to candidates.
- [x] Added atomic snapshot creation that refuses to overwrite a baseline.
- [x] Added snapshot creation and comparison CLI commands.
- [x] Added unit and integration tests, including a real incorrect-query candidate.
- [x] Added a deterministic RepoPilot baseline artifact for CI comparison.
- [x] Added a GitHub Actions workflow for Linux and Windows with retained reports.
- [x] Reconciled the README, guide, architecture, reference, and playbook checklists.

The refined workflow passed on GitHub; branch protection is not verified.
Version labels describe the evaluated checkout; they do not
select or load another agent. Snapshot comparisons are outcome comparisons,
while replay remains the detailed trajectory comparison mechanism.

## Historical batch notes

The active ordered backlog and its acceptance criteria are maintained in
[TODO.md](TODO.md). The dated implementation notes below describe earlier
checkpoints and should not override the current status at the top of this file.

## Model gateway batch implemented (2026-09-26)

- Added strict provider-neutral model requests/responses, provider configuration,
  and parent-owned model-call evidence without raw prompt or response text.
- Added supervised model execution with scenario deadlines, per-run model-call and
  token limits, and a gateway-wide suite cost ceiling reserved before dispatch.
- Added scripted `FakeProvider` and model-backed `RepoPilotModel`; model requests
  reuse the tool registry, permission policy, and scenario step limit.
- Bound conversation history and task-owned search fixtures; script ordinals are
  assigned by the gateway and remain stable when context is trimmed.
- Added deterministic coverage for the same ten golden cases, schema violations,
  model/tool limits, denial, usage accounting, failures, timeout, maximum search
  output, corrupted evidence, and script sequencing after context trimming.
- Independent code review found context handling and script-indexing issues;
  both were fixed and the affected cases verified.

Validation:

```text
uv run --locked pytest tests/unit/test_model_gateway.py -q       13 passed (initial focused checks)
uv run --locked pytest -q                                       114 passed, 3 skipped, 2 dependency warnings
uv run --locked pytest tests/unit/test_model_gateway.py -q -k 'ordinal or model_tool_answer or budget_includes'
                                                               4 passed after final review fix
uv run --locked ruff check .                                    passed after final fix
uv run --locked mypy src                                        passed, 38 source files
uv run --locked arl eval                                        passed, 10/10 and quality gate
uv run --locked arl replay run --case evals/replays/search-001.json passed
uv build                                                       passed
```

The full suite preceded the last small script-ordinal fix; only affected model
cases and static checks were repeated afterward. PostgreSQL tests were skipped
because no disposable database was configured; this batch did not change storage.
Live provider integration, actual billed costs, and live evaluation remain
unverified. CLI/API defaults remain the deterministic agent. See
LLM_EVALUATION_ROADMAP.md for configuration and an example.

## Timing evidence added (2026-09-26)

- Parent-observed monotonic durations now cover total runs, agent startup, tool
  requests, and tool startup in milliseconds.
- The suite scorecard reports nearest-rank p50/p95 distributions and missing
  measurement counts. A versioned synthetic fixture verifies aggregation.
- No latency gate has been added; an accepted baseline is still required.

Validation after the timing change:

```text
uv run --locked pytest                         97 passed with disposable PostgreSQL enabled
uv run --locked ruff check .                  passed
uv run --locked mypy src                     passed (35 source files)
uv run --locked arl eval --snapshot reports/timing-candidate.json --agent-version timing-v1   passed, 10/10
uv run --locked arl compare --baseline evals/baselines/repopilot.json --candidate reports/timing-candidate.json   passed, no regressions
uv run --locked arl replay run --case evals/replays/search-001.json --json   passed
uv build                                     passed
```

## Durable evidence batch in progress (2026-09-26)

- Added a storage-neutral `RunRepository` protocol and `StoredRun` evidence model.
- Added a PostgreSQL repository with transactional run/evaluation/trace writes,
  explicit versioned SQL migration, owner-scoped reads, expiry, and retention.
- The API now supports optional `ARL_DATABASE_URL` and evaluation retrieval.
- Added a CLI migration command and disposable-PostgreSQL CI integration job.
- A disposable local PostgreSQL 18 cluster passed migration, restart, ownership,
  retention, and failure tests. Hosted CI passed; branch settings remain unverified.

The local batch acceptance criterion and hosted CI are verified. Required checks
remain optional and unverified.

Validation run for this batch on Windows:

```text
uv run --locked pytest                         92 passed with PostgreSQL enabled, 2 dependency warnings
uv run --locked ruff check .                  passed
uv run --locked mypy src                     passed (34 source files)
uv run --locked arl eval                     passed (10/10 cases, quality gate passed)
uv run --locked arl replay run --case evals/replays/search-001.json --json   passed
uv build                                     passed; SQL migration present in sdist and wheel
uv run --locked arl db migrate                passed against disposable PostgreSQL 18
```

See [TODO.md](TODO.md) for acceptance criteria and the full ordered checklist.

- [x] Observe a successful GitHub Actions run.
- [ ] Configure required checks if branch protection is desired.
- [x] Define a repository interface for durable run evidence.
- [x] Add PostgreSQL storage, migrations, and restart/ownership integration tests.
- [x] Record run/tool durations and suite latency statistics before adding gates.
- [x] Add a provider-neutral model gateway with fake-provider tests and usage accounting.
- [x] Add opt-in live-model evaluations with suite cost limits and baseline comparison.
- [ ] Bind approvals to exact actions, reviewer identity, expiry, and audit events.
- [ ] Add persisted checkpoints and API approval/resume integration tests.
- [ ] Expand security/recovery scenarios and add trace/release review views.

## Deliberately not implemented yet

- No verified live request or billing result; OpenAI integration and provider-neutral gateway are implemented.
- No SQLAlchemy or Alembic; durable trace storage uses direct PostgreSQL queries.
- No API approval pause/resume; approving a record does not execute an action.
- No measured cost/latency release gates or OpenTelemetry exporter.
- No Docker, Redis, MCP, frontend, or multi-agent runtime.
- No automated baseline promotion or human candidate-release approval product.

## Verification

Standard commands:

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
uv run arl eval
uv run arl replay run --case evals/replays/search-001.json --json
uv build
```

## OpenAI live evaluation batch (2026-09-26)

- Added an optional OpenAI SDK extra and a Responses API adapter with input-token
  preflight, one strict `repo_search` function, output-token limits, no SDK
  retries, and `store=False`.
- Added the explicit `arl live-eval` command. It requires an API key from the
  environment, operator-supplied prices, a suite-wide cost ceiling, and a new
  output path. It validates the baseline/dataset before calling the provider.
- The report contains sanitized scorecards, usage, cost estimates, per-success
  cost, versioned candidate evidence, quality-gate results, and baseline
  comparison. Existing reports cannot be overwritten.
- The command and real billing were not run against OpenAI. No API calls were
  made by tests or CI.

Validation:

```text
uv run --locked pytest -q                           118 passed, 3 skipped, 3 provider-stub failures
uv run --locked pytest tests/unit/test_openai_provider.py -q 5 passed after fixing the stub
uv run --locked ruff check .                        passed
uv run --locked mypy src                            passed (41 source files)
uv build                                            passed
```

The full test suite was not repeated after the test-only stub fix; the five
affected provider tests passed. PostgreSQL integration tests were skipped at
that checkpoint. A later explicitly authorized live run verified account and
model access. One case timed out and had unknown usage; see the current status
at the top of this file for its measured result and limitations.

Pre-batch baseline on 2026-09-26: **63 tests passed**, with two existing dependency
deprecation warnings. Post-batch verification is recorded after the final checks.

# Agent Reliability Lab — Current Status and Next Work

Updated: 2026-09-26

## Current position

The lab has a bounded scenario runner, typed tool boundary, permissions,
traces, deterministic graders, replay, snapshots, PostgreSQL evidence storage,
a provider-neutral model gateway, and opt-in OpenAI evaluation. Its CLI/API
still default to RepoPilot; it is not a production agent runtime or a security
certification system.

Two separate Python examples demonstrate the adapter path:

- `examples/external_calculator/`: application-owned agent and typed tool,
  three scenarios, baseline comparison.
- `examples/refund_support/`: synthetic customer support workflow with
  preview-only refund behavior, normal and adversarial cases, and a security
  quality gate.

The refund example passes four cases, including direct user-content and
indirect tool-response prompt injection. An intentionally unsafe control leaks
synthetic canaries and requests a high-risk refund action; the grader rejects
it while policy prevents the action handler from executing. This validates
the observable scoring path for the example. It does not yet measure an actual
user-owned agent or prove stochastic LLM resistance.

A separate live `gpt-4.1-mini` run against the bundled RepoPilot suite completed
9/10 cases. One timed out, so the zero-regression comparison failed. Known
estimated cost was $0.001726; one timed-out call had unknown usage. This is one
measurement, not a stable baseline or an exact invoice.

## Security capabilities and limits

Implemented checks include schema-valid arguments, registered tool names,
permission decisions, exact expected tool-call sequences/arguments/outcomes,
prohibited tool-request detection, canary absence from final answers and tool
arguments, step/time limits, and trace consistency. `QualityGate` has a
zero-tolerance security-violation rate by default. Reports distinguish an
agent's prohibited request from the harness blocking dispatch.

The refund suite tests direct and indirect injection only against the included
deterministic sample agent and a scripted unsafe negative control. It is not a
framework adapter for an agent built by the user, not a live-model red-team
suite, and not a guarantee about internal reasoning. The `issue_refund` tool is
a sentinel whose handler always fails if policy ever dispatches it; previews
are synthetic and never change payment state.

## Next implementation batches

### 1. Connect and evaluate one user-owned agent

- [ ] Select one actual agent and document its runtime, model/prompt version,
  available tools, and possible side effects.
- [ ] Write a thin adapter and typed registry that routes every action through
  harness validation and policy.
- [ ] Reuse the support suite where applicable; add scenarios for that agent's
  real workflow and threat model.
- [ ] Verify on safe and intentionally vulnerable controls that expected
  answers, exact tool arguments/outcomes, canary checks, and prohibited tool
  requests fail or pass as intended.
- [ ] Keep live-provider runs opt-in, repeatable, and cost-bounded; record
  model/prompt/data versions with each report.

Acceptance: one independently maintained agent can be evaluated on reviewed
tasks; a deliberately unsafe candidate fails the security gate, and traces
show the request and the separate policy decision.

### 2. Compare the four agents fairly

- [ ] Add adapters for the other agents only after the first real integration
  works end to end.
- [ ] Run each on the same scenarios, fixtures, permissions, and evaluator
  version; keep agent-specific tool expectations explicit.
- [ ] Report per-agent task success, security violations, tool selection and
  arguments, failures, latency, and known model usage/cost.
- [ ] Repeat live-model cases before interpreting small differences.

Acceptance: snapshots use matching dataset/evaluator identities and security
failures cannot be offset by answer quality or aggregate success rate.

### 3. Measure before adding more release gates

- [ ] Collect repeated success, latency, and usage measurements for fixed
  model/prompt/dataset versions.
- [ ] Set cost and latency thresholds only when evidence and product needs
  support them.
- [ ] Keep security violations at zero unless a human-reviewed policy defines
  a specific exception; never auto-promote baselines.

## Later playbook work

- [ ] Add exact-action human approval, reviewer identity, expiry, audit
  history, persisted checkpoints, and pause/resume tests if an agent workflow
  needs actions to continue after approval.
- [ ] Add a trace/release review UI when CLI artifacts no longer support review.
- [ ] Add OpenTelemetry when traces must flow across service boundaries.
- [ ] Add deployment packaging when a reproducible hosted service is needed.

LangGraph, SQLAlchemy/Alembic, queues, MCP, and multi-agent orchestration are
not prerequisites. Add them only for a demonstrated integration or product
requirement.

## Playbook cross-reference

- Sections 2 and 8: synthetic support environment, injection fixtures, exact
  graders, and permission assertions.
- Sections 9 and 10: evidence-linked failures and replayable regressions.
- Section 11: release review remains separate from runtime approval/resume.
- Days 4, 5, 7, and 9: graders, security failure classification, gates, and
  attack/recovery coverage.
- Section 13: show an unsafe failure, a fix, a regression test, and a blocked
  release.
- Section 14: measure cost and latency before setting thresholds.

## Verification record

The current security batch has two passing refund-support integration tests,
passing Ruff and `mypy src`, and a 4/4 local example run with a passing baseline
comparison. The full test run reported 127 passed, 3 PostgreSQL tests skipped,
and one stale evaluator-version test assertion; the updated comparison tests
then passed 20/20. The full suite has not been rerun after that test correction.
Do not claim a live-model security run or evaluation of a user-owned agent;
neither has happened.

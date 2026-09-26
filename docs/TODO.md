# Agent Reliability Lab — Current Status and Next Work

Updated: 2026-09-26

## Current position

The project has a deterministic runner, typed tool boundary, permission checks,
traces, deterministic graders, replay, quality gates, snapshots, PostgreSQL
evidence storage, a provider-neutral model gateway, and an opt-in OpenAI
evaluation command. It is still an evaluation lab, not a production agent
runtime or a security certification system.

An external-agent integration example now demonstrates the Python adapter
path using an application-owned calculator agent and tool. Its three scenarios
passed and matched its saved baseline. This proves the integration shape; it
does not evaluate any of the user's own agents. The CLI and API still default
to RepoPilot.

A live `gpt-4.1-mini` run against the bundled RepoPilot smoke suite completed
9/10 cases. One case timed out, so the zero-regression comparison failed. Known
estimated cost was $0.001726; one timed-out call had unknown usage. This is one
measurement, not a stable baseline or an exact invoice.

## Security: what exists and what is missing

The harness currently enforces tool argument schemas, tool registration,
permission policy, step/time bounds, and trace-linked outcomes. Integration
tests verify malformed arguments, unknown tools, an approval-required tool,
and tool-handler errors. These controls constrain actions that pass through the
harness.

There is not yet a prompt-injection evaluation suite. The RepoPilot model prompt
labels fixture content as untrusted, but that instruction has not been tested
against adversarial content. The harness can grade observable behavior—answers,
tool requests, permission decisions, and traces—but cannot inspect or certify an
agent's internal reasoning. Approval-required actions are blocked; there is no
complete human review, pause, and resume workflow.

## Next implementation batches

### 1. Evaluate one real external agent, including its security boundary

- [ ] Choose one of the user's actual agents and document its invocation,
  tools, model/prompt version, and side effects.
- [ ] Write an adapter and typed tool registry for that agent; keep all actions
  behind harness validation and permission checks.
- [ ] Create a small, reviewed scenario set for its real tasks, including
  benign controls and direct and indirect prompt-injection attempts.
- [ ] Put an unmistakable canary secret and malicious instructions in
  untrusted user/retrieved/tool content. Assert that the agent answers the
  trusted task, does not reveal the canary, and does not request forbidden or
  approval-required actions.
- [ ] Add harmless sentinel tools to prove blocked actions have no side effect.
- [ ] Add negative-control agents/fixtures that intentionally follow the
  injection; verify the grader fails them. This demonstrates that the security
  cases can catch a regression.
- [ ] Preserve per-case traces, failure evidence, model/prompt identity, and
  baseline comparison. Keep live-provider tests opt-in and cost-bounded.

Acceptance: the same reviewed cases run through the external adapter; expected
safe behavior passes; injection-following and forbidden-action controls fail;
no blocked handler executes; reports identify the failed case and relevant
trace evidence.

### 2. Make security assertions precise and reusable

- [ ] Add scenario assertions for exact tool-call sequence, selected argument
  values, expected tool outcomes/errors, and sensitive canary absence where
  needed. Keep schema validation and permission decisions deterministic.
- [ ] Cover malformed/extra arguments, unknown tools, forbidden tools,
  approval-required tools, tool errors, retries/duplicates, and recovery.
- [ ] Separate agent-policy failures from harness-policy enforcement in the
  scorecard: a denied action is safe enforcement, while an agent attempting a
  forbidden action may still be a candidate behavior failure.
- [ ] Review failure categories and replay artifacts for useful security
  evidence without storing raw secrets or unnecessary private content.

Acceptance: deliberately unsafe or malformed trajectories fail the relevant
agent-behavior check, while the trace separately proves the harness blocked
execution. Safe controls remain passing.

### 3. Compare the four agents fairly

- [ ] Add an adapter for each agent only after the first integration contract
  works end to end.
- [ ] Run each against the same scenarios, fixture versions, permission
  controls, and evaluator version.
- [ ] Report task success, security violations, tool names/arguments/outcomes,
  failures, latency, and known model usage/cost per agent.
- [ ] Repeat live-model cases enough to show variability before interpreting
  small score differences.

Acceptance: comparison artifacts identify all agent and dataset versions;
security violations cannot be offset by answer quality or average scores.

### 4. Set release gates from evidence

- [ ] Collect repeated success, latency, and usage measurements for fixed
  model/prompt/dataset versions.
- [ ] Set cost and latency thresholds only after measurements and product
  requirements justify them.
- [ ] Keep zero-tolerance gates for critical safety failures unless a reviewed
  policy explicitly says otherwise.
- [ ] Require a human to review grader/threshold changes and baseline
  promotion; do not promote baselines automatically.

## Later playbook work

- [ ] Implement a real approval workflow bound to an exact action, reviewer,
  expiry, and audit history; add persisted checkpoints and safe resume tests.
- [ ] Add trace/release review UI when CLI reports no longer support review.
- [ ] Add OpenTelemetry export when traces need to cross service boundaries.
- [ ] Add deployment packaging when a reproducible hosted service is required.

LangGraph, SQLAlchemy/Alembic, queues, and multi-agent orchestration are not
prerequisites for the next security/evaluation batch. Introduce them only for a
demonstrated integration or product requirement.

## Playbook cross-reference

- Sections 2 and 8: synthetic environments, injection fixtures, deterministic
  graders, and permission assertions.
- Sections 9 and 10: failure taxonomy, evidence-linked failures, and replay as
  regression protection.
- Section 11: candidate/release human review; the runtime approval workflow is
  a separate unfinished capability.
- Days 4, 5, 7, and 9: graders, security failure classification, quality gates,
  and attack/recovery scenarios.
- Section 13: demonstrate a failure, fix, regression check, and release gate.
- Section 14: cost/latency gates only after measured baselines.

## Completion and verification notes

Update BUILD_STATUS.md after each implementation batch. Record only commands
actually run and distinguish focused tests from full-suite validation. Current
external-agent example verification: five focused integration tests passed;
Ruff and `mypy src` passed; the documented local example reported 3/3 cases and
a passing baseline comparison. Current OpenAI live-run limitations are listed
above and in LLM_EVALUATION_ROADMAP.md.

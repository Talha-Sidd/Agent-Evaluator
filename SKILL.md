---

name: agent-reliability-engineering
description: Use when implementing, reviewing, debugging, testing, or extending AI-agent infrastructure such as runners, tools, permission policies, traces, evaluators, model gateways, checkpoints, replay, quality gates, or orchestration.
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# Agent Reliability Engineering

Use this workflow for agent-related implementation and review work.

## 1. Understand the requested change

Before editing code, identify:

* what behavior is requested;
* what existing behavior must remain unchanged;
* which component owns the responsibility;
* whether the change affects safety, evaluation, or observability.

Do not immediately start coding from the task description alone.

Inspect the relevant implementation and tests first.

---

## 2. Locate the owning layer

Classify the work into one or more layers:

```text
Scenario
ScenarioRunner
AgentAdapter
Agent
ModelGateway
TypedToolRegistry
PermissionPolicy
Tool
Trace
Persistence
Checkpoint
Evaluator
QualityGate
Replay
```

Avoid putting behavior in a convenient layer if another layer logically owns it.

Examples:

```text
run IDs              → runner
permissions          → permission policy
tool validation      → tool boundary
provider API calls   → model gateway
scoring              → evaluator
storage              → persistence
```

---

## 3. Identify the invariant

Before implementation, state what must remain true.

Examples:

```text
Agents cannot grant themselves permission.

Tool arguments are validated before execution.

The runner owns run lifecycle.

Provider SDK types do not leak into domain models.

Evaluators do not modify agent behavior.

Trace storage does not define trace semantics.
```

Use the invariant to guide both code and tests.

---

## 4. Decide what should be deterministic

Ask:

> Can ordinary code decide or verify this exactly?

If yes, implement it deterministically.

Typical deterministic responsibilities:

* permissions
* argument validation
* lifecycle transitions
* step limits
* timeout rules
* tool allowlists
* required/forbidden tool checks
* exact expectations
* budgets
* state transitions

Use an LLM only when semantic interpretation is genuinely necessary.

---

## 5. Inspect the trust boundary

For every model-generated action verify that the path looks like:

```text
untrusted model output
        ↓
typed/schema validation
        ↓
permission check
        ↓
bounded execution
        ↓
structured result
```

Never rely on:

* prompt wording
* tool descriptions
* agent reasoning

as the security boundary.

---

## 6. Review tool design

When adding or changing a tool, check:

### Purpose

The tool should have one clear responsibility.

### Scope

Prefer narrow operations over arbitrary execution.

### Inputs

Inputs must be typed and validated.

### Outputs

Outputs should be structured where practical.

### Risk

Assign an appropriate risk level.

### Permission

Ensure the correct policy decision occurs before execution.

### Timeout

Use a timeout or execution budget where relevant.

### Errors

Tool failures should be explicit and structured.

---

## 7. Review permission behavior

Permission decisions must happen outside the model.

Verify that:

```text
agent request
→ policy decision
→ execute / reject / require approval
```

The agent must not be able to override or downgrade the policy.

Test at least:

* allowed action
* denied action
* approval-required action

where applicable.

---

## 8. Review loop behavior

Any agent loop should have explicit termination conditions.

Check:

* maximum steps
* retry count
* timeout
* token limits
* cost limits

A loop reaching a limit should produce an explicit terminal result.

Never leave an uncontrolled:

```python
while True:
    ...
```

around model execution without a bounded exit strategy.

---

## 9. Review observability

For new behavior ask:

* Can we tell that this action happened?
* Can success and failure be distinguished?
* Can permission denial be distinguished from tool failure?
* Can retries be seen?
* Can step-limit termination be identified?
* Is the run ID preserved?
* Is sensitive data excluded?

Add structured trace events where necessary.

Avoid relying only on free-form log text.

---

## 10. Review failure behavior

Determine expected handling for relevant failure cases:

```text
invalid_input
invalid_tool_arguments
tool_not_found
permission_denied
approval_required
timeout
tool_error
model_error
step_limit_exceeded
evaluation_failure
internal_error
```

Do not silently convert failures into:

```text
None
""
[]
success
```

unless that result is explicitly part of the contract.

---

## 11. Review context usage

Check whether the model is receiving more context than necessary.

Prefer:

```text
relevant files
relevant tool results
compact state
targeted retrieval
summaries
```

Avoid automatically passing:

```text
entire repository
entire conversation
entire trace history
all previous tool results
```

Context should serve the task.

---

## 12. Review model/provider boundaries

Provider-specific behavior should sit behind a small interface.

Prefer:

```text
Agent
   ↓
ModelGateway
   ↓
OpenAI / Anthropic / Gemini / Local Model
```

Avoid allowing provider SDK structures to leak into:

* scenarios
* evaluators
* traces
* domain models
* permission policies

unless there is a strong reason.

---

## 13. Review evaluation strategy

Start with exact checks.

Preferred evaluation order:

```text
1. deterministic exact checks
2. structural checks
3. deterministic semantic checks
4. model judge only where necessary
```

Examples of exact checks:

* required tool used
* forbidden tool avoided
* number of steps
* expected string present
* status correct
* schema valid

Do not use an LLM judge for these.

---

## 14. Evaluate the trajectory

Do not evaluate only the final answer.

Where relevant inspect:

* tool sequence
* tool arguments
* permission decisions
* retries
* failures
* step count
* final answer
* latency
* token usage
* cost

A good answer obtained through unsafe behavior should not count as fully successful.

---

## 15. Compare against a baseline

For changes involving:

* prompts
* models
* tool descriptions
* retrieval
* agent loops
* orchestration
* context strategy

compare the candidate against the previous working version using the same scenarios.

Record both:

```text
improvements
regressions
```

Do not replace the baseline because one example looked better.

---

## 16. Avoid unnecessary multi-agent designs

Before adding another agent ask:

1. Can this task be solved cleanly by the existing agent?
2. Is work genuinely parallelizable?
3. Does specialization provide measurable benefit?
4. Does independent verification justify another agent?
5. Does added complexity improve evaluation results?

If not, keep the system single-agent.

---

## 17. Implement the smallest coherent change

Avoid combining unrelated work such as:

```text
new feature
+ refactor
+ dependency migration
+ architecture rewrite
```

unless technically required.

Prefer small changes with clear contracts.

---

## 18. Add tests

For changed behavior consider:

### Happy path

Does the expected behavior work?

### Validation

What happens with malformed input?

### Permission

What happens if access is denied?

### Tool failure

What happens if the handler throws or times out?

### Limits

What happens at or beyond the step/retry boundary?

### Tracing

Are important events present and ordered correctly?

### Regression

Does the discovered bug stay fixed?

Use deterministic fixtures where possible.

---

## 19. Run focused checks first

Run tests directly related to the changed component first.

Then run project-wide checks.

Typical sequence:

```bash
uv run pytest path/to/relevant/tests
uv run pytest
uv run ruff check .
uv run mypy .
```

Use repository-specific commands when available.

Never state that a command passed without executing it.

---

## 20. Review security implications

Before completion check:

* Can agent input escape validation?
* Can policy be bypassed?
* Did a new broad capability appear?
* Can secrets enter logs or traces?
* Can external content become trusted instructions?
* Can model output reach shell/network/database directly?

Fix security-boundary violations before declaring completion.

---

## 21. Review architecture integrity

Verify that the change preserves important boundaries:

```text
runner ≠ agent
agent ≠ permission policy
agent ≠ evaluator
tool registry ≠ permission policy
trace model ≠ storage
domain model ≠ provider SDK
```

Do not remove useful boundaries merely to reduce file count.

---

## 22. Review observability and replay readiness

Ask:

> If this run fails tomorrow, will we know why?

Preserve useful structured information such as:

* run ID
* scenario ID
* agent/model version
* tool actions
* evaluator result
* failure category
* configuration where appropriate

Avoid recording secrets or excessive raw context.

---

## 23. Review dependency additions

Before adding a dependency ask:

* What exact problem does it solve?
* Can existing code solve this clearly?
* Is the dependency justified now?
* Does it add operational complexity?

Do not add:

```text
LangGraph
MCP
Redis
vector database
queue
Docker
Kubernetes
```

solely because similar agent projects use them.

---

## 24. Final reliability review

Before completion verify:

### Correctness

* requested behavior works;
* relevant edge cases are handled.

### Safety

* permissions cannot be bypassed;
* tool arguments are validated;
* broad capabilities are justified.

### Reliability

* loops are bounded;
* failures are explicit;
* behavior is reproducible where appropriate.

### Observability

* important events are traceable;
* failures can be diagnosed.

### Evaluation

* deterministic checks remain deterministic;
* changed behavior has coverage;
* candidate changes are compared to baseline when relevant.

### Maintainability

* responsibilities remain separated;
* provider-specific logic stays contained;
* unnecessary infrastructure was not introduced.

---

## 25. Final response format

When reporting completed work, use:

### Changed

What behavior was added or fixed.

### Why

Why the change belongs in this layer and what invariant it protects.

### Validation

Commands actually run and their results.

### Remaining

Real limitations, deferred work, or unverified behavior.

Never claim production readiness only because unit tests pass.

---

## Core Mental Model

```text
LLM
proposes

Harness
controls execution

Permission policy
decides what is allowed

Tools
perform bounded actions

Trace
records what happened

Evaluator
checks behavior

Tests
prevent regressions

Human
retains authority
```

# Connect your application agent

This folder is an integration starter for an agent owned by another
application. It is deliberately not presented as a real agent: before using it,
replace the adapter, tool definitions, scenarios, and metadata with the actual
agent and reviewed workflow you want to evaluate.

## Integration record

Complete this record in the application repository before running an
evaluation:

| Field | Required value |
|---|---|
| Agent owner/application | Name of the application and responsible team |
| Runtime | Python/framework/version and how the agent is invoked |
| Model | Provider and exact model ID, or `deterministic` |
| Prompt version | Reviewed identifier or content hash |
| Agent version | Immutable commit or release identifier |
| Tools | Name, typed inputs/outputs, risk level, and side effects for each tool |
| Data | Fixture source and whether it is synthetic or approved for evaluation |
| Limits | Run timeout, step limit, model calls/tokens, and cost ceiling if applicable |

Do not run production credentials, customer records, or side-effecting tools in
this starter. Use synthetic data and no-op handlers first. The runner starts
adapters and tool handlers in worker processes for lifecycle control; this is
not an OS security sandbox.

## Adapter contract

Implement `AgentAdapter.run(task, run_id, tools) -> AgentResult`. The agent must
request every action through the supplied `tools` executor. Do not give it a
second direct path to tools. Keep its implementation importable at module scope
so Python multiprocessing `spawn` can load it.

```python
from uuid import UUID

from agent_reliability_lab.domain.models import AgentResult, AgentTask
from agent_reliability_lab.domain.protocols import ToolExecutor


class MyApplicationAdapter:
    name = "my-app-agent-v1"

    def run(self, task: AgentTask, run_id: UUID, tools: ToolExecutor) -> AgentResult:
        # Translate task into the actual agent's invocation.
        # Configure that agent to call only tools exposed through `tools`.
        # Return an AgentResult; the harness replaces adapter-reported tool
        # calls/traces with its own observed records.
        raise NotImplementedError("connect the application-owned agent here")
```

If the agent uses an LLM, mediate requests through the harness `ModelExecutor`
and provider-neutral `ModelGateway` rather than hiding direct provider calls in
the adapter. Keep live calls opt-in and enforce per-run and suite-wide budgets.

## Application-owned tools

Define each tool with Pydantic input/output models and register it in a
`TypedToolRegistry`. Assign risk deliberately. High/medium risk requests will
be blocked pending approval; approval/resume execution is not implemented yet.
Initially use read-only or synthetic handlers. Replace example schemas and
handlers with the application-specific ones only after reviewing side effects.

## Reviewed scenarios

Create a JSONL dataset in the application repository. Include normal and edge
cases, direct and indirect untrusted-content attacks where relevant, exact tool
arguments/outcomes, prohibited tool requests, and canary checks. Scenario
expectations are grader data and are not passed to the agent. Keep attack text
and expected outcomes reviewed by the application owner.

## Run from the repository root

After the adapter, registry, and scenario file exist:

```python
from pathlib import Path

from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.runner.runner import ScenarioRunner

suite = EvaluationSuite(
    agent=MyApplicationAdapter(),
    runner=ScenarioRunner(registry=my_application_registry()),
)
scenarios = suite.load_jsonl(Path("evals/my_agent_cases.jsonl"))
scorecard = suite.run(scenarios, "my-agent-v1")
```

Then use `create_snapshot` and `compare_snapshots` as in
`examples/external_calculator/evaluate.py`. Preserve agent, model, prompt,
dataset, and evaluator versions alongside the report. Run a deliberately unsafe
control and verify it fails while the trace shows policy blocked dispatch.

## Completion checklist

- [ ] This is an independently maintained agent, not a lab demo adapter.
- [ ] Runtime, model/prompt versions, tools, data, and side effects are recorded.
- [ ] All tool calls are routed through the harness registry and policy.
- [ ] Scenarios represent a reviewed real workflow and threat model.
- [ ] Safe agent passes the task and exact-trajectory checks.
- [ ] Unsafe control fails the security gate; prohibited dispatch is blocked.
- [ ] Live-model use is opt-in, repeatable, and cost-bounded if applicable.
- [ ] Candidate is compared against a reviewed baseline using identical inputs.

Until the checklist is filled using an actual application agent, results from
the bundled deterministic examples must not be described as evaluation of a
user-owned agent or proof of live-model security.

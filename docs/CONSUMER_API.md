# Simple Python API for evaluating an agent

Install Agent Reliability Lab in the application repository, implement the
`AgentAdapter` contract, and call the top-level `evaluate` helper. The app and
its scenarios stay in the consumer's repository; the lab package does not need
to be edited.

```python
from pathlib import Path

from agent_reliability_lab import evaluate
from my_agent.arl_adapter import MyAgent

report = evaluate(
    agent=MyAgent(),
    scenarios=Path("evals/my_agent_cases.jsonl"),
)

print(report.summary())
for case in report.cases:
    print(case.evaluation.scenario_id, case.evaluation.passed)
    print("answer:", case.result.final_answer)
    print("tools:", [call.name for call in case.result.tool_calls])
```

`report.summary()` returns:

- suite name, passed/total cases, and task success rate;
- failure counts by category;
- observed run latency p50/p95;
- observed tool and model call counts;
- estimated model cost from usage recorded by the configured model gateway.

Each item in `report.cases` retains the complete structured result and
evaluation: final answer, pass/fail checks, failure reports, tool arguments and
outcomes, permission decisions, trace events, timing, and model usage/errors.
Review those records when a case fails; the aggregate score alone is not a
diagnosis.

## Answer-only integration

If the agent is exposed only as a callable or black-box service, omit `tools`.
The harness can evaluate the returned answer against scenario expectations,
record run success/failure and timing, and compare repeated cases. It cannot
verify hidden tool calls, their arguments, or whether a hidden action was
permitted. Black-box service calls also do not run through the harness worker
boundary unless the adapter itself is safe and compatible with that boundary.

Example scenario:

```jsonl
{"scenario_id":"missing-order-id","task":"Can I get a refund?","expected_behavior":"Ask for an order ID; do not guess.","expected_terms":["order ID"],"expected_tools":[],"timeout_seconds":10}
```

Expected terms are exact substring checks, not semantic grading. Add reviewed
cases for correct outcomes, boundary behavior, errors, and relevant attacks.
The lab cannot infer a team's business rules from the agent implementation.

## Tool-mediated integration

To check tool use and permissions, pass an application-owned
`TypedToolRegistry`. Configure the agent adapter so every tool request is sent
through the provided `ToolExecutor`:

```python
from pathlib import Path

from agent_reliability_lab import evaluate
from my_agent.arl_adapter import MyAgent
from my_agent.evaluation_tools import build_registry

report = evaluate(
    agent=MyAgent(),
    scenarios=Path("evals/my_agent_cases.jsonl"),
    tools=build_registry(),
    suite_name="orders-agent-prompt-v3",
)
```

The tool registry supplies typed schemas, handlers, and risk levels. Then the
harness can check requested tool names, arguments, outputs, permission
decisions, blocked dispatch, and execution outcomes. The agent must not have a
second direct route to those tools. Use synthetic fixtures and harmless
handlers first. Medium/high-risk actions are blocked pending approval; approval
and resume execution are not yet implemented.

## Live model evaluation

If the adapter requests models through the lab's provider-neutral
`ModelExecutor`, pass a configured `ModelGateway` as `model_gateway`. Keep
provider setup opt-in and configure per-run and suite cost/token/time limits.
The summary cost is an estimate based on operator-supplied token prices and
provider-reported usage, not an invoice. Direct model calls hidden inside an
adapter are not included in model-call evidence.

## What this API does not decide

The consumer supplies reviewed scenarios and defines what success, unsafe
behavior, and permitted actions mean. Exact assertions can be checked
deterministically. The API does not provide automatic scenario discovery,
semantic grading of arbitrary answers, integration with every agent framework,
or a remote upload/evaluation service. It is a simpler entry point to the
existing Python harness, not a replacement for an adapter or test design.

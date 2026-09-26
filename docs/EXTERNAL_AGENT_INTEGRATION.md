# Integrate an agent built outside this project

The harness accepts application agents through the `AgentAdapter` protocol.
An adapter implements `run(task, run_id, tools)` and returns an `AgentResult`.
The runner supplies the scenario task and a restricted tool proxy; tool requests
go through schema validation, permission policy, execution limits, and trace
recording.

The runnable example in `examples/external_calculator/` is separate from the
built-in RepoPilot agent. It has an application-owned deterministic agent, its
own typed `calculate` tool, a four-case scenario suite, and a saved baseline.
The fourth case contains a hostile instruction to perform a protected action.
The evaluation command also runs an unsafe negative control that requests that
action. The expected outcome is a failed scenario evaluation while policy
blocks the handler. The command fails if the safe suite regresses or the unsafe
control is not rejected and blocked. This is an integration and harness-control
check, not a live LLM security evaluation.

Run it from the repository root:

```powershell
uv run --locked python -m examples.external_calculator.evaluate
```

The output includes per-case pass/fail, passed check counts, tool names,
durations, overall success rate, baseline comparison, unsafe-control result,
and regressions. Add
`--json` for machine-readable output. To save a candidate snapshot for review,
choose a new path:

```powershell
uv run --locked python -m examples.external_calculator.evaluate `
  --agent-version external-calculator-v2 `
  --snapshot reports/external-calculator-v2.json
```

Snapshots do not contain task text, fixture contents, final answers, or raw
tool arguments, and snapshot creation never overwrites an existing file. The
committed baseline is `examples/external_calculator/baseline-starter-v3.json`.

Integration tests also send malformed arguments, an unknown tool, an
approval-required tool, and a tool handler error through the runner. They
assert structured errors and verify blocked handlers do not execute.
The security negative-control integration test additionally verifies that the
unsafe agent's prohibited request appears in the trace and that its handler
was not executed.

## Adapting your own agent

For a detailed integration record and a fill-in completion checklist, start
with [`examples/user_agent/README.md`](../examples/user_agent/README.md). It
requires the actual runtime, model/prompt version, tools, side effects, and
workflow scenarios to be documented before calling the integration a real
user-owned-agent evaluation.

1. Write a wrapper in your agent's application package that implements
   `AgentAdapter`.
2. Convert the harness `AgentTask` into the input your agent expects.
3. Register the agent's tools with `ToolDefinition` and a
   `TypedToolRegistry`. Keep tool schemas and handlers in the application
   package, and choose risk levels deliberately.
4. Pass the adapter and `ScenarioRunner(registry=...)` to `EvaluationSuite`.
5. Run the same scenarios and fixtures for each candidate, then compare its
   snapshot with the reviewed baseline.

```python
suite = EvaluationSuite(
    agent=MyAgentAdapter(),
    runner=ScenarioRunner(registry=my_application_tool_registry()),
)
scenarios = suite.load_jsonl(Path("evals/my_agent_cases.jsonl"))
scorecard = suite.run(scenarios, "my-agent")
```

An adapter must be importable and pickleable because the runner starts it in a
supervised Python worker process. This lifecycle boundary is not an OS sandbox.
The integration is a Python API, not an auto-loader for arbitrary frameworks.
LangGraph, LangChain, hosted HTTP agents, and other runtimes need a small
adapter for their invocation and tool model. The CLI and API still default to
RepoPilot; this example shows how to evaluate another agent from Python
without changing the core package.

For adversarial examples and security-check semantics, see
[SECURITY_EVALUATION.md](SECURITY_EVALUATION.md).

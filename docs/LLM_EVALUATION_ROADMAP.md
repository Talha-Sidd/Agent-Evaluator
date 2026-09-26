# Real LLM evaluation roadmap

The project moves from deterministic harness checks to live-model evaluation in
small, measurable steps. A live provider call is not required for ordinary unit
tests or pull-request CI.

## Stage 1: model boundary and fake-provider coverage

Implemented: `domain/model_gateway.py` defines strict provider-neutral contracts;
`platform/model_gateway.py` owns supervised provider execution; `RepoPilotModel`
requests models and tools through the runner. `FakeProvider` supplies scripted
responses for deterministic tests. Run evidence records model/prompt identity,
token usage, configured input/output prices, estimated USD cost, duration in
milliseconds, hashes, and typed failures. Raw model prompts and responses are
excluded from model-call evidence. Evidence survives adapter failures and cannot
be replaced by adapter-authored records.

- Add a provider-neutral model gateway; provider SDK types stay behind its
  adapter boundary.
- Add a bounded model-backed RepoPilot adapter that uses the existing tool
  registry, permission policy, and run limits.
- Test the gateway and adapter with a deterministic fake provider.
- Record provider/model identity, prompt version, input/output tokens, estimated
  cost, latency, and typed failure outcomes in run evidence.

**Exit criteria:** gateway and adapter tests are deterministic; malformed model
tool requests pass through existing schema and permission checks; time, step,
and cost limits stop execution with observable outcomes.

The harness reserves the maximum input/output token allowance and its estimated
cost before each dispatch, adding usage from earlier successful calls. A failure
with unknown usage stops the run; missing usage is not reported as zero cost.
Provider adapters must enforce input/output caps before making billable calls.
Returned usage is validated again by the harness. Prices are explicit configured
USD amounts per million tokens, not automatically fetched vendor prices.
These local controls do not guarantee remote cancellation or exact billed cost.
The gateway assigns each request a call ordinal; scripted fake responses use it
so trimming conversation history does not change the response sequence.

The model receives the task and tool results, never evaluator expectations. The
adapter binds `repo_search` to the task's repository fixture, excludes that corpus
from conversation history, and keeps the initial task plus the newest complete
turns within a 128 KiB context limit. Models cannot alter the trusted system prompt
or choose the model, prices, or run budgets. Model calls have a separate call limit;
tool requests retain the scenario's step limit and permission checks. Requests
and provider execution share the scenario deadline. No retries are automatic.

### Try the fake provider

Save this as a Python file and run it with `uv run python path/to/file.py`.
The `__main__` guard is required for the supervised worker processes on Windows.

```python
from agent_reliability_lab.agents.repopilot.model import (
    REPOPILOT_PROMPT_VERSION, REPOPILOT_SYSTEM_PROMPT, RepoPilotModel,
)
from agent_reliability_lab.domain.model_gateway import ModelConfig, ModelResponse, ModelToolRequest
from agent_reliability_lab.domain.models import Scenario
from agent_reliability_lab.platform.evals.suite import EvaluationSuite
from agent_reliability_lab.platform.model_gateway import FakeProvider, ModelGateway
from agent_reliability_lab.platform.runner.runner import ScenarioRunner


def main():
    config = ModelConfig(
        provider="fake", model="scripted-v1", prompt_version=REPOPILOT_PROMPT_VERSION,
        system_prompt=REPOPILOT_SYSTEM_PROMPT,
        input_usd_per_million=1.0, output_usd_per_million=2.0,
    )
    provider = FakeProvider((
        ModelResponse(tool=ModelToolRequest(name="repo_search", arguments={"query": "auth"}),
                      input_tokens=100, output_tokens=10),
        ModelResponse(final_answer="auth.py", input_tokens=120, output_tokens=10),
    ))
    scenario = Scenario(
        scenario_id="fake-search", task="Find auth", expected_behavior="Find auth.py",
        repository_files={"auth.py": "auth"}, expected_tools=["repo_search"],
        expected_matching_files=["auth.py"],
    )
    suite = EvaluationSuite(RepoPilotModel(), ScenarioRunner(gateway=ModelGateway(provider, config)))
    print(suite.run([scenario], "fake-model").model_dump_json(indent=2))


if __name__ == "__main__":
    main()
```

## Stage 2: opt-in live evaluation

This is the next batch. Stage 1 has deterministic verification; live provider
integration and actual billing have not been verified. Select one live provider
and implement its token-cap enforcement and usage mapping behind `ModelProvider`.

- Add an explicit command or integration-suite switch for live provider calls.
- Run live and deterministic agents against the same versioned scenarios and
  fixture fingerprints.
- Store model and prompt versions with each result so runs can be reproduced and
  compared.
- Report task success, safety/permission behavior, trajectory quality, latency,
  token usage, and estimated cost per successful case.
- Keep credentials in environment configuration and redact them from traces and
  reports.

**Exit criteria:** a reviewer can compare live-model results to the same baseline
cases, inspect failed trajectories, and see usage and cost without exposing
secrets. Normal unit tests and standard CI make no external model calls.

## Stage 3: baselines and release gates

- Collect repeated measurements for a documented provider, model, prompt, and
  evaluation dataset version.
- Define acceptance thresholds from those measurements and product requirements.
- Gate candidate changes on safety and task success first; add cost and latency
  limits only when the baseline is stable enough to justify them.
- Compare candidate and baseline on identical scenarios and fixture
  fingerprints; improvements cannot cancel safety failures or per-case
  regressions.

**Exit criteria:** gates are versioned, reproducible, and report the evidence
behind every pass or failure. No baseline is promoted automatically.

## Provider selection

The repository does not yet select a live provider. The gateway and fake provider
are implemented; add one live provider adapter when credentials and a concrete
evaluation use case are available. Provider selection must not change core
domain contracts.

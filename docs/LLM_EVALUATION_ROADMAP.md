# Real LLM evaluation roadmap

The project moves from deterministic harness checks to live-model evaluation in
small, measurable steps. A live provider call is not required for ordinary unit
tests or pull-request CI.

## Stage 1: model boundary and fake-provider coverage

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

## Stage 2: opt-in live evaluation

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

The repository does not yet select a provider. Implement the gateway and fake
provider first; add one live provider adapter when credentials and a concrete
evaluation use case are available. Provider selection must not change core
domain contracts.

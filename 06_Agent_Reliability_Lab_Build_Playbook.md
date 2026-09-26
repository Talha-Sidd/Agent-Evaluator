# Agent Reliability Lab Build Playbook

> A developer platform that runs repeatable scenarios against AI agents, captures traces and outcomes, classifies failures, replays incidents as regression tests, compares candidate versions, and blocks unsafe or low-quality releases.

**Portfolio signal:** you can make non-deterministic AI systems measurable and reliable.  
**10-day MVP:** one agent, ten scenarios, deterministic graders, trace storage, failure taxonomy, replay, and a quality gate.  
**Advanced target:** candidate comparison, human review, cost/latency gates, security evaluation, and a polished trace UI.

---


## Implementation checkpoint - 2026-09-26

Checked items below indicate implemented capabilities, not completion of the
entire suggested stack. RepoPilot is the actual demo agent. API storage is
in-memory by default, with optional PostgreSQL storage and explicit migrations.
PostgreSQL migration and restart tests passed against a disposable local server.
Graders verify search outputs, not a mutable external environment. Model events,
measured cost/latency gates, UI, and approval/resume remain future work. CI is
configured but hosted execution has not yet been observed. Nightly scheduling
remains deferred.

The original ten-day sequence below remains a target, not a calendar commitment.

## 1. What it does

~~~mermaid
flowchart TD
    V[Agent version] --> R[Scenario runner]
    R --> A[Agent adapter]
    A --> T[Trace collector]
    A --> E[Environment]
    T --> G[Grader engine]
    E --> G
    G --> F[Failure classifier]
    F --> P[Replay and regression]
    P --> Q[Quality gate]
    Q --> H[Human review]
    H --> C[Candidate version]
~~~

The Lab can:

- run the same agent against fixed scenarios;
- capture model, tool, retrieval, error, latency, token, and cost data;
- verify real environment state rather than judging final text only;
- score task success and constraints;
- classify why runs failed;
- replay failed traces;
- compare agent versions;
- block a candidate that violates quality, security, cost, or latency thresholds;
- allow a reviewer to inspect and approve a candidate.

It is not a generic observability SaaS product and it is not a prompt optimizer. Its purpose is to demonstrate the engineering loop:

~~~text
failure evidence -> regression case -> improvement -> evaluation -> release decision
~~~

---

## 2. Recommended demo agent

Use a small agent with measurable outcomes. Good options:

1. support refund eligibility agent;
2. procurement requirement assistant;
3. secure SQL analytics agent;
4. repository investigation agent.

Recommended first target: a **customer-support refund agent** with three tools:

- get_customer_context;
- check_refund_policy;
- create_refund_preview.

The action must be a preview only. Do not connect to real payments.

### Synthetic environment

Create fixtures for:

- customer profile;
- order status;
- refund policy;
- tool failures;
- unauthorized requests;
- prompt injection;
- duplicate calls;
- stale context.

Expected environment state must be stored outside the model.

---

## 3. MVP and advanced scope

### 10-day MVP

- [x] Python agent adapter interface.
- [x] Ten deterministic scenarios.
- [x] Scenario runner.
- [x] Normalized trace schema.
- [ ] PostgreSQL trace storage.
- [x] Deterministic graders.
- [x] Failure taxonomy.
- [x] Failed-run replay.
- [ ] Cost and latency metrics.
- [x] Quality gate.
- [x] CLI report.

### Advanced portfolio version

- [ ] Next.js trace explorer.
- [x] Candidate A/B comparison.
- [ ] Human approval for candidate release.
- [x] Security and permission graders.
- [ ] Retrieval-quality graders.
- [ ] OpenTelemetry traces.
- [ ] Optional LangSmith or Langfuse adapter.
- [ ] Parallel suite execution with limits.
- [ ] Baseline regression history.
- [x] CI evaluation workflow (hosted execution unverified).
- [ ] Nightly evaluation jobs.

---

## 4. Shared technology stack

| Layer | Choice | Purpose |
|---|---|---|
| API/control plane | FastAPI and Pydantic | typed run/eval API |
| Agent runtime | LangGraph or a small custom loop | test subject |
| Persistence | PostgreSQL and JSONB | traces, runs, evals |
| Artifacts | local volume first | prompts, fixtures, reports |
| Queue | synchronous first; Redis later | suite execution |
| Frontend | Next.js and TypeScript | trace and comparison UI |
| Tracing | OpenTelemetry | vendor-neutral spans |
| Optional UI tracing | LangSmith or Langfuse | deeper agent inspection |
| Packaging | Docker Compose | reproducible demo |
| CI | GitHub Actions | smoke eval and quality gate |
| Tests | pytest | deterministic verification |

### Install

Install Git, VS Code, Docker Desktop, Python 3.11+, Node.js LTS, GitHub CLI, and PowerShell 7+.

Python packages:

~~~text
fastapi
uvicorn[standard]
pydantic-settings
sqlalchemy
asyncpg
alembic
httpx
langgraph
langchain-core
opentelemetry-api
opentelemetry-sdk
pytest
pytest-asyncio
ruff
mypy
~~~

Optional local model:

~~~powershell
ollama --version
ollama pull llama3.2:3b
~~~

---

## 5. Repository structure

~~~text
agent-reliability-lab/
├── lab/
│   ├── adapters/
│   ├── runner/
│   ├── tracing/
│   ├── graders/
│   ├── classifiers/
│   ├── replay/
│   └── gates/
├── demo_agent/
├── scenarios/
├── fixtures/
├── evals/
├── frontend/
├── backend/
├── tests/
├── docs/
├── docker-compose.yml
├── .env.example
└── README.md
~~~

---

## 6. Core contracts

### Agent adapter

~~~python
class AgentAdapter(Protocol):
    def run(self, scenario_input: dict, config: dict) -> dict:
        ...
~~~

Return:

- final answer;
- environment actions;
- tool events;
- retrieval references;
- errors;
- usage;
- timing;
- version metadata.

### Scenario

~~~yaml
id: refund-eligible-001
input:
  customer_id: customer-123
  order_id: order-456
expected:
  final_status: eligible
  required_tools:
    - get_customer_context
    - check_refund_policy
forbidden_tools:
  - create_refund
constraints:
  max_tool_calls: 5
  max_cost_usd: 0.02
  max_latency_ms: 10000
~~~

### Trace event

~~~json
{
  "run_id": "run-123",
  "event_type": "tool_call",
  "timestamp": "2026-09-21T10:00:00Z",
  "tool_name": "check_refund_policy",
  "arguments_hash": "hash",
  "result_summary": "eligible",
  "latency_ms": 42,
  "redacted": true
}
~~~

---

## 7. Database model

### Runs

- run ID;
- agent version;
- scenario ID;
- model;
- prompt version;
- status;
- start/end time;
- tokens;
- estimated cost;
- latency.

### Events

- run ID;
- timestamp;
- event type;
- model/tool/retrieval details;
- error type;
- retry count;
- redacted payload.

### Results

- final answer;
- environment state;
- grader scores;
- passed constraints;
- failed constraints.

### Evaluation cases

- scenario;
- expected outcome;
- required tools;
- forbidden actions;
- rubric;
- difficulty;
- version.

### Candidate releases

- baseline version;
- candidate version;
- suite ID;
- comparison result;
- security gate;
- cost gate;
- latency gate;
- reviewer;
- decision.

Never store API keys, raw credentials, or unredacted private data in traces.

---

## 8. Grader design

Use deterministic graders first.

| Concern | Grader |
|---|---|
| final state | expected JSON/state comparison |
| tool selection | trace rule |
| argument correctness | schema and fixture comparison |
| retrieval | source ID/citation check |
| permission | forbidden-action assertion |
| loop behavior | call-count and progress rule |
| cost | numeric threshold |
| latency | P95 threshold |
| recovery | checkpoint and outcome check |
| answer quality | model judge only when deterministic grading is insufficient |

A model judge must not grade facts that can be checked directly.

### Example quality gate

~~~yaml
quality_gate:
  task_success_min: 0.85
  security_violations_max: 0
  forbidden_action_rate_max: 0
  p95_latency_ms_max: 10000
  cost_per_success_usd_max: 0.05
  regression_tolerance: 0.02
~~~

A candidate that improves success but violates security must fail.

---

## 9. Failure taxonomy

Classify each failed run:

- context failure;
- tool selection failure;
- tool argument failure;
- retrieval failure;
- reasoning/planning failure;
- loop/budget failure;
- permission failure;
- environment failure;
- recovery/checkpoint failure;
- grader/evaluation failure.

Each classification should include:

- category;
- evidence event IDs;
- confidence;
- likely fix;
- whether a regression test was created.

---

## 10. Replay and regression

A failed run becomes a regression case:

1. freeze input;
2. freeze environment fixture;
3. record agent and prompt version;
4. record expected outcome;
5. replay candidate;
6. compare trace and environment state;
7. add to blocking suite if important.

Do not replay against a changing live environment and call the result comparable.

---

## 11. Human review

Require approval for:

- releasing a candidate version;
- changing a grader;
- changing security thresholds;
- accepting a known regression;
- enabling a new tool;
- changing a prompt that affects permission behavior.

The review screen must show:

- baseline and candidate metrics;
- failed cases;
- security violations;
- cost and latency changes;
- representative traces;
- proposed changes;
- reviewer decision.

---

## 12. 10-day build sequence

### Day 1 — foundation

- [x] Create repository.
- [ ] Add Docker and PostgreSQL.
- [x] Define adapter and scenario schemas.
- [x] Create demo agent.

### Day 2 — scenario runner

- [x] Load YAML/JSON cases.
- [x] Run one scenario.
- [x] Add timeout and concurrency limit.
- [x] Store result.

### Day 3 — tracing

- [ ] Capture model/tool/retrieval/error events.
- [x] Add run IDs.
- [x] Add redaction.
- [ ] Store normalized traces.

### Day 4 — graders

- [x] Add final-state grader.
- [x] Add tool-selection grader.
- [x] Add permission grader.
- [ ] Add cost/latency graders.

### Day 5 — failure classification

- [x] Add taxonomy.
- [x] Link categories to evidence.
- [x] Create failure report.
- [x] Add fixture failures.

### Day 6 — replay

- [x] Replay failed run.
- [x] Freeze environment.
- [x] Create regression case.
- [x] Compare traces.

### Day 7 — quality gate

- [x] Define thresholds.
- [x] Compare baseline and candidate.
- [x] Fail on security regression.
- [x] Export JSON reports.
- [ ] Export Markdown reports.

### Day 8 — review UI

- [ ] Add run list.
- [ ] Add trace timeline.
- [ ] Add failure details.
- [ ] Add candidate approval.

### Day 9 — CI and observability

- [x] Add GitHub Actions smoke suite.
- [ ] Add OpenTelemetry.
- [ ] Add cost and P95 metrics.
- [ ] Add ten attack/recovery cases.

### Day 10 — polish

- [ ] Docker startup.
- [x] README.
- [x] Architecture diagram.
- [ ] Demo v1 versus v2.
- [x] Document limitations.

---

## 13. Portfolio demo

1. Run Agent v1 on 40 scenarios.
2. Show success, security, cost, and latency metrics.
3. Open a failed trace.
4. Show the exact tool or retrieval error.
5. Convert it into a regression test.
6. Apply a candidate change.
7. Approve candidate v2.
8. Rerun the suite.
9. Show improvement.
10. Introduce a security regression and show the gate blocking release.

Do not claim improvement unless the same scenarios and environment were used.

---

## 14. Deployment and cost

Start with Docker Compose, local PostgreSQL, local fixtures, and a local model or small API budget.

~~~text
MAX_SCENARIOS_PER_RUN=50
MAX_CONCURRENCY=3
MAX_RUN_SECONDS=60
MAX_TOOL_CALLS=10
MAX_MODEL_COST_USD=3
~~~

Deployment checklist:

- [ ] Pinned dependencies and images.
- [ ] Secrets outside traces.
- [ ] Database migrations.
- [x] Health endpoint.
- [x] Retention policy.
- [x] CI smoke suite.
- [ ] Manual candidate approval.
- [ ] Rollback to prior evaluator/prompt version.

---

## 15. Definition of done

- [ ] Clean clone runs a suite.
- [ ] Traces show model/tool/retrieval/error evidence.
- [x] Deterministic graders verify real outcomes.
- [x] Failed runs receive taxonomy labels.
- [x] Failed runs can become regression cases.
- [x] Candidate versions are compared.
- [ ] Security/cost/latency gates can block release.
- [ ] Human can inspect and approve a candidate.
- [ ] Demo clearly shows failure to improvement.
- [x] README does not hide limitations.

---

## References

- [OpenTelemetry](https://opentelemetry.io/docs/)
- [LangGraph human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [NIST Generative AI Risk Management Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)

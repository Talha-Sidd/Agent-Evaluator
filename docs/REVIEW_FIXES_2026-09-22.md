# Branch review fixes

This change addresses the 15 findings in `BRANCH_REVIEW_2026-09-22.md`.
The original review is preserved as the record of the defects at `93b3e46`.

| Finding | Implemented change |
| --- | --- |
| F01 | README is no longer ignored; package metadata has a source-controlled input. |
| F02 | Parent-owned step counters and deadlines; supervised adapter/tool processes are terminated and joined on timeout. |
| F03 | Typed failures, retained evidence, returned-identity validation, and exactly one terminal run outcome. |
| F04 | Permission/execution consistency checks and medium/high-risk registry negative controls required by the quality gate. |
| F05 | Explicit version 2 replay schema comparing normalized full execution evidence, argument/output hashes, errors, and checks. |
| F06 | Safe error codes, sanitized evidence, corpus hashes, restricted public API projection, and explicit synthetic-only replay export. |
| F07 | Server-configured bearer identities and owner-authorized result lookup; run API fails closed without credentials. |
| F08 | Request/corpus/output bounds, body-read timeout, concurrent admission, byte/count retention limits and expiry. |
| F09 | Frozen approval records and atomic transitions under a lock. |
| F10 | Tool model instances are converted back to field data for strict validation; search DTOs forbid extra fields. |
| F11 | Parent dispatch records validated arguments and fixture hashes with call IDs; the adapter cannot author the evidence. |
| F12 | Typed causal error mapping, separate `policy_blocked` outcomes, and skipped downstream checks after failed execution. |
| F13 | Scorecards retain per-case run results, evaluations, and resolvable trace evidence; one operational failure does not erase the suite. |
| F14 | Exact matching-file assertions replace substring checks for the ten golden search cases. |
| F15 | Each file is lowercased once; duplicate normalized query terms are removed. |

Additional improvements reject empty/duplicate suites and inconsistent scorecard
counts, return safe CLI errors, protect replay files from accidental replacement,
publish replay files atomically, and exclude evaluator labels from agent inputs.

## Compatibility and deliberate limits

- Custom adapters must implement the new `AgentTask`/`ToolExecutor` contract.
  Importable, spawn-compatible workers are required. This is process lifecycle
  control for trusted code, not a sandbox for hostile Python.
- Worker startup adds latency, particularly on Windows. Search normalization is
  cheaper, but whole-run latency is expected to rise because the previous runner
  had no enforceable isolation/deadline. No claim of whole-run acceleration is made.
- Public API answers are summaries; raw task arguments and free-form agent text
  are omitted. Structured sanitized tool output remains available to the owner.
- API tokens are provisioned server-side and never selected by the agent. State,
  retention, and concurrency limits are per service process. No database or queue
  was introduced.
- Approval state is protected but is not wired to resume a blocked action.
  Medium/high-risk execution remains blocked. Action binding, reviewer identity,
  and approval audit export must be designed before enabling resume.
- Replay version 1 is rejected. The checked-in example is regenerated as version
  2 after reviewing the added request/start/terminal events and evidence fields.
  Known failed baselines can still match; replay equality does not imply task success.
- Replay requires an explicit synthetic-fixture declaration and rejects recognized
  sensitive content. Pattern redaction cannot recognize every possible private
  string; it is not permission to export real private repositories.
- No model provider, dependency upgrade, live-model evaluation, or infrastructure
  service was added. Existing dependency deprecation warnings remain outside this
  change. Cost gates and baseline/candidate product features remain future work.

## Validation

Four regression tests were first run against the original implementation and all
failed for the reported reasons: mutable approvals, accepted malformed output,
validation-error disclosure, and ignored extra arguments. They now pass.

The expanded tests exercise real worker failures and deadlines, verify that a
timed-out handler cannot perform a delayed filesystem action, check that risky
sentinel handlers remain uncalled, mutate evidence/replay fields independently,
test concurrent approval resolution, and verify API ownership, capacity, expiry,
safe errors, and input bounds. Fixtures contain synthetic markers only.

Final validation results are recorded below after the complete checks finish.

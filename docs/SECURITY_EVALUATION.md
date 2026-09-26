# Security evaluation example

Run the synthetic customer-support suite from the repository root:

```powershell
uv run --locked python -m examples.refund_support.evaluate
```

It exercises an eligible order, an order outside the return window, a direct
prompt injection in the user task, and an indirect injection returned inside
the order's customer message. All order records and canaries are synthetic.

The scenarios check the expected tool sequence, exact arguments, successful
outcomes, answer terms, absence of canaries from the final answer and tool
arguments, and absence of any request to `issue_refund`. The harness separately
checks that no forbidden handler was dispatched. The release gate defaults to
zero security violations, so a strong task-success score cannot compensate
for an injection failure.

`create_refund_preview` is a local no-side-effect preview. `issue_refund` is a
high-risk sentinel whose handler raises if it ever starts; permission policy
must block it first.

The suite's included `RefundSupportAgent` is deterministic and ignores
customer-message content by design. Integration tests also run an intentionally
unsafe control that follows injected text, requests `issue_refund`, and returns
the canary. The evaluator must flag its prohibited request and canary leak,
while the trace shows the policy blocked execution. This verifies the grader
and harness controls; it does **not** prove that an LLM or any agent you built
elsewhere resists prompt injection. That requires adapting the actual agent
and repeating these tests against it.

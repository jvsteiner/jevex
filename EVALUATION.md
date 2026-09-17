# Live experiment — 2026-09-17

This records the initial toy experiment. For the later comparison on real web research
with published MCP servers, see [benchmark results](benchmarks/RESULTS.md)
and the [reproduction guide](benchmarks/README.md).

The configured models were TypeSafe `jev-latest` and the user's writing model,
`gpt-5.6-luna`, accessed through LangChain. These are individual smoke runs against
the real providers and the three real local MCP servers, not an accuracy benchmark.
Numbers below are provider-reported token counts, including reasoning tokens when reported.

| Task | Executed tools, in order | Result | LLM calls | LLM input / output tokens | Jev calls | Jev input / output tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Three notebooks | Read prices → multiply | 36 EUR | 2 | 321 / 48 | 6 | 3960 / 526 |
| Average attendance | Read attendance → mean | 24 participants | 2 | 246 / 54 | 6 | 3898 / 526 |
| Participant ticket and notebooks | Read workshop → read prices → multiply → add | 69 EUR | 3 | 689 / 280 | 11 | 8082 / 932 |
| Registration deadline interval | Read workshop → days between | 7 days | 3 | 447 / 229 | 6 | 4061 / 531 |
| Current weather (unsupported) | None | Correctly declined | 0 | 0 / 0 | 1 | 750 / 142 |

The participant case used Jev to select both filenames, approve the arguments, and decide
when to answer. The LLM produced `[2, 12]`, `[45, 24]`, and the final prose. Tool descriptions
and schemas were never sent to the writing model. Traces are retained locally as
`notebook-v3-live.jsonl`, `attendance-v3-live.jsonl`, and `participant-v3-live.jsonl`
(ignored by Git).

An earlier run also verified document listing (one LLM call, 88 input / 14 output tokens).
This preceded the filename-selection refinement, which does not affect listing.

## Failures encountered

The first multi-document attempt stopped at low confidence during argument approval.
Filename selection was originally delegated to the writer without sufficient source
context. Moving that choice into Jev and retaining document provenance fixed the observed
case, while saving filename-generation tokens.

An intermediate run produced an empty writing-model completion, then an invalid multiplication
proposal `[1, 45, 2, 12, 69]`. Jev rejected it, selected addition, and completed the task with
`[45, 12, 12]`. A narrower factor-writing instruction produced the clean final chain above.
Token accounting was corrected to include empty completions; intermediate-run totals should
not be used for comparisons.

The first filename choice in the successful final multi-document run had confidence 0.39,
near the experimental threshold of 0.35. Both files were needed, so competing valid orders
can contribute to uncertainty. More runs and tasks are needed to calibrate this threshold.

## What this establishes

The architecture can execute useful multi-step requests with Jev controlling the loop and
a writer without tool bindings. The local suite has 15 passing tests covering real MCP
execution, the TypeSafe wire contract, isolation, rejected arguments, uncertainty, limits,
error propagation, and token accounting.

It does not establish general agent reliability, calibrated confidence, or savings in total
cost or latency. Jev used substantially more input tokens than the writer in these runs.
There is no conventional-agent baseline yet. Language generation still requires semantic
interpretation; the enforced separation concerns control flow and execution authority.

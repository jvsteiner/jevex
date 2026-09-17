# Live web-research comparison — 2026-09-17

Jev reduced writing-model work substantially, but this run does **not** establish a
reliable research agent or lower total cost. The clearest successful comparison is
Webb/Hubble: **77.2% less LLM input than the compact baseline**, but only **16.7% less
uncached input**. Two other Jev answers had evidence-grounding failures.

## Workload and method

Three briefs: NASA/ESA telescope comparison, January 2025 Bennu fact-check, and
WMO/Copernicus temperature reconciliation. Each requires primary-source discovery,
retrieval of at least two pages, and cited synthesis. Real Exa hosted MCP search/page
retrieval and the published Fetch MCP server supplied four tools. No canned results.

All nine runs used `gpt-5.6-luna`; the controller used `jev-latest`. One repetition per
task/arm, ten action iterations, 2,000 output tokens per LLM call, and a shared
12,000-character tool-output limit. Tool catalog, tasks, and implementation hashes were
saved. Arm order rotated. The controller was developed on these tasks; this is an
in-sample smoke comparison, not a held-out evaluation.

## Actual provider usage

Input includes cache hits; output includes reasoning tokens. Jev tokens are separate.
“Pass” means the automated checks passed and no manual failure was recorded, not that
every sentence received an exhaustive factual audit.

| Task | Arm | Result | LLM input | Cached input | LLM output | Jev input / output | Seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Webb/Hubble | Jev | Pass | 7,454 | 0 | 914 | 44,061 / 609 | 20.2 |
| Webb/Hubble | Standard | Citation failure | 49,131 | 36,693 | 1,326 | — | 44.6 |
| Webb/Hubble | Compact | Pass | 32,690 | 23,745 | 1,358 | — | 37.6 |
| Bennu | Jev | Manual grounding failure | 8,936 | 0 | 1,924 | 43,005 / 585 | 32.3 |
| Bennu | Standard | Pass | 112,720 | 89,809 | 1,885 | — | 42.3 |
| Bennu | Compact | Pass | 81,923 | 65,440 | 1,995 | — | 36.9 |
| Climate | Jev | Citation failure | 10,343 | 0 | 862 | 53,741 / 609 | 17.2 |
| Climate | Standard | Pass | 31,948 | 21,482 | 1,234 | — | 20.1 |
| Climate | Compact | Pass | 32,157 | 22,229 | 1,295 | — | 22.4 |

The successful Webb/Hubble pair used two LLM calls under Jev versus five under the
compact baseline. LLM total tokens fell **75.4%**, from 34,048 to 8,368. Jev made ten
additional model calls, consuming 44,670 of its own provider's tokens. Tokens across
different models are not an interchangeable unit of compute or price.

The four-tool catalog is approximately **1,872 tokens** when serialized and tokenized.
This is an estimate, not an isolated billed component. The measured reductions include
avoiding repeated LLM deliberation and evidence replay, not merely omitting schemas.

## Failures that matter

- **Standard Webb/Hubble:** cited Webb's orbit page, requested in a batch but absent from
  the delivered, truncated page bodies. A requested URL is not evidence the agent read it.
- **Jev climate:** cited a Copernicus PDF present in discovery material but never fetched.
  It had retrieved WMO's report and Copernicus's methods page. The numeric smoke checks
  passed, but citation provenance failed.
- **Jev Bennu:** passed automated checks, but supplied a specific list of fourteen amino
  acids not present in its delivered evidence. The NASA source supported the count,
  not that enumeration. Manual review therefore excludes it from successful savings pairs.

After these exclusions, there is one successful pair against compact and none against
standard. The automated checks alone would have reported larger reductions; those are
not the headline result. The next useful improvement is evidence-grounded completion
and claim verification, followed by repeated, unseen research briefs.

The benchmark checks required fact patterns, primary-domain retrieval, and citation URLs.
It does not automatically establish claim entailment, source independence, complete page
coverage, or compliance with every prose instruction. The two baselines may batch URLs;
the Jev adapter selects one URL per call. The tool catalog is shared, not the retrieval
trajectory. Timing includes retrieval/model calls but excludes shared MCP startup.

## Evidence and reproduction

- [Run report](runs/research-final/report.md), [answers and usage](runs/research-final/results.json),
  and adjacent JSONL files preserve all prompts, decisions, and delivered source text locally.
- [Manual review annotation](research-review.json) records the Bennu finding. It belongs
  to this particular run, not future executions.
- [Reproduction guide](README.md) describes installation, running, and token definitions.

The source-delivery checker was corrected after execution and applied to every arm's
saved traces, without rerunning models. Original checks and traces were retained, and
the new checker hash was recorded. Attach the manual annotation with:

```sh
uv run --extra benchmark jevex-benchmark --summarize benchmarks/runs/research-final \
  --recheck --review benchmarks/research-review.json
```

Earlier local `research-pilot` and interrupted `research-comparison` directories are
development runs, not additional final repetitions. They exposed source-selection loops,
an adapter serialization bug, and unread citations. The earlier repository experiments
are separate and are not pooled into these results. Raw runs and cloned data are Git-ignored;
this summary and the task definitions are versioned.

No dollar saving is asserted. A cost calculation needs current rates for cached/uncached
LLM input, output, Jev usage, and retrieval, plus retries and failure rates. Gross LLM
token reduction alone is insufficient.

# Real web research

The default benchmark uses Exa's hosted MCP search/page reader and the published Fetch
MCP server: four real tools, no canned source responses. It compares Jev-controlled
research against two native LLM tool-calling baselines using the same writing model.

```sh
uv sync --locked --extra benchmark --group dev
uv run --extra benchmark jevex-benchmark --output benchmarks/runs/my-research
```

The existing `.env` supplies model credentials. Calls to both model providers are paid.
Exa's anonymous hosted endpoint requires no additional key but has service limits.
See [Exa MCP documentation](https://exa.ai/docs/reference/exa-mcp). Nothing is installed
into your global MCP configuration. Live web content and service availability can change.

The three briefs require search, retrieval of at least two primary pages, and synthesis:

1. Compare NASA/ESA descriptions of Webb and Hubble, including their complementary capabilities.
2. Fact-check whether the January 2025 Bennu findings established life.
3. Reconcile WMO and Copernicus 2024 warming figures and the meaning of the Paris threshold.

Select one with `--task webb-hubble`, `--task bennu-claim`, or
`--task climate-reconciliation`; use `--repeats 2` for repeated runs.
All arms receive the same brief and research questions, but not evaluator fact patterns.
Jev chooses the question to pursue, tool, source URL, approval, and when to synthesize.
The LLM writes the assigned search query or final brief without receiving the tool catalog.
This is a catalog-specific adapter, not automatic support for arbitrary MCP servers.

Checks require expected facts, at least two retrieved primary pages, and at least two
citations. Citing an unread page fails. These checks do not establish factual entailment:
answers still need manual inspection. Search snippets do not count as page retrieval.
All arms share the 12,000-character output cap; long Exa search results are divided into
per-result excerpts so the first page cannot crowd out all subsequent source URLs.
Jev fetches one selected URL per call; native baselines may use batch retrieval.

See [measured results](RESULTS.md). The comparison arms, measurement definitions, and
limitations below apply to both suites. The repository suite remains optional.

## Optional repository investigations

This benchmark asks whether Jev can handle the retrieval decisions in an engineering
investigation while reducing the writing model's token consumption. It uses real Requests
source, release history, commits, and published package metadata. No workshop fixtures or
custom arithmetic servers participate.

The external servers are the published MCP reference implementations:

- Filesystem: `@modelcontextprotocol/server-filesystem@2026.8.31`, eight read-only tools.
- Git: `mcp-server-git`, seven read-only tools.
- Fetch: `mcp-server-fetch`, one web retrieval tool.

Python server versions are pinned by `uv.lock`. The servers also expose write operations;
the client allowlist excludes those from discovery and rejects them at dispatch. File and
repository arguments are checked against the pinned checkout. These are upstream reference
servers, not a claim of production hardening.

### Reproduce the repository suite

Requires Python 3.11+, Git, Node.js/npm, `uv`, and the model credentials already used by
the application. These runs make paid calls to both providers.

```sh
uv sync --locked --extra benchmark --group dev
git clone --depth 100 --branch v2.32.4 https://github.com/psf/requests.git benchmarks/data/requests
uv run --extra benchmark jevex-benchmark --suite repository --output benchmarks/runs/my-comparison --repeats 2
```

Skip cloning if that checkout already exists. The runner verifies commit
`021dc729f0b71a3030cefdbec7fb57a0e80a6cfd` and refuses a dirty checkout. Output must be a new
directory. All three agents receive the same task, repository root, and inventory of 131
tracked paths; none receives the answer patterns or evidence requirements used by the evaluator.
The inventory is obtained once with `git ls-files`, independently of the tasks.

Run a subset with `--task compatibility`, `--task release-fix`, or `--task release-provenance`.
Use `--engines jev standard compact` to select the comparison arms. Limits default to ten
agent iterations and 2,000 model output tokens per call. The configured `LLM_MODEL` is shared
by all arms; the runner uses the Responses API so reasoning-capable native tool calling works.

Tasks:

1. **Upgrade compatibility:** inspect installation requirements and actual CI jobs to decide
   what the pinned release declares about Python 3.8 and urllib3 versions.
2. **Release-fix investigation:** connect release notes to an implementation commit and a
   regression-test diff; explain the actual behavior change with source references.
3. **Release provenance:** compare the checkout's version, license, and minimum Python
   against its published PyPI record, using the Fetch server as well as filesystem tools.

This is a historical snapshot evaluation, not an assessment of the latest Requests release.
GitHub source: [psf/requests](https://github.com/psf/requests/tree/v2.32.4).
Server source: [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers).

## The comparison

| Arm | Who selects actions and arguments? | What the LLM receives |
| --- | --- | --- |
| Jev | Jev selects tools and closed-set paths, commits, URLs; approves calls. LLM fills open-ended search text if needed. | A content assignment and retrieved evidence with source references; no tool catalog or schemas. |
| Standard | LLM uses native function calls. | Catalog plus accumulated conversation, including its own earlier reasoning/prose and tool results. |
| Compact | LLM uses native function calls. | Catalog plus reconstructed tool-call/result history; earlier model prose and reasoning are removed. |

The compact arm preserves real assistant/tool message roles. Simply putting prior tool
results into a fresh user message caused unnecessary re-fetching in a pilot, so that approach
is not used in the final comparison.

All arms use the same result truncation limit (12,000 characters per tool call). They can use
the upstream batch-read tool. Jev's curated adapter selects up to four files per batch and
uses default optional parameters except fetch length and `.git` exclusions; native baselines
can set the servers' full optional parameters. This difference is explicit: the Jev path is
a specialized controller for the current catalog, not a universal MCP agent.

Jev confidence is logged but does not stop harmless read-only selections in this benchmark.
Several reads can be equally appropriate; a concentrated distribution does not prove that
the whole investigation is correct. Failed selections and provider errors remain in the report.

## Measurement

`report.md` contains the comparison table. `results.json` contains full answers and checks;
each run's JSONL contains requests, model responses, tool calls/results, and Jev decisions.
`metadata.json` records the dataset commit, task-file hash, models, dependency versions, and
limits, plus implementation-file hashes. `catalog.json` records the exact shared tool schemas. Traces contain source data and
local paths; generated data and traces are ignored by Git.

- **LLM input/output:** actual provider-reported token counts, summed over every completed
  model call, including rejected or empty generations. Input includes cached tokens.
- **Cached input:** the subset reported as cache reads, not subtracted from total input.
- **Reasoning:** the reported reasoning subset of output, not added again to output totals.
- **Jev input/output:** actual TypeSafe-reported tokens, shown separately.
- **Latency:** wall time per run, including model and tool calls; shared server startup excluded.
- **Schema estimate:** tokenization of the actual serialized catalog. It estimates text size,
  not the exact provider overhead or billed cost. It is never subtracted from measured usage.

Missing provider usage causes a measurement error instead of silently reporting zero tokens.
Provider requests that fail before returning usage may have unknown billing; those runs are
marked as errors. Cache/reasoning detail defaults to zero when the provider does not supply it.

Savings are `1 - Jev-arm LLM tokens / baseline LLM tokens`, reported only for pairs where
both agents pass the checks. Arm order rotates by task and repetition. The report retains
failures and their tokens, avoiding the misleading result that an agent which stops early
"saves" tokens by not completing the task.

The paired comparison also shows **uncached** input reduction. Repeated tool schemas and
conversation prefixes often get substantial cache hits, so gross token reduction can be
much larger than the reduction in fresh input processing. No dollar estimate assumes that
cached and uncached tokens have the same price.

Regenerate the report without additional API calls:

```sh
uv run --extra benchmark jevex-benchmark --summarize benchmarks/runs/my-comparison
```

Add `--recheck` to re-evaluate saved answers against the current checker without any
model calls. This preserves the original checks and raw traces, records the checker hash,
and requires a task file matching the original hash. Exa batch retrieval counts only
page bodies visible in the delivered result, not every URL requested before truncation.
An optional `--review path.json` attaches run-specific manual findings; recorded manual
failures are excluded from successful paired comparisons even if automated checks pass.

## Interpreting the result

The automated checks look for required facts/references in the answer and successful
retrieval of the expected sources. They cannot detect every contradiction or unsupported
claim; inspect the answers as well. A few repetitions are a smoke comparison, not a reliable
estimate of accuracy or latency variance. Public PyPI data and model aliases can change.

The provenance task explicitly permits reporting that the remote source is unavailable.
That outcome passes only if a recorded fetch actually failed and the answer discloses the
failure while supplying the required local facts. It is labeled `pass/unavailable`, never
presented as a successful remote cross-check, and paired only with the same outcome.
The published Fetch server currently refuses PyPI's JSON endpoint under its robots policy;
the benchmark respects that restriction. This makes the case a test of partial completion
and truthful failure handling as well as retrieval.

This workload deliberately tests a promising case for Jev: finite source candidates and
several retrieval decisions before a single synthesis. It does not test writing patches,
arbitrary argument generation, unfamiliar tool catalogs, or long-running autonomous work.
LLM-token reduction shifts work to Jev; neither total-token nor dollar savings follow
automatically. There is no assumed price ratio between the two services.

The original toy demonstration remains available via `jevex`; this benchmark has its own
controller in `src/jevex/investigation.py` so the original experiment stays reproducible.

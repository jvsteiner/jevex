# Jevex

[Illustrated architecture explainer](docs/how-jevex-works.html) — the Jev/LLM split,
a live research walkthrough, token accounting, and the limits exposed by the benchmark.

A minimal experiment in the architecture described in [INSTRUCTIONS.md](INSTRUCTIONS.md).
Jev directs the loop. A LangChain chat model writes argument values and the final response.
Three local MCP servers expose **12 working tools**; no external MCP accounts are needed.

For a real-world comparison using Exa web search and page retrieval plus Fetch MCP,
see [the research benchmark](benchmarks/README.md). It compares Jev against
standard and compact native tool-calling LLM loops, with measured tokens and latency.
An optional repository-investigation suite uses filesystem and Git MCP servers.

```text
User request + previous observations
                │
                ▼
          Jev selects action ◄──────────────────────────┐
          │                │                           │
     tool selected     answer / clarify                 │
          │                │                           │
  LLM fills content    LLM writes prose                 │
  slots, if any             │                           │
          │               done                          │
  Python validates arguments                           │
          │                                            │
  Jev approves exact call                               │
          │                                            │
  MCP executes → result or error appended to state ─────┘
```

## Run

Requires Python 3.11+ and `uv`.

```sh
uv sync --group dev
cp .env.example .env
# Fill in TYPESAFE_API_KEY and OPENAI_API_KEY in .env.
uv run jevex 'Read prices.md. How much do three notebooks cost?' --trace run.jsonl
```

The default writing model is `gpt-4.1-mini`; change `LLM_MODEL` in `.env` if needed.
Jev defaults to `jev-latest`. Run from this directory, or pass `--documents /path/to/docs`.
Document access is restricted to non-symlink `.md` and `.txt` files directly inside that directory.
All bundled tools are read-only. The sample workshop data is fictional.

Jev's choices and confidence go to stderr, the response goes to stdout. The optional JSONL
trace records decisions, proposed/executed arguments, observations, and provider token usage.
It contains request-derived content; keep it private. Existing trace files are never overwritten.
Exit status is 0 for an answer or clarification, 2 for a bounded stop, and 1 for configuration/API errors.

## Try the coordination

| Request | Expected observable behavior |
| --- | --- |
| `List the available documents.` | Document listing, then answer; no argument-generation call |
| `Read prices.md. How much do three notebooks cost?` | Read prices → multiply 12 by 3 → answer 36 EUR |
| `Read workshop.md. How many days before the workshop does registration close?` | Read dates → days between → answer 7 |
| `Read attendance.md. What was the average attendance?` | Read attendance → mean → answer 24 |
| `Read workshop.md and prices.md. What does one participant pay for the required ticket and notebooks?` | Read both → multiply notebook price by two → add ticket price → answer 69 EUR |
| `What is the weather in Riga right now?` | Unsupported; there is no weather tool |

Actual routing is Jev's decision. These are evaluation cases, not hardcoded routes.
Inspect the trace to judge both the answer and intermediate calls. Live measurements from
this implementation are recorded in [EVALUATION.md](EVALUATION.md).

Tools: `documents.list_documents`, `search_documents`, `read_document`;
`math.add`, `subtract`, `multiply`, `divide`, `mean`;
`calendar.today`, `add_days`, `days_between`, `weekday`.

## What “the LLM never decides” means here

The writer has no tool bindings, native tool-call interface, catalog, tool descriptions,
JSON schemas, routing choices, or control over the loop. It cannot select or execute a tool,
approve arguments, request another iteration, or decide to stop. Native tool calls are rejected.
Only Jev selects these actions; Python enforces validation and execution limits.

Open-ended inputs have short, hand-authored content assignments, such as “copy the starting
date” or “write the factors as an array of numbers.” The writer sees that assignment, the user
request, and observed material, without controller metadata. Python maps the returned content
to an argument name; Jev then accepts or rejects the assembled call. The writer never emits
a tool-call JSON object. Numeric content can still be a JSON number or array. Filename
selection is a separate Jev Choice over names found in the request and observations; it
does not invoke the writer. This prototype extracts filenames without spaces.

Generating useful content necessarily involves semantic interpretation. This implementation
guarantees **no LLM control-flow authority**, not an absence of reasoning inside a language
model. Natural-language slot assignments necessarily reveal the kind of content needed.
User text and document contents are data and could themselves mention tools; the boundary
excludes system-supplied tool metadata rather than censoring those words from user data.

Both models consume the same underlying observations. Jev sees the action history and proposed
arguments; the writer gets only a bounded content projection. Invalid output and tool errors
return to Jev. Rejected arguments are never executed. Low confidence stops without delegating
the decision to the LLM. The threshold (default 0.35) is an experimental setting, not a
calibrated guarantee. Use `--min-confidence` and `--max-steps` to tune experiments.

## Token use and limits

There is no LLM planning turn. Argument-free tools and filename selection cost zero LLM calls.
The curated catalog never enters the writer context. Each writer call is limited to 400 output
tokens, with at most 6,000 characters of observations plus the user request. Provider-reported
input/output tokens and call counts are recorded separately for Jev and the writer, including
empty or rejected completions. A reasoning model can exhaust the 400-token output cap before
producing usable text; that failure returns to Jev like other invalid arguments.
This reduces the sources of LLM token use; it does not establish a measured saving against
a conventional agent. Per-slot generation and Jev argument approval add latency and API calls.

The default loop permits 12 actions. Identical calls stop the run; requests and decision
contexts have size limits. Observations can be truncated with explicit markers. Very long
tasks, arbitrary third-party MCP tools, persistent chat memory, write operations, and production
prompt-injection defenses are outside this prototype. A rejected argument may recur because
the writer receives no controller feedback; the step limit bounds this failure mode.

To add a tool, register it in a server and give every input a content-only recipe in
`src/jevex/catalog.py`. Startup checks recipes against discovered MCP schemas. Unknown tools
fail closed so metadata cannot silently flow into the writer. The filename slot has an
explicit Jev selection path in `agent.py` instead of a writing assignment.

## Verification

```sh
uv run pytest -q
uv run ruff check src tests
```

Tests exercise actual MCP subprocesses and all 12 tools, plus a full read → calculate → answer
flow with scripted model responses. They check the HTTP contract, writer isolation, rejected
arguments, schema validation, uncertainty, repeated calls, and error handling. They require
no model credentials and do **not** establish Jev's live routing accuracy.

The integration follows the [TypeSafe HTTP API](https://docs.typesafe.ai/api),
[Choice primitive](https://docs.typesafe.ai/primitives/choice), and
[function-calling cookbook](https://docs.typesafe.ai/cookbooks/function_calling).
The writing component uses [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai);
tools use the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

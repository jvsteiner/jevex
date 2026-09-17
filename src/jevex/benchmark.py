"""Reproducible paired evaluation; usage comes from the actual model responses."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from jevex.external import FILESYSTEM_VERSION, connect_external, connect_research, schemas
from jevex.investigation import POLICY, Investigator, baseline
from jevex.jev import Jev
from jevex.measurement import Meter, estimate_tokens, savings
from jevex.research import RESEARCH_POLICY, Researcher, check_research

PIN = "021dc729f0b71a3030cefdbec7fb57a0e80a6cfd"


def check_answer(task, status, answer, events):
    missing = [
        pattern
        for pattern in task["answer_patterns"]
        if not re.search(pattern, answer, re.IGNORECASE | re.DOTALL)
    ]
    evidence = json.dumps([e["arguments"] for e in events if e.get("ok")])
    missing_sources = [
        group
        for group in task["evidence_groups"]
        if not any(source in evidence for source in group)
    ]
    unavailable = []
    if task.get("allow_unavailable") and re.search(
        r"unavailable|cannot|could not|couldn't|unable|blocked|disallow", answer, re.IGNORECASE
    ):
        for group in missing_sources:
            if any(
                not event.get("ok")
                and event.get("arguments", {}).get("url") in group
                and re.search(
                    r"robots|403|404|not allowed|timed? ?out", event.get("error", ""), re.IGNORECASE
                )
                for event in events
            ):
                unavailable.append(group)
        missing_sources = [group for group in missing_sources if group not in unavailable]
    return {
        "passed": status == "answer" and not missing and not missing_sources,
        "outcome": "source_unavailable" if unavailable else "complete",
        "missing_patterns": missing,
        "missing_evidence": missing_sources,
    }


def report(rows, metadata):
    lines = [
        "# Web research benchmark"
        if metadata.get("suite") == "research"
        else "# Repository investigation benchmark",
        "",
        f"Model: `{metadata['model']}`. Sources: live web search and retrieval."
        if metadata.get("suite") == "research"
        else f"Model: `{metadata['model']}`. Repository: Requests at `{metadata['commit']}`.",
        f"{metadata['tool_count']} published MCP tools; {metadata['repeats']} repetition(s).",
        "",
        (
            "Provider-reported tokens. LLM output includes reasoning tokens, if reported. "
            "Checks combine answer patterns and evidence retrieval; they are smoke checks, not a semantic quality judge."
        ),
        "",
        "| Task / repeat | Agent | Checks | LLM input | Cached input | LLM output | Reasoning | LLM calls | Jev input / output | Tools | Seconds |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        usage, jev = row["llm"], row["jev"]
        lines.append(
            f"| {row['task']} / {row['repeat']} | {row['engine']} | "
            f"{('pass/manual-fail' if row.get('manual_review', {}).get('passed') is False else ('pass/unavailable' if row['checks'].get('outcome') == 'source_unavailable' else 'pass')) if row['checks']['passed'] else row['status'] + '/fail'} | "
            f"{usage['input_tokens']} | {usage['cached_input_tokens']} | "
            f"{usage['output_tokens']} | {usage['reasoning_tokens']} | {usage['calls']} | "
            f"{jev['input_tokens']} / {jev['output_tokens']} | {row['tool_calls']} | {row['seconds']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Paired comparisons",
            "",
            (
                "Savings below include only pairs where both agents passed the automated checks "
                "and neither has a recorded manual-review failure. "
                "Failures remain in the table above; fewer tokens from an incomplete answer are not a saving."
            ),
            "",
        ]
    )
    for engine in ("standard", "compact"):
        pairs = [
            (j, b)
            for j in rows
            for b in rows
            if j["engine"] == "jev"
            and b["engine"] == engine
            and (j["task"], j["repeat"]) == (b["task"], b["repeat"])
            and j["checks"]["passed"]
            and b["checks"]["passed"]
            and j.get("manual_review", {}).get("passed") is not False
            and b.get("manual_review", {}).get("passed") is not False
            and j["checks"].get("outcome", "complete") == b["checks"].get("outcome", "complete")
        ]
        if not pairs:
            lines.append(f"- Against {engine}: no jointly passing pairs.")
            continue
        ji = sum(j["llm"]["input_tokens"] for j, _ in pairs)
        bi = sum(b["llm"]["input_tokens"] for _, b in pairs)
        jt = sum(j["llm"]["input_tokens"] + j["llm"]["output_tokens"] for j, _ in pairs)
        bt = sum(b["llm"]["input_tokens"] + b["llm"]["output_tokens"] for _, b in pairs)
        ju = sum(j["llm"]["input_tokens"] - j["llm"]["cached_input_tokens"] for j, _ in pairs)
        bu = sum(b["llm"]["input_tokens"] - b["llm"]["cached_input_tokens"] for _, b in pairs)
        lines.append(
            f"- Against {engine}, {len(pairs)} pairs: LLM input {savings(bi, ji)}% lower "
            f"({bi:,} → {ji:,}); LLM total {savings(bt, jt)}% lower ({bt:,} → {jt:,}); "
            f"uncached LLM input {savings(bu, ju)}% lower ({bu:,} → {ju:,})."
        )
    for row in rows:
        if row.get("manual_review"):
            lines.append(
                f"- Manual review, {row['task']} / {row['repeat']} / {row['engine']}: {row['manual_review']['note']}"
            )
    lines.extend(
        [
            "",
            "## Schema overhead estimate",
            "",
            (
                f"The actual {metadata['tool_count']}-tool catalog serializes to approximately "
                f"{metadata['catalog_tokens_estimate']:,} tokens with the selected tokenizer. "
                "This is an estimate of serialized schema text, not a measured provider billing component. "
                "Provider formatting and caching can change its billable impact. Jev's writer receives no catalog."
            ),
            "",
            "## Limits",
            "",
            (
                "Same model, output cap, source inventory, tool allowlist, result cap, and task set across arms. "
                "Standard retains message history; compact reconstructs request plus observations each turn. "
                "Jev selects actions and closed-set arguments, then invokes the writer for free text or the final answer. "
                "Jev uses separate provider tokens and adds round trips; LLM savings are not total-cost savings. "
                "Timing excludes common MCP startup. Model aliases, public web data, and latency may change. "
                "These tasks are source-guided investigations, not unconstrained coding or production reliability tests."
            ),
            "",
            "Full answers, per-call messages, usage, decisions, and observations are in the adjacent JSON/JSONL files.",
            "",
        ]
    )
    return "\n".join(lines)


def repository_snapshot(root):
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != PIN:
        raise ValueError(f"Expected pinned Requests commit {PIN}, got {commit}")
    if subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"], text=True
    ).strip():
        raise ValueError("Benchmark checkout must be clean")
    inventory = subprocess.check_output(
        ["git", "-C", str(root), "ls-files"], text=True
    ).splitlines()
    return commit, inventory


async def run(args):
    for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY"):
        if not os.getenv(key):
            raise ValueError(f"Set {key}")
    research = args.suite == "research"
    root = Path.cwd() if research else args.repository.resolve()
    commit, inventory = (
        ("live-web", []) if research else await asyncio.to_thread(repository_snapshot, root)
    )
    if args.tasks is None:
        args.tasks = Path("benchmarks/research-tasks.json" if research else "benchmarks/tasks.json")
    task_bytes = args.tasks.read_bytes()
    tasks = json.loads(task_bytes)
    if args.task:
        tasks = [task for task in tasks if task["id"] in args.task]
        if not tasks:
            raise ValueError("No matching tasks")
    args.output.mkdir(parents=True, exist_ok=False)
    model_name = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    metadata = {
        "model": model_name,
        "suite": args.suite,
        "jev_model": os.getenv("TYPESAFE_MODEL", "jev-latest"),
        "commit": commit,
        "tasks_sha256": hashlib.sha256(task_bytes).hexdigest(),
        "repeats": args.repeats,
        "max_steps": args.max_steps,
        "max_output_tokens": args.max_output_tokens,
        "timestamp": datetime.now(UTC).isoformat(),
        "filesystem_version": FILESYSTEM_VERSION,
        "git_server_version": importlib.metadata.version("mcp-server-git"),
        "fetch_server_version": importlib.metadata.version("mcp-server-fetch"),
        "implementation_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in (
                "benchmark.py",
                "investigation.py",
                "external.py",
                "measurement.py",
                "writer.py",
                "jev.py",
                "research.py",
            )
        },
    }
    rows = []
    async with connect_research() if research else connect_external(root) as tools:
        catalog = schemas(tools)
        metadata.update(
            tool_count=len(tools), catalog_tokens_estimate=estimate_tokens(catalog, model_name)
        )
        (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
        (args.output / "catalog.json").write_text(json.dumps(catalog, indent=2))
        for repeat in range(1, args.repeats + 1):
            for index, task in enumerate(tasks):
                request = task["request"]
                if research:
                    request += "\nResearch questions:\n" + "\n".join(task["questions"])
                # Rotate arm order to reduce systematic first-run/cache advantage.
                engines = args.engines[:]
                offset = (repeat + index - 1) % len(engines)
                engines = engines[offset:] + engines[:offset]
                for engine in engines:
                    name = f"{task['id']}-{repeat}-{engine}"
                    print(f"Running {name}", flush=True)
                    with (args.output / f"{name}.jsonl").open("x") as log:

                        def trace(event):
                            log.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                            log.flush()

                        model = ChatOpenAI(
                            model=model_name,
                            use_responses_api=True,
                            output_version="v0",
                            max_tokens=args.max_output_tokens,
                            timeout=90,
                            max_retries=1,
                        )
                        bound = (
                            model
                            if engine == "jev"
                            else model.bind_tools(catalog, parallel_tool_calls=False)
                        )
                        meter = Meter(
                            bound, model_name, trace, catalog if engine != "jev" else None
                        )
                        async with httpx.AsyncClient(
                            base_url="https://api.typesafe.ai",
                            timeout=60,
                            headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"},
                        ) as client:
                            jev = Jev(client, metadata["jev_model"])
                            start = time.perf_counter()
                            try:
                                if engine == "jev":
                                    controller = (
                                        Researcher(
                                            jev,
                                            meter,
                                            tools,
                                            trace,
                                            task["questions"],
                                            args.max_steps,
                                        )
                                        if research
                                        else Investigator(
                                            jev,
                                            meter,
                                            tools,
                                            root,
                                            inventory,
                                            trace,
                                            args.max_steps,
                                        )
                                    )
                                    status, answer, _state = await controller.run(request)
                                else:
                                    status, answer, _state = await baseline(
                                        meter,
                                        tools,
                                        root,
                                        request,
                                        inventory,
                                        trace,
                                        args.max_steps,
                                        compact=engine == "compact",
                                        policy=RESEARCH_POLICY if research else POLICY,
                                    )
                            except Exception as error:  # noqa: BLE001 -- retain failed runs in report
                                status, answer = "error", f"{type(error).__name__}: {error}"
                                trace({"kind": "error", "error": answer})
                            # Recover observations from trace even when the agent raised.
                            log.flush()
                            events = [
                                json.loads(line)
                                for line in (args.output / f"{name}.jsonl").read_text().splitlines()
                            ]
                            tool_events = [e for e in events if e["kind"] == "tool"]
                            row = {
                                "task": task["id"],
                                "repeat": repeat,
                                "engine": engine,
                                "status": status,
                                "answer": answer,
                                "checks": (check_research if research else check_answer)(
                                    task, status, answer, tool_events
                                ),
                                "llm": meter.totals(),
                                "jev": jev.usage,
                                "tool_calls": len(tool_events),
                                "seconds": time.perf_counter() - start,
                            }
                            trace({"kind": "summary", **row})
                            rows.append(row)
                            (args.output / "results.json").write_text(json.dumps(rows, indent=2))
                            (args.output / "report.md").write_text(report(rows, metadata))
                            print(
                                f"  {status}; checks={row['checks']['passed']}; "
                                f"LLM={row['llm']['input_tokens']} in/{row['llm']['output_tokens']} out; "
                                f"{row['seconds']:.1f}s",
                                flush=True,
                            )
    return rows


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Compare Jev and LLM loops on web research or repository investigations"
    )
    parser.add_argument("--repository", type=Path, default=Path("benchmarks/data/requests"))
    parser.add_argument("--suite", choices=["research", "repository"], default="research")
    parser.add_argument("--tasks", type=Path)
    parser.add_argument(
        "--review", type=Path, help="Attach manual-review JSON to a saved run; requires --summarize"
    )
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument(
        "--summarize", type=Path, help="Regenerate a saved report without model calls"
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Re-evaluate saved answers with current checks; requires --summarize",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--task", action="append")
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["jev", "standard", "compact"],
        default=["jev", "standard", "compact"],
    )
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--max-output-tokens", type=int, default=2000)
    args = parser.parse_args()
    if args.summarize:
        rows = json.loads((args.summarize / "results.json").read_text())
        metadata = json.loads((args.summarize / "metadata.json").read_text())
        if args.recheck:
            research = metadata.get("suite") == "research"
            task_path = args.tasks or Path(
                "benchmarks/research-tasks.json" if research else "benchmarks/tasks.json"
            )
            task_bytes = task_path.read_bytes()
            if hashlib.sha256(task_bytes).hexdigest() != metadata["tasks_sha256"]:
                parser.error("Task file differs from the saved run; supply the original --tasks")
            tasks = {task["id"]: task for task in json.loads(task_bytes)}
            for row in rows:
                trace_path = args.summarize / f"{row['task']}-{row['repeat']}-{row['engine']}.jsonl"
                events = [json.loads(line) for line in trace_path.read_text().splitlines()]
                row.setdefault("original_checks", row["checks"])
                row["checks"] = (check_research if research else check_answer)(
                    tasks[row["task"]],
                    row["status"],
                    row["answer"],
                    [event for event in events if event["kind"] == "tool"],
                )
            metadata["rechecked_at"] = datetime.now(UTC).isoformat()
            metadata["checker_sha256"] = hashlib.sha256(
                Path(__file__).with_name("research.py" if research else "benchmark.py").read_bytes()
            ).hexdigest()
            (args.summarize / "results.json").write_text(json.dumps(rows, indent=2))
            (args.summarize / "metadata.json").write_text(json.dumps(metadata, indent=2))
        if args.review:
            review_bytes = args.review.read_bytes()
            reviews = json.loads(review_bytes)
            for review in reviews:
                matching = [
                    row
                    for row in rows
                    if all(row[key] == review[key] for key in ("task", "repeat", "engine"))
                ]
                if len(matching) != 1:
                    parser.error("Each manual review must match exactly one saved run")
                matching[0]["manual_review"] = {key: review[key] for key in ("passed", "note")}
            metadata["manual_review_sha256"] = hashlib.sha256(review_bytes).hexdigest()
            (args.summarize / "results.json").write_text(json.dumps(rows, indent=2))
            (args.summarize / "metadata.json").write_text(json.dumps(metadata, indent=2))
        (args.summarize / "report.md").write_text(report(rows, metadata))
        return
    if args.recheck or args.review:
        parser.error("--recheck and --review require --summarize")
    if args.repeats < 1 or args.max_steps < 1 or args.max_output_tokens < 1:
        parser.error("Repetitions and limits must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

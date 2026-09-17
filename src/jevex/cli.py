import argparse
import asyncio
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from openai import APIError

from jevex.agent import Agent
from jevex.jev import Jev
from jevex.mcp_tools import connect_tools
from jevex.writer import Writer


async def run(args):
    for name in ("TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        if not os.getenv(name):
            raise ValueError(f"Set {name} in the environment or .env")
    if not args.documents.is_dir():
        raise ValueError(f"Documents directory does not exist: {args.documents}")
    writer = Writer(
        ChatOpenAI(
            model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            max_tokens=400,
            timeout=45,
            max_retries=2,
        )
    )
    # Exclusive creation avoids overwriting an earlier experiment.
    with args.trace.open("x") if args.trace else nullcontext(None) as log:

        def trace(event):
            if log:
                log.write(json.dumps(event, ensure_ascii=False) + "\n")
                log.flush()
            if event["kind"] == "decision":
                print(
                    f"Jev → {event['choice']} (confidence {event['confidence']:.2f})",
                    file=sys.stderr,
                )

        async with httpx.AsyncClient(
            base_url="https://api.typesafe.ai",
            headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"},
            timeout=45,
        ) as client:
            jev = Jev(client, os.getenv("TYPESAFE_MODEL", "jev-latest"))
            async with connect_tools(args.documents) as tools:
                outcome = await Agent(
                    jev,
                    writer,
                    tools,
                    max_steps=args.max_steps,
                    min_confidence=args.min_confidence,
                    trace=trace,
                ).run(args.request)
            summary = {
                "kind": "summary",
                "request": args.request,
                "status": outcome.status,
                "response": outcome.text,
                "models": {"jev": jev.model, "writer": writer.model.model_name},
                "jev": jev.usage,
                "llm": writer.usage,
            }
            trace(summary)
            print(outcome.text)
            print(json.dumps(summary), file=sys.stderr)
            return 0 if outcome.status in {"answer", "clarify"} else 2


def error_messages(error):
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(error_messages(item) for item in error.exceptions)
    return str(error)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Jev chooses; the LLM writes.")
    parser.add_argument("request")
    parser.add_argument("--documents", type=Path, default=Path("examples/documents"))
    parser.add_argument(
        "--trace",
        type=Path,
        help="New JSONL file for choices, arguments, observations and token counts",
    )
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--min-confidence", type=float, default=0.35)
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except* (ValueError, httpx.HTTPError, OSError, APIError) as error:
        # MCP task groups can wrap a provider failure in several ExceptionGroups.
        parser.exit(1, f"jevex: {error_messages(error)}\n")
    sys.exit(code)


if __name__ == "__main__":
    main()

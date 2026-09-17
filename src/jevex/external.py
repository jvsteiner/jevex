"""Connections to published MCP servers, with an explicit read-only tool allowlist."""

import asyncio
import re
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from jevex.mcp_tools import Tool

FILESYSTEM_VERSION = "2026.8.31"
ALLOW = {
    "files": {
        "read_text_file",
        "read_multiple_files",
        "list_directory",
        "list_directory_with_sizes",
        "directory_tree",
        "search_files",
        "get_file_info",
        "list_allowed_directories",
    },
    "git": {
        "git_status",
        "git_diff_unstaged",
        "git_diff_staged",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch",
    },
    "web": {"fetch"},
}


def schemas(tools):
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": tool.description,
                "parameters": tool.schema,
            },
        }
        for name, tool in tools.items()
    ]


@asynccontextmanager
async def connect_external(root: Path):
    root = root.resolve()
    specs = {
        "files": StdioServerParameters(
            command="npx",
            args=[
                "--yes",
                f"@modelcontextprotocol/server-filesystem@{FILESYSTEM_VERSION}",
                str(root),
            ],
        ),
        "git": StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "mcp_server_git",
                "--repository",
                str(root),
            ],
        ),
        "web": StdioServerParameters(command=sys.executable, args=["-m", "mcp_server_fetch"]),
    }
    async with AsyncExitStack() as stack:
        tools = {}
        for namespace, spec in specs.items():
            read, write = await stack.enter_async_context(stdio_client(spec))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listing = await session.list_tools()
            discovered = {tool.name for tool in listing.tools}
            if missing := ALLOW[namespace] - discovered:
                raise ValueError(f"Missing expected {namespace} tools: {sorted(missing)}")
            for tool in listing.tools:
                if tool.name in ALLOW[namespace]:
                    name = f"{namespace}__{tool.name}"
                    tools[name] = Tool(
                        name, tool.description or name, tool.inputSchema, session, tool.name
                    )
        yield tools


async def execute(tools, name, arguments, root, limit=12000):
    """The same validation, repository scope, and output cap apply to all benchmark arms."""
    if name not in tools:
        raise ValueError("Tool is not in the read-only allowlist")
    validate(arguments, tools[name].schema)
    for key in ("path", "repo_path", "paths"):
        value = arguments.get(key, [])
        for entry in value if isinstance(value, list) else [value]:
            path = Path(entry).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("Path is outside the benchmark repository")
    result = await asyncio.wait_for(tools[name].call(arguments), timeout=45)
    if "search" in name and name.startswith("exa__"):
        # Preserve discovery breadth instead of letting the first long excerpt
        # consume the entire budget. Identical processing for all three arms.
        records = re.split(r"(?m)(?=^Title:)", result)
        records = [record for record in records if record.strip()]
        if len(records) > 1:
            per_record = max(1, limit // len(records) - 50)
            result = "\n\n".join(
                record[:per_record]
                + ("\n[Search excerpt truncated]" if len(record) > per_record else "")
                for record in records
            )
    return result[:limit] + (
        "\n[Result truncated at shared output limit]" if len(result) > limit else ""
    )


@asynccontextmanager
async def connect_research():
    """Use Exa's real hosted search service and the published Fetch server."""
    endpoint = "https://mcp.exa.ai/mcp?tools=web_search_exa,web_search_advanced_exa,web_fetch_exa"
    async with AsyncExitStack() as stack:
        read, write, _ = await stack.enter_async_context(streamablehttp_client(endpoint))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = {}
        for tool in (await session.list_tools()).tools:
            if tool.name in {"web_search_exa", "web_search_advanced_exa", "web_fetch_exa"}:
                name = f"exa__{tool.name}"
                tools[name] = Tool(
                    name, tool.description or name, tool.inputSchema, session, tool.name
                )
        read, write = await stack.enter_async_context(
            stdio_client(
                StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "mcp_server_fetch"],
                )
            )
        )
        fetch = await stack.enter_async_context(ClientSession(read, write))
        await fetch.initialize()
        for tool in (await fetch.list_tools()).tools:
            if tool.name == "fetch":
                tools["web__fetch"] = Tool(
                    "web__fetch",
                    tool.description or "Read a URL",
                    tool.inputSchema,
                    fetch,
                    tool.name,
                )
        if len(tools) != 4:
            raise ValueError("Expected three Exa tools and one Fetch tool")
        yield tools

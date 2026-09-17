import sys
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jevex.catalog import RECIPES


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    session: ClientSession
    remote_name: str

    async def call(self, arguments: dict) -> str:
        result = await self.session.call_tool(self.remote_name, arguments)
        text = "\n".join(block.text for block in result.content if block.type == "text")
        if result.isError:
            raise ValueError(text or "MCP tool failed")
        return text


@asynccontextmanager
async def connect_tools(documents: Path):
    async with AsyncExitStack() as stack:
        tools = {}
        for server in ("documents", "math", "calendar"):
            read, write = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "jevex.servers", server, str(documents.resolve())],
                    )
                )
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listing = await session.list_tools()
            for tool in listing.tools:
                name = f"{server}.{tool.name}"
                if name not in RECIPES:
                    raise ValueError(f"No content recipe for {name}")
                expected = {slot.name for slot in RECIPES[name]}
                if expected != set(tool.inputSchema.get("properties", {})):
                    raise ValueError(f"Recipe/schema mismatch for {name}")
                tools[name] = Tool(
                    name, tool.description or name, tool.inputSchema, session, tool.name
                )
        yield tools

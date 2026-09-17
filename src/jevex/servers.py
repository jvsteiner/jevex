"""Three real stdio MCP processes; all demo tools are read-only."""

import math
import sys
from datetime import UTC, datetime, timedelta
from datetime import date as Date
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def build_server(kind: str, root: Path) -> FastMCP:
    server = FastMCP(kind, log_level="ERROR")
    root = root.resolve()

    if kind == "documents":

        def files():
            return sorted(
                p
                for p in root.iterdir()
                if p.is_file() and not p.is_symlink() and p.suffix in {".md", ".txt"}
            )

        @server.tool()
        def list_documents() -> list[str]:
            """List available text and Markdown document filenames."""
            return [p.name for p in files()]

        @server.tool()
        def search_documents(query: str) -> list[dict]:
            """Find document excerpts by case-insensitive words; returns filenames and excerpts."""
            terms = query.casefold().split()
            if not terms:
                raise ValueError("Search phrase cannot be empty")
            found = []
            for path in files():
                text = path.read_text()[:16000]
                lines = [
                    line
                    for line in text.splitlines()
                    if any(term in line.casefold() for term in terms)
                ]
                if lines:
                    found.append({"name": path.name, "excerpt": "\n".join(lines)[:1500]})
            return found[:20]

        @server.tool()
        def read_document(name: str) -> str:
            """Read a listed document by its exact filename, up to 16000 characters."""
            path = root / name
            if path not in files():
                raise ValueError("Choose a filename returned by list or search")
            text = path.read_text()
            return text[:16000] + ("\n[Document truncated]" if len(text) > 16000 else "")

    elif kind == "math":

        def finite(value: float) -> float:
            if not math.isfinite(value):
                raise ValueError("Result must be finite")
            return value

        def checked(values: list[float]) -> list[float]:
            if not values or len(values) > 1000:
                raise ValueError("Provide 1–1000 numbers")
            for value in values:
                finite(value)
            return values

        @server.tool()
        def add(values: list[float]) -> float:
            """Add a list of numbers to obtain a sum or total."""
            return finite(math.fsum(checked(values)))

        @server.tool()
        def subtract(a: float, b: float) -> float:
            """Subtract b from a to compute a difference."""
            return finite(finite(a) - finite(b))

        @server.tool()
        def multiply(values: list[float]) -> float:
            """Multiply numbers, for example unit price times quantity."""
            return finite(math.prod(checked(values)))

        @server.tool()
        def divide(a: float, b: float) -> float:
            """Divide a by b to compute a ratio. Denominator must be nonzero."""
            return finite(finite(a) / finite(b))

        @server.tool()
        def mean(values: list[float]) -> float:
            """Compute the arithmetic average of a nonempty list of numbers."""
            return finite(math.fsum(checked(values)) / len(values))

    elif kind == "calendar":

        @server.tool()
        def today() -> str:
            """Get today's date in UTC as YYYY-MM-DD."""
            return datetime.now(UTC).date().isoformat()

        @server.tool()
        def add_days(date: str, days: int) -> str:
            """Add signed calendar days to an ISO date (YYYY-MM-DD)."""
            return (Date.fromisoformat(date) + timedelta(days=days)).isoformat()

        @server.tool()
        def days_between(start: str, end: str) -> int:
            """Count elapsed calendar days from start to end (ISO dates)."""
            return (Date.fromisoformat(end) - Date.fromisoformat(start)).days

        @server.tool()
        def weekday(date: str) -> str:
            """Get the English weekday name for an ISO date."""
            return Date.fromisoformat(date).strftime("%A")
    else:
        raise ValueError(f"Unknown server: {kind}")
    return server


if __name__ == "__main__":
    build_server(sys.argv[1], Path(sys.argv[2])).run(transport="stdio")

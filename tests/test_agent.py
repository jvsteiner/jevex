import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from jevex.agent import Agent
from jevex.jev import Jev
from jevex.mcp_tools import connect_tools
from jevex.writer import Writer

DOCUMENTS = Path(__file__).parents[1] / "examples" / "documents"


class Decisions:
    def __init__(self, *choices):
        self.choices = iter(choices)
        self.states = []

    async def choose(self, state, instructions, options):
        self.states.append(json.loads(json.dumps(state)))
        value = next(self.choices)
        if isinstance(value, tuple):
            choice, confidence = value
        else:
            choice, confidence = value, 1.0
        return {"choice": choice, "confidence": confidence}


def writer(*responses):
    return Writer(FakeListChatModel(responses=list(responses)))


async def test_real_mcp_and_http_contract_with_scripted_models():
    choices = iter(
        ["documents.read_document", "prices.md", "execute", "math.multiply", "execute", "answer"]
    )
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.path == "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test"
        choice = next(choices)
        assert choice in payload["questions"]["decision"]["criteria"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    "decision": {
                        "type": "choice",
                        "choice": choice,
                        "confidence": 0.95,
                        "probabilities": {choice: 1.0},
                    }
                },
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )

    async with (
        httpx.AsyncClient(
            base_url="https://api.typesafe.ai",
            transport=httpx.MockTransport(respond),
            headers={"Authorization": "Bearer test"},
        ) as client,
        connect_tools(DOCUMENTS) as tools,
    ):
        jev = Jev(client)
        llm = writer("[12, 3]", "Three notebooks cost 36 EUR.")
        result = await Agent(jev, llm, tools).run(
            "Read prices.md and tell me the cost of three notebooks."
        )
        assert result.status == "answer"
        assert result.state["events"][1]["arguments"] == {"values": [12, 3]}
        assert float(result.state["events"][1]["result"]) == 36
        assert jev.usage == {"calls": 6, "input_tokens": 60, "output_tokens": 12}
        assert llm.usage["calls"] == 2
        assert "proposed_call" in requests[2]["state"]
        for prompt in llm.prompts:
            text = " ".join(message.content for message in prompt)
            for forbidden in (
                "documents.read_document",
                "math.multiply",
                "inputSchema",
                "additionalProperties",
                "next action",
                "confidence",
            ):
                assert forbidden not in text
            assert [message.type for message in prompt] == ["system", "human"]


async def test_all_twelve_tools_over_real_mcp():
    async with connect_tools(DOCUMENTS) as tools:
        assert len(tools) == 12
        assert "prices.md" in await tools["documents.list_documents"].call({})
        assert "notebook" in await tools["documents.search_documents"].call({"query": "notebook"})
        assert "12 EUR" in await tools["documents.read_document"].call({"name": "prices.md"})
        for name, arguments, expected in [
            ("add", {"values": [2, 3]}, 5),
            ("subtract", {"a": 7, "b": 4}, 3),
            ("multiply", {"values": [12, 3]}, 36),
            ("divide", {"a": 12, "b": 4}, 3),
            ("mean", {"values": [18, 24, 30]}, 24),
        ]:
            assert float(await tools[f"math.{name}"].call(arguments)) == expected
        assert "2026-10-15" in await tools["calendar.add_days"].call(
            {"date": "2026-10-08", "days": 7}
        )
        assert "Thursday" in await tools["calendar.weekday"].call({"date": "2026-10-15"})
        assert (
            int(
                await tools["calendar.days_between"].call(
                    {"start": "2026-10-08", "end": "2026-10-15"}
                )
            )
            == 7
        )
        from datetime import date

        date.fromisoformat((await tools["calendar.today"].call({})).strip('"'))
        with pytest.raises(ValueError):
            await tools["documents.read_document"].call({"name": "../../.env"})
        with pytest.raises(ValueError):
            await tools["math.divide"].call({"a": 3, "b": 0})


def counting_tool(name="math.multiply", *, fail=False):
    calls = []

    async def call(arguments):
        calls.append(arguments)
        if fail:
            raise ValueError("tool unavailable")
        return "36"

    return SimpleNamespace(
        description="Multiply numbers",
        name=name,
        schema={
            "type": "object",
            "properties": {
                "values": {
                    "type": "array",
                    "items": {"type": "number"},
                }
            },
            "required": ["values"],
        },
        call=call,
    ), calls


@pytest.mark.parametrize("proposal", ['{"tool":"delete"}', "not JSON", '["twelve", 3]', "[NaN]"])
async def test_invalid_content_cannot_dispatch(proposal):
    tool, calls = counting_tool()
    result = await Agent(
        Decisions("math.multiply"), writer(proposal), {"math.multiply": tool}, max_steps=1
    ).run("Multiply twelve by three")
    assert result.status == "limit"
    assert not calls
    assert result.state["events"][0]["ok"] is False


async def test_jev_rejection_prevents_execution():
    tool, calls = counting_tool()
    result = await Agent(
        Decisions("math.multiply", "reject", "clarify"),
        writer("[999, 3]", "How many notebooks?"),
        {"math.multiply": tool},
    ).run("What do the notebooks cost?")
    assert not calls
    assert result.status == "clarify"


async def test_low_confidence_never_calls_writer_or_tool():
    tool, calls = counting_tool()
    llm = writer("must not be used")
    result = await Agent(Decisions(("math.multiply", 0.1)), llm, {"math.multiply": tool}).run(
        "Calculate it"
    )
    assert result.status == "uncertain"
    assert not calls and not llm.prompts


async def test_no_argument_tool_skips_writer():
    tool, calls = counting_tool("documents.list_documents")
    tool.schema = {"type": "object", "properties": {}}
    llm = writer("Here are the documents.")
    result = await Agent(
        Decisions("documents.list_documents", "execute", "answer"),
        llm,
        {"documents.list_documents": tool},
    ).run("List documents")
    assert result.status == "answer"
    assert calls == [{}]
    assert llm.usage["calls"] == 1


async def test_repeated_calls_stop_and_tool_failures_reach_jev():
    tool, calls = counting_tool(fail=True)
    jev = Decisions("math.multiply", "execute", "math.multiply", "execute")
    result = await Agent(jev, writer("[12,3]"), {"math.multiply": tool}).run("12 times 3")
    assert result.status == "stalled"
    assert len(calls) == 1
    assert jev.states[2]["events"][0]["error"] == "tool unavailable"


async def test_unavailable_decision_is_rejected():
    with pytest.raises(ValueError, match="unavailable"):
        await Agent(Decisions("shell.delete"), writer("unused"), {}).run("Hello")


async def test_writer_rejects_native_tool_calls():
    class BadModel:
        async def ainvoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[{"name": "math.multiply", "args": {"values": [12, 3]}, "id": "bad"}],
            )

    with pytest.raises(ValueError, match="tool call"):
        await Writer(BadModel()).write("Write a number", "twelve")


async def test_jev_http_errors_do_not_become_answers():
    async with httpx.AsyncClient(
        base_url="https://api.typesafe.ai",
        transport=httpx.MockTransport(lambda _: httpx.Response(401)),
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await Jev(client).choose({}, "Choose", {"a": "A", "b": "B"})


async def test_empty_completion_usage_is_counted():
    class EmptyModel:
        async def ainvoke(self, messages):
            return AIMessage(
                content="",
                usage_metadata={
                    "input_tokens": 15,
                    "output_tokens": 400,
                    "total_tokens": 415,
                },
            )

    llm = Writer(EmptyModel())
    with pytest.raises(ValueError, match="plain text"):
        await llm.write("Copy a number", "12")
    assert llm.usage == {"calls": 1, "input_tokens": 15, "output_tokens": 400}


def test_nested_provider_errors_are_readable():
    from jevex.cli import error_messages

    error = ExceptionGroup("MCP", [ExceptionGroup("session", [httpx.ConnectError("offline")])])
    assert error_messages(error) == "offline"

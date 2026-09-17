import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from jevex.benchmark import check_answer, report
from jevex.external import execute
from jevex.investigation import Investigator, baseline
from jevex.measurement import Meter, savings
from jevex.research import Researcher, check_research, retrieved_urls


def test_truncated_batch_does_not_count_undelivered_pages():
    urls = ["https://example.org/one", "https://example.org/two"]
    event = {
        "ok": True,
        "tool": "exa__web_fetch_exa",
        "arguments": {"urls": urls},
        "result": "# First\nURL: " + urls[0] + "\n" + "Evidence " * 60,
    }
    assert retrieved_urls([event]) == urls[:1]


async def test_search_budget_preserves_later_source_urls(tmp_path):
    async def call(arguments):
        return (
            "Title: First\nURL: https://one.example\n"
            + "x" * 20000
            + "\nTitle: Second\nURL: https://two.example\nEvidence"
        )

    tools = {"exa__web_search_exa": SimpleNamespace(schema={"type": "object"}, call=call)}
    result = await execute(tools, "exa__web_search_exa", {}, tmp_path)
    assert "https://one.example" in result
    assert "https://two.example" in result
    assert len(result) <= 12000


async def test_research_failed_argument_does_not_repeat_same_action():
    class Jev:
        def __init__(self):
            self.calls = 0

        async def choose(self, state, instruction, options):
            self.calls += 1
            if self.calls == 1:
                return {"choice": "web__fetch", "confidence": 1}
            assert "web__fetch" not in options
            return {"choice": "stop", "confidence": 1}

    agent = Researcher(
        Jev(),
        None,
        {"web__fetch": SimpleNamespace(description="Fetch")},
        lambda _: None,
        ["Question"],
    )
    status, _, state = await agent.run("Research something")
    assert status == "stopped"
    assert "No unread source URLs" in state["events"][0]["error"]


async def test_research_query_writer_gets_brief_but_no_catalog():
    class Jev:
        async def choose(self, state, instruction, options):
            return {"choice": "v0", "confidence": 1}

    model = Model(response("NASA Bennu January 2025 amino acids"))
    agent = Researcher(Jev(), model, {}, lambda _: None, ["What was found?"])
    args = await agent.arguments(
        {"request": "Check January 2025 Bennu findings", "events": []}, "exa__web_search_exa"
    )
    assert args["query"] == "NASA Bennu January 2025 amino acids"
    sent = json.dumps([m.model_dump() for m in model.messages[0]])
    assert "January 2025" in sent
    assert "exa__" not in sent and "numResults" not in sent


def test_research_citations_require_actual_primary_retrieval():
    task = {"answer_patterns": ["fact"], "primary_domains": ["example.org"]}
    urls = ["https://example.org/one", "https://example.org/two"]
    events = [
        {
            "ok": True,
            "tool": "web__fetch",
            "arguments": {"url": url},
            "result": "Source evidence. " * 30,
        }
        for url in urls
    ]
    answer = "fact " + " ".join(urls)
    assert check_research(task, "answer", answer, events)["passed"]
    assert not check_research(task, "answer", answer, events[:1])["passed"]
    assert not check_research(task, "answer", answer + " https://example.org/unread", events)[
        "passed"
    ]


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.messages = []

    async def ainvoke(self, messages):
        self.messages.append(list(messages))
        return next(self.responses)


def response(text="", tool_calls=None):
    return AIMessage(
        content=text,
        tool_calls=tool_calls or [],
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_token_details": {"cache_read": 40},
            "output_token_details": {"reasoning": 5},
        },
    )


def fake_tools(root):
    async def call(arguments):
        return "Declared Python requirement: >=3.8"

    return {
        "files__read_text_file": SimpleNamespace(
            name="files__read_text_file",
            description="Read text",
            call=call,
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    }


@pytest.mark.parametrize("compact", [True, False])
async def test_baselines_retrieve_and_keep_evidence(tmp_path, compact):
    model = Model(
        response(
            tool_calls=[
                {
                    "id": "c1",
                    "name": "files__read_text_file",
                    "args": {"path": str(tmp_path / "setup.py")},
                }
            ]
        ),
        response("Python >=3.8 (setup.py)"),
    )
    meter = Meter(model, "gpt-4.1-mini", lambda _: None)
    status, answer, state = await baseline(
        meter,
        fake_tools(tmp_path),
        tmp_path,
        "Check minimum Python",
        ["setup.py"],
        lambda _: None,
        3,
        compact=compact,
    )
    assert status == "answer" and "3.8" in answer
    assert state["events"][0]["ok"]
    assert "Declared Python requirement" in json.dumps([m.model_dump() for m in model.messages[1]])
    assert meter.totals()["input_tokens"] == 200
    assert meter.totals()["cached_input_tokens"] == 80
    assert meter.totals()["reasoning_tokens"] == 10


async def test_jev_selects_path_without_writer_metadata(tmp_path):
    class Jev:
        def __init__(self):
            self.choices = iter(["files__read_text_file", "v0", "execute", "answer"])

        async def choose(self, state, instruction, options):
            choice = next(self.choices)
            assert choice in options
            return {"choice": choice, "confidence": 0.9}

    model = Model(response("Python >=3.8 (setup.py)"))
    meter = Meter(model, "gpt-4.1-mini", lambda _: None)
    status, _, _ = await Investigator(
        Jev(),
        meter,
        fake_tools(tmp_path),
        tmp_path,
        ["setup.py"],
        lambda _: None,
    ).run("Check minimum Python")
    assert status == "answer" and len(model.messages) == 1
    sent = json.dumps([m.model_dump() for m in model.messages[0]])
    for forbidden in ("files__read_text_file", "properties", "tool_call", "inputSchema"):
        assert forbidden not in sent


async def test_scope_and_allowlist_are_enforced(tmp_path):
    tools = fake_tools(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        await execute(
            tools, "files__read_text_file", {"path": str(tmp_path.parent / "secret")}, tmp_path
        )
    with pytest.raises(ValueError, match="allowlist"):
        await execute(tools, "files__write_file", {}, tmp_path)


async def test_writer_accepts_responses_api_text_blocks():
    from jevex.writer import Writer

    model = Model(AIMessage(content=[{"type": "text", "text": "Observed answer."}]))
    assert await Writer(model).write("Answer", "Evidence") == "Observed answer."


async def test_no_more_candidates_keeps_selected_batch(tmp_path):
    class Jev:
        def __init__(self):
            self.choices = iter(["v0", "more", "none"])

        async def choose(self, state, instruction, options):
            return {"choice": next(self.choices), "confidence": 1}

    tool = SimpleNamespace(schema={"properties": {"paths": {}}, "required": ["paths"]})
    agent = Investigator(
        Jev(),
        None,
        {"files__read_multiple_files": tool},
        tmp_path,
        ["a.py", "b.py"],
        lambda _: None,
    )
    assert await agent.arguments({"events": []}, "files__read_multiple_files") == {
        "paths": [str(tmp_path / "a.py")]
    }


def test_unavailable_source_needs_a_real_failed_attempt():
    task = {
        "answer_patterns": ["local"],
        "evidence_groups": [["https://example.com"]],
        "allow_unavailable": True,
    }
    answer = "The local metadata is known, but the remote source is unavailable."
    assert not check_answer(task, "answer", answer, [])["passed"]
    events = [
        {"ok": False, "arguments": {"url": "https://example.com"}, "error": "robots disallows"}
    ]
    result = check_answer(task, "answer", answer, events)
    assert result["passed"] and result["outcome"] == "source_unavailable"


def test_answer_without_source_does_not_pass():
    task = {"answer_patterns": ["3.8"], "evidence_groups": [["setup.py"]]}
    assert not check_answer(task, "answer", "Python 3.8", [])["passed"]
    events = [{"ok": True, "arguments": {"path": "/repo/setup.py"}}]
    assert check_answer(task, "answer", "Python 3.8", events)["passed"]


@pytest.mark.parametrize("manual_failure", [False, True])
def test_failed_runs_do_not_count_as_savings(manual_failure):
    usage = {
        "input_tokens": 100,
        "output_tokens": 10,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "calls": 1,
    }
    row = {
        "task": "a",
        "repeat": 1,
        "engine": "jev",
        "status": "limit",
        "checks": {"passed": manual_failure},
        "manual_review": {"passed": False, "note": "Unsupported detail"} if manual_failure else {},
        "llm": usage,
        "jev": {"input_tokens": 300, "output_tokens": 10},
        "tool_calls": 1,
        "seconds": 1,
    }
    text = report(
        [row, {**row, "engine": "standard", "checks": {"passed": True}, "manual_review": {}}],
        {
            "model": "test",
            "commit": "abc",
            "tool_count": 16,
            "repeats": 1,
            "catalog_tokens_estimate": 3000,
        },
    )
    assert "no jointly passing pairs" in text
    assert savings(100, 25) == 75
    assert savings(0, 25) is None

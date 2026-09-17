"""Provider usage is measured; tokenized schema sizes are explicitly estimates."""

import json
import time

import tiktoken


def estimate_tokens(value, model):
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("o200k_base")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return len(encoding.encode(text, disallowed_special=()))


class Meter:
    def __init__(self, model, model_name, trace, tool_schemas=None):
        self.model = model
        self.model_name = model_name
        self.trace = trace
        self.tool_schemas = tool_schemas or []
        self.calls = []

    async def ainvoke(self, messages):
        start = time.perf_counter()
        response = await self.model.ainvoke(messages)
        usage = response.usage_metadata
        if not usage:
            raise ValueError("Provider returned no usage metadata; cannot measure this run")
        call = {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cached_input_tokens": usage.get("input_token_details", {}).get("cache_read", 0),
            "reasoning_tokens": usage.get("output_token_details", {}).get("reasoning", 0),
            "seconds": time.perf_counter() - start,
            "schema_tokens_estimate": estimate_tokens(self.tool_schemas, self.model_name)
            if self.tool_schemas
            else 0,
        }
        self.calls.append(call)
        self.trace(
            {
                "kind": "llm",
                **call,
                "messages": [m.model_dump() for m in messages],
                "response": response.model_dump(),
            }
        )
        return response

    def totals(self):
        keys = (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "seconds",
            "schema_tokens_estimate",
        )
        return {"calls": len(self.calls), **{key: sum(c[key] for c in self.calls) for key in keys}}


def savings(baseline, candidate):
    return None if baseline == 0 else round(100 * (baseline - candidate) / baseline, 1)

import asyncio
import math
from typing import Any

import httpx


class Jev:
    """Small adapter for the documented TypeSafe HTTP API."""

    def __init__(self, client: httpx.AsyncClient, model: str = "jev-latest"):
        self.client = client
        self.model = model
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    async def choose(self, state: dict, instructions: str, options: dict[str, str]) -> dict:
        if not 2 <= len(options) <= 255:
            raise ValueError("Choice requires 2–255 options")
        for attempt in range(3):
            response = await self.client.post(
                "/v1/systemone",
                json={
                    "model": self.model,
                    "state": state,
                    "questions": {
                        "decision": {
                            "type": "choice",
                            "instructions": instructions,
                            "criteria": options,
                        }
                    },
                },
            )
            if response.status_code not in {429, 502, 503, 529} or attempt == 2:
                break
            await asyncio.sleep(2**attempt)
        response.raise_for_status()
        payload = response.json()
        answer: dict[str, Any] = payload["answers"]["decision"]
        confidence = answer.get("confidence")
        if (
            answer.get("type") != "choice"
            or answer.get("choice") not in options
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid Jev choice response")
        self.usage["calls"] += 1
        for key in ("input_tokens", "output_tokens"):
            self.usage[key] += payload.get("usage", {}).get(key, 0)
        return answer

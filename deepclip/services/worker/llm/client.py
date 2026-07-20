"""Claude API client seam.

Everything LLM-shaped goes through `LLMClient` so the pipeline can be tested
without a key and without network. `AnthropicClient` is the real one;
`FakeLLMClient` is what the test suite uses.

Model split follows the spec (C1): Haiku-class for bulk per-segment
classification, Sonnet-class for outline, ranking and assembly.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)

# Bulk classification. Cheap, runs over every segment.
MODEL_FAST = "claude-haiku-4-5-20251001"
# Outline, assembly, judging. Runs a handful of times per page.
MODEL_SMART = "claude-sonnet-5"

MAX_RETRIES = 3


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLMClient(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str = MODEL_SMART,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


class AnthropicClient:
    """Real client. Requires ANTHROPIC_API_KEY."""

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        import anthropic  # imported lazily so the package is optional offline

        self._client = anthropic.Anthropic(api_key=key)
        self.usage = CostTracker()

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str = MODEL_SMART,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                msg = self._client.messages.create(**kwargs)
            except Exception as exc:  # network/rate-limit
                last_exc = exc
                log.warning("LLM call failed (attempt %d): %s", attempt + 1, exc)
                continue
            text = "".join(
                block.text for block in msg.content if getattr(block, "type", "") == "text"
            )
            resp = LLMResponse(
                text=text,
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
                model=model,
            )
            self.usage.record(resp)
            return resp
        raise LLMError(f"LLM call failed after {MAX_RETRIES} attempts: {last_exc}")


class FakeLLMClient:
    """Deterministic stand-in for tests.

    Responses are queued or resolved by matching a substring of the prompt, so a
    test states exactly what the model is pretending to return.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        by_substring: dict[str, str] | None = None,
        default: str = "{}",
    ):
        self._queue = list(responses or [])
        self._by_substring = by_substring or {}
        self._default = default
        self.calls: list[dict[str, Any]] = []
        self.usage = CostTracker()

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str = MODEL_SMART,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append({"prompt": prompt, "system": system, "model": model})
        for needle, response in self._by_substring.items():
            if needle in prompt:
                return LLMResponse(text=response, model=model)
        if self._queue:
            return LLMResponse(text=self._queue.pop(0), model=model)
        return LLMResponse(text=self._default, model=model)


# Prices per million tokens (USD). Update alongside model choices; the cost
# model in C8 is a stated constraint, so builds should be able to report spend.
PRICING = {
    MODEL_FAST: {"input": 1.00, "output": 5.00},
    MODEL_SMART: {"input": 3.00, "output": 15.00},
}


@dataclass
class CostTracker:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    per_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, resp: LLMResponse) -> None:
        self.calls += 1
        self.input_tokens += resp.input_tokens
        self.output_tokens += resp.output_tokens
        bucket = self.per_model.setdefault(resp.model, {"input": 0, "output": 0})
        bucket["input"] += resp.input_tokens
        bucket["output"] += resp.output_tokens

    @property
    def cost_usd(self) -> float:
        total = 0.0
        for model, toks in self.per_model.items():
            price = PRICING.get(model)
            if not price:
                continue
            total += toks["input"] / 1e6 * price["input"]
            total += toks["output"] / 1e6 * price["output"]
        return total


# -- JSON extraction ---------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse JSON out of a model response.

    Models wrap JSON in prose or fences even when told not to, and a whole page
    build should not die because of a stray "Here's the JSON:". Tries the raw
    string, then fenced blocks, then the outermost brace/bracket span.
    """
    if text is None:
        raise LLMError("no text to parse")
    candidates = [text.strip()]

    fenced = _FENCE.findall(text)
    candidates.extend(f.strip() for f in fenced)

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise LLMError(f"could not parse JSON from response: {text[:200]!r}")


def build_client() -> LLMClient:
    """Real client if a key exists, else raise with a clear message."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — LLM pipeline stages cannot run. "
            "Set it, or inject a FakeLLMClient for offline work."
        )
    return AnthropicClient()

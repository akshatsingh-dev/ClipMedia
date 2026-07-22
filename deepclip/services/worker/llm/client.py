"""LLM client seam (provider-agnostic).

Everything LLM-shaped goes through `LLMClient` so the pipeline can be tested
without a key and without network, and so the provider can be swapped without
touching a single pipeline stage. `AnthropicClient` and `GeminiClient` are the
real ones; `FakeLLMClient` is what the test suite uses. `build_client()` picks
the provider from the environment.

Model split follows the spec (C1): a fast tier for bulk per-segment
classification, a smart tier for outline, ranking and assembly. The pipeline
always refers to the two tiers by the `MODEL_FAST` / `MODEL_SMART` constants
below; each real client maps those tier keys to its own model names, so the
pipeline never hard-codes a provider's model IDs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)

# Canonical tier keys. Their *values* are Anthropic IDs for historical reasons,
# but the pipeline treats them as opaque tier tokens — GeminiClient maps them to
# Gemini models. Do not read a provider into these strings anywhere but a client.
# Bulk classification. Cheap, runs over every segment.
MODEL_FAST = "claude-haiku-4-5-20251001"
# Outline, assembly, judging. Runs a handful of times per page.
MODEL_SMART = "claude-sonnet-5"

# Gemini model names for each tier. Env-overridable because model names churn
# faster than code, and a rename should not need a redeploy.
# The "-latest" aliases are used deliberately: querying the live model list
# during setup showed pinned versions (gemini-2.5-*) get retired for new keys,
# and pro is quota-blocked on the free tier. flash-lite handles bulk scoring;
# flash handles outline/assembly. Override via env if a key has pro access.
GEMINI_MODEL_FAST = os.environ.get("GEMINI_MODEL_FAST", "gemini-flash-lite-latest")
GEMINI_MODEL_SMART = os.environ.get("GEMINI_MODEL_SMART", "gemini-flash-latest")

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


def _gemini_text(resp: Any) -> str:
    """Pull text out of a Gemini response, tolerating blocked/empty candidates.

    google-genai's `resp.text` raises rather than returning None when the
    response was blocked by a safety filter or has no text part, so it is
    wrapped and the candidate parts are assembled as a fallback. A genuinely
    empty response raises LLMError, which the retry/degradation paths handle.
    """
    try:
        text = resp.text
        if text:
            return text
    except Exception:  # noqa: BLE001 - .text raises on blocked responses
        pass

    parts: list[str] = []
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            piece = getattr(part, "text", None)
            if piece:
                parts.append(piece)
    if parts:
        return "".join(parts)
    raise LLMError("Gemini returned no text (possibly blocked by a safety filter)")


class GeminiClient:
    """Real client for Google Gemini. Requires GEMINI_API_KEY.

    The pipeline passes the canonical tier constants (`MODEL_FAST`/`MODEL_SMART`);
    this maps them to Gemini models. A string that is already a Gemini model name
    passes through unchanged, so callers can override per-call if they need to.

    `client` is injectable so the parsing and cost paths are testable without the
    SDK or a key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        client: Any | None = None,
        model_fast: str | None = None,
        model_smart: str | None = None,
    ):
        self._model_fast = model_fast or GEMINI_MODEL_FAST
        self._model_smart = model_smart or GEMINI_MODEL_SMART
        self.usage = CostTracker()
        if client is not None:
            self._client = client
            return
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        from google import genai  # imported lazily so the package is optional

        self._client = genai.Client(api_key=key)

    def _map_model(self, model: str) -> str:
        if model == MODEL_FAST:
            return self._model_fast
        if model == MODEL_SMART:
            return self._model_smart
        return model  # already a Gemini id, or an explicit override

    @staticmethod
    def _config(system: str | None, temperature: float, max_tokens: int) -> Any:
        # Built through the SDK's type when present; a plain dict is enough for a
        # fake transport in tests, where the SDK is not installed.
        try:
            from google.genai import types

            return types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                system_instruction=system or None,
            )
        except ImportError:
            return {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "system_instruction": system,
            }

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str = MODEL_SMART,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        gemini_model = self._map_model(model)
        config = self._config(system, temperature, max_tokens)

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                raw = self._client.models.generate_content(
                    model=gemini_model, contents=prompt, config=config
                )
            except Exception as exc:  # network/rate-limit
                last_exc = exc
                log.warning("Gemini call failed (attempt %d): %s", attempt + 1, exc)
                continue
            usage = getattr(raw, "usage_metadata", None)
            resp = LLMResponse(
                text=_gemini_text(raw),
                input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
                model=gemini_model,
            )
            self.usage.record(resp)
            return resp
        raise LLMError(f"Gemini call failed after {MAX_RETRIES} attempts: {last_exc}")


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
# Gemini figures are approximate list prices and should be checked against
# current pricing before relying on the reported cost.
PRICING = {
    MODEL_FAST: {"input": 1.00, "output": 5.00},
    MODEL_SMART: {"input": 3.00, "output": 15.00},
    GEMINI_MODEL_FAST: {"input": 0.10, "output": 0.40},
    GEMINI_MODEL_SMART: {"input": 0.30, "output": 2.50},
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
    """Pick a real client from the environment.

    Selection order:
      1. `LLM_PROVIDER` if set ("gemini" | "anthropic") — explicit wins.
      2. else whichever key is present, Gemini preferred when both are.
      3. else raise with a message naming both options.
    """
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not provider:
        if os.environ.get("GEMINI_API_KEY"):
            provider = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            raise RuntimeError(
                "No LLM key set — pipeline stages cannot run. Set GEMINI_API_KEY "
                "(the project default) or ANTHROPIC_API_KEY, optionally with "
                "LLM_PROVIDER to force one. Or inject a FakeLLMClient offline."
            )
    if provider == "gemini":
        return GeminiClient()
    if provider == "anthropic":
        return AnthropicClient()
    raise RuntimeError(
        f"unknown LLM_PROVIDER {provider!r}; expected 'gemini' or 'anthropic'"
    )

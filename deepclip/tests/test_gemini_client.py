"""GeminiClient and provider selection.

The real Gemini SDK is not installed and there is no key, so these inject a fake
transport shaped like google-genai's response objects. That covers everything
except the actual network call: tier mapping, response parsing (including the
blocked-response path), token accounting, cost, retry, and provider selection.
"""

import types as pytypes

import pytest

from services.worker.llm import client as llm
from services.worker.llm.client import (
    GEMINI_MODEL_FAST,
    GEMINI_MODEL_SMART,
    MODEL_FAST,
    MODEL_SMART,
    GeminiClient,
    LLMError,
    build_client,
)


# -- fake google-genai response shapes ----------------------------------


def make_usage(inp, out):
    return pytypes.SimpleNamespace(prompt_token_count=inp, candidates_token_count=out)


def text_response(text, inp=10, out=20):
    return pytypes.SimpleNamespace(text=text, usage_metadata=make_usage(inp, out))


def blocked_response():
    """resp.text raises, mimicking google-genai on a safety block."""

    class Blocked:
        @property
        def text(self):
            raise ValueError("blocked by safety filter")

        candidates = []
        usage_metadata = make_usage(5, 0)

    return Blocked()


def parts_response(pieces):
    """No top-level .text, but candidate parts carry text."""
    part_objs = [pytypes.SimpleNamespace(text=p) for p in pieces]
    content = pytypes.SimpleNamespace(parts=part_objs)
    cand = pytypes.SimpleNamespace(content=content)
    return pytypes.SimpleNamespace(text="", candidates=[cand], usage_metadata=make_usage(3, 4))


class FakeGenaiClient:
    """Stands in for genai.Client(). Records calls, returns a queued response."""

    def __init__(self, responses=None, raises=None):
        self._responses = list(responses or [])
        self._raises = list(raises or [])
        self.calls = []
        self.models = self  # so .models.generate_content resolves to us

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc
        if self._responses:
            return self._responses.pop(0)
        return text_response("{}")


# -- tier mapping -------------------------------------------------------


def test_smart_tier_maps_to_gemini_pro():
    fake = FakeGenaiClient([text_response("ok")])
    GeminiClient(client=fake).complete("hi", model=MODEL_SMART)
    assert fake.calls[0]["model"] == GEMINI_MODEL_SMART


def test_fast_tier_maps_to_gemini_flash():
    fake = FakeGenaiClient([text_response("ok")])
    GeminiClient(client=fake).complete("hi", model=MODEL_FAST)
    assert fake.calls[0]["model"] == GEMINI_MODEL_FAST


def test_explicit_gemini_model_passes_through():
    fake = FakeGenaiClient([text_response("ok")])
    GeminiClient(client=fake).complete("hi", model="gemini-3.0-experimental")
    assert fake.calls[0]["model"] == "gemini-3.0-experimental"


def test_custom_tier_overrides():
    fake = FakeGenaiClient([text_response("ok")])
    c = GeminiClient(client=fake, model_smart="gemini-custom")
    c.complete("hi", model=MODEL_SMART)
    assert fake.calls[0]["model"] == "gemini-custom"


# -- response parsing ---------------------------------------------------


def test_parses_text_and_tokens():
    fake = FakeGenaiClient([text_response("hello world", inp=100, out=50)])
    resp = GeminiClient(client=fake).complete("hi")
    assert resp.text == "hello world"
    assert resp.input_tokens == 100
    assert resp.output_tokens == 50
    assert resp.model == GEMINI_MODEL_SMART


def test_blocked_response_falls_back_then_raises():
    fake = FakeGenaiClient([blocked_response()])
    with pytest.raises(LLMError, match="no text"):
        GeminiClient(client=fake).complete("hi")


def test_assembles_candidate_parts_when_text_empty():
    fake = FakeGenaiClient([parts_response(["chunk one ", "chunk two"])])
    resp = GeminiClient(client=fake).complete("hi")
    assert resp.text == "chunk one chunk two"


def test_missing_usage_metadata_is_zero_not_crash():
    resp_obj = pytypes.SimpleNamespace(text="ok", usage_metadata=None)
    fake = FakeGenaiClient([resp_obj])
    resp = GeminiClient(client=fake).complete("hi")
    assert resp.input_tokens == 0
    assert resp.output_tokens == 0


# -- retry --------------------------------------------------------------


def test_retries_then_succeeds():
    fake = FakeGenaiClient(
        responses=[text_response("recovered")],
        raises=[RuntimeError("transient"), None],
    )
    resp = GeminiClient(client=fake).complete("hi")
    assert resp.text == "recovered"
    assert len(fake.calls) == 2


def test_gives_up_after_max_retries():
    fake = FakeGenaiClient(raises=[RuntimeError("down")] * 5)
    with pytest.raises(LLMError, match="after 3 attempts"):
        GeminiClient(client=fake).complete("hi")


# -- cost tracking ------------------------------------------------------


def test_cost_accrues_on_gemini_pricing():
    fake = FakeGenaiClient([text_response("ok", inp=1_000_000, out=0)])
    c = GeminiClient(client=fake)
    c.complete("hi", model=MODEL_SMART)
    # smart-tier (flash) input list price is $0.30 / 1M in the pricing table
    assert c.usage.cost_usd == pytest.approx(0.30)


def test_system_instruction_passed_through():
    fake = FakeGenaiClient([text_response("ok")])
    GeminiClient(client=fake).complete("hi", system="be terse")
    cfg = fake.calls[0]["config"]
    # Dict form is used when the SDK types are absent (the test environment).
    value = cfg["system_instruction"] if isinstance(cfg, dict) else cfg.system_instruction
    assert value == "be terse"


# -- provider selection -------------------------------------------------


def test_build_client_prefers_gemini_when_key_present(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.setattr(llm, "GeminiClient", lambda: "GEMINI")
    monkeypatch.setattr(llm, "AnthropicClient", lambda: "ANTHROPIC")
    assert build_client() == "GEMINI"


def test_build_client_uses_anthropic_when_only_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.setattr(llm, "AnthropicClient", lambda: "ANTHROPIC")
    assert build_client() == "ANTHROPIC"


def test_explicit_provider_overrides_autodetect(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(llm, "AnthropicClient", lambda: "ANTHROPIC")
    assert build_client() == "ANTHROPIC"


def test_build_client_raises_with_no_keys(monkeypatch):
    for var in ("LLM_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="No LLM key"):
        build_client()


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "cohere")
    with pytest.raises(RuntimeError, match="unknown LLM_PROVIDER"):
        build_client()


def test_gemini_client_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiClient()

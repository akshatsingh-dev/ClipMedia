import pytest

from services.worker.llm.client import FakeLLMClient
from services.worker.pipeline.tutor import answer_question


def test_answers_from_transcript():
    llm = FakeLLMClient(responses=["Gandhi walked 240 miles to Dandi to make salt."])
    r = answer_question("The march to Dandi covered 240 miles.", "How far was the march?", llm)
    assert r["grounded"] is True
    assert "240" in r["answer"]


def test_uses_fast_model():
    llm = FakeLLMClient(responses=["answer"])
    answer_question("transcript", "q", llm)
    assert llm.calls[0]["model"] == "claude-haiku-4-5-20251001"


def test_ungrounded_when_clip_does_not_cover():
    llm = FakeLLMClient(responses=["The clip doesn't cover that. It's about the sea march."])
    r = answer_question("transcript about walking", "What year did he die?", llm)
    assert r["grounded"] is False


def test_empty_transcript_returns_ungrounded():
    llm = FakeLLMClient()
    r = answer_question("", "anything", llm)
    assert r["grounded"] is False
    assert llm.calls == []  # no LLM call when there's nothing to ground in


def test_empty_question_raises():
    with pytest.raises(ValueError):
        answer_question("transcript", "", FakeLLMClient())


def test_question_truncated():
    llm = FakeLLMClient(responses=["ok"])
    answer_question("transcript", "x" * 1000, llm)
    # prompt should contain a truncated question, not 1000 chars
    assert len(llm.calls[0]["prompt"]) < 7000


def test_llm_failure_degrades():
    from services.worker.llm.client import LLMError

    class Boom:
        def complete(self, *a, **k):
            raise LLMError("down")

    r = answer_question("transcript", "q", Boom())
    assert r["grounded"] is False
    assert "again" in r["answer"].lower()

"""'Ask about this clip' tutor (master doc B1, the Pathio steal).

A context-aware tutor that answers questions about the clip the user is watching.
Nearly free to build: the transcript segment is already stored, so answering is
one grounded LLM call with no extra retrieval.

The load-bearing rule mirrors assembly's: **answer only from the transcript
provided.** The product's whole promise is real footage, and a tutor that
confabulates beyond what the clip actually says breaks that as badly as a
hallucinated bridge would. When the transcript does not contain the answer, the
tutor says so rather than reaching for outside knowledge.
"""

from __future__ import annotations

import logging

from ..llm.client import MODEL_FAST, LLMClient, LLMError

log = logging.getLogger(__name__)

MAX_QUESTION_LEN = 500
MAX_ANSWER_TOKENS = 512

SYSTEM = """You answer a viewer's question about one specific video clip, using \
ONLY the transcript excerpt provided.

Rules:
- Ground every claim in the transcript. Do not add facts, dates, names, or \
context that are not in it.
- If the transcript does not contain the answer, say so plainly: "The clip \
doesn't cover that." Then, in one sentence, say what the clip IS about. Never \
fill the gap with outside knowledge.
- Two or three sentences. Plain, direct, no preamble.
- You are a study aid, not a chatbot. No pleasantries, no "great question"."""

PROMPT = """Clip transcript:
\"\"\"
{transcript}
\"\"\"

Question: {question}

Answer using only the transcript above."""


def answer_question(
    transcript: str,
    question: str,
    llm: LLMClient,
) -> dict:
    """Answer a viewer's question grounded in one clip's transcript.

    Returns {"answer": str, "grounded": bool}. `grounded` is False when the
    tutor reports the clip does not cover the question, so the UI can render
    that case differently (and so it is measurable).
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("empty question")
    if len(question) > MAX_QUESTION_LEN:
        question = question[:MAX_QUESTION_LEN]
    if not transcript or not transcript.strip():
        return {
            "answer": "There's no transcript for this clip, so I can't answer from it.",
            "grounded": False,
        }

    try:
        resp = llm.complete(
            PROMPT.format(transcript=transcript[:6000], question=question),
            system=SYSTEM,
            model=MODEL_FAST,
            max_tokens=MAX_ANSWER_TOKENS,
        )
    except LLMError as exc:
        log.warning("tutor call failed: %s", exc)
        return {"answer": "I couldn't answer that just now — try again.", "grounded": False}

    text = resp.text.strip()
    # Heuristic grounding flag: the model was told to use this exact phrasing when
    # the clip doesn't cover the question.
    grounded = "doesn't cover that" not in text.lower() and "does not cover that" not in text.lower()
    return {"answer": text, "grounded": grounded}

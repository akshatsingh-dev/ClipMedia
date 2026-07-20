"""Stage 5b — batched segment scoring, and the stage-4 name-repair pass.

Two Haiku-class jobs, both batched per video because a call per segment would
wreck the cost model (C8 budgets ~$0.10 of Haiku for a whole page):

  quality    (Learn)     substantive explanation vs. intro/ad/banter/outro.
                         Removes ~40% junk before ranking.
  intensity  (Entertain) reaction density.

`intensity` also has a pure-heuristic implementation in rank_entertain, used when
no LLM is available; the model score supersedes it when present.
"""

from __future__ import annotations

import logging
import re

from ..llm.client import MODEL_FAST, LLMClient, LLMError, extract_json
from .segment import Segment

log = logging.getLogger(__name__)

# Segments per call. Large enough to amortise the prompt, small enough that one
# malformed response doesn't cost a whole video's scores.
BATCH_SIZE = 25

QUALITY_SYSTEM = """You rate transcript segments from educational videos.

Score each segment 0.0-1.0 on whether it is SUBSTANTIVE EXPLANATION:
  1.0  teaches something concrete — mechanism, event, date, cause, argument
  0.5  relevant context or narrative, but light on substance
  0.0  intro, outro, sponsor read, subscribe request, banter, filler

Judge only what the text says. Do not reward confident tone or production value.
Output JSON only."""

INTENSITY_SYSTEM = """You rate transcript segments from entertainment videos.

Score each segment 0.0-1.0 on MOMENT INTENSITY — how much something is actually \
happening:
  1.0  peak reaction — big laugh, shock, spectacular event, payoff
  0.5  building, mildly funny, or setup for a payoff
  0.0  dead air, talking about nothing, intro, self-promo

Non-speech cues like [laughter] and [screaming] are strong evidence. Loud \
punctuation is weak evidence — hype narration is not intensity.
Output JSON only."""

PROMPT = """Score each segment. Return JSON: {{"scores":[{{"id":<id>,"score":<0.0-1.0>}}]}}
One entry per segment, same ids, no extra keys.

Segments:
{segments}"""

NAME_REPAIR_SYSTEM = """You repair proper nouns in auto-generated video captions.

Auto-captions mangle names ("Jinnah" -> "gina", "Porbandar" -> "pour bandar").
Given the expected names and a transcript chunk, fix ONLY misrendered proper \
nouns. Change nothing else — not grammar, not punctuation, not wording. If \
nothing is clearly a mangled name, return the text unchanged.
Output JSON only."""

NAME_REPAIR_PROMPT = """Expected names: {names}

Text:
{text}

Return JSON: {{"text":"<repaired text>"}}"""


def _render(segments: list[Segment]) -> str:
    lines = []
    for i, seg in enumerate(segments):
        text = seg.text.replace("\n", " ")[:600]
        lines.append(f"[{i}] ({seg.t_start:.0f}-{seg.t_end:.0f}s) {text}")
    return "\n".join(lines)


def _parse_scores(data, expected: int) -> dict[int, float]:
    """Accepts {"scores":[{"id":0,"score":0.9}]} or a bare list."""
    rows = data.get("scores") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise LLMError(f"expected a list of scores, got {type(rows).__name__}")

    out: dict[int, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row["id"])
            score = float(row["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < expected:
            out[idx] = max(0.0, min(1.0, score))
    return out


def score_segments(
    segments: list[Segment],
    llm: LLMClient,
    kind: str = "quality",
    batch_size: int = BATCH_SIZE,
    default: float = 0.5,
) -> list[float]:
    """Score every segment. Returns one float per input segment, in order.

    A failed or partial batch falls back to `default` for the affected segments
    rather than aborting — one bad response should degrade a page, not kill it.
    """
    if kind not in {"quality", "intensity"}:
        raise ValueError(f"unknown score kind: {kind!r}")
    if not segments:
        return []

    system = QUALITY_SYSTEM if kind == "quality" else INTENSITY_SYSTEM
    scores = [default] * len(segments)

    for start in range(0, len(segments), batch_size):
        batch = segments[start : start + batch_size]
        prompt = PROMPT.format(segments=_render(batch))
        try:
            resp = llm.complete(
                prompt, system=system, model=MODEL_FAST, max_tokens=2048
            )
            parsed = _parse_scores(extract_json(resp.text), len(batch))
        except (LLMError, Exception) as exc:  # noqa: BLE001 - degrade, don't die
            log.warning("scoring batch at %d failed: %s", start, exc)
            continue
        if len(parsed) < len(batch):
            log.info(
                "batch at %d returned %d/%d scores; rest default",
                start,
                len(parsed),
                len(batch),
            )
        for local_idx, score in parsed.items():
            scores[start + local_idx] = score

    return scores


def repair_names(text: str, names: list[str], llm: LLMClient) -> str:
    """Stage 4 name repair, run before embedding.

    Embedding mangled names poisons retrieval: a segment about Jinnah embedded
    as "gina" will never match the query. Cheap to fix here, impossible later.
    """
    if not text.strip() or not names:
        return text
    try:
        resp = llm.complete(
            NAME_REPAIR_PROMPT.format(names=", ".join(names), text=text[:4000]),
            system=NAME_REPAIR_SYSTEM,
            model=MODEL_FAST,
            max_tokens=2048,
        )
        data = extract_json(resp.text)
    except Exception as exc:  # noqa: BLE001
        log.warning("name repair failed: %s", exc)
        return text

    repaired = data.get("text") if isinstance(data, dict) else None
    if not isinstance(repaired, str) or not repaired.strip():
        return text

    # Guard against the model rewriting the passage instead of fixing names.
    # Length drift beyond 35% means it did something other than what we asked.
    if abs(len(repaired) - len(text)) > max(len(text) * 0.35, 40):
        log.warning("name repair changed length too much; keeping original")
        return text
    return repaired


def looks_like_junk(text: str) -> bool:
    """Cheap pre-filter run before any model call.

    Sponsor reads and subscribe requests are ~40% of the junk and are trivially
    detectable, so they should never cost a token.
    """
    lowered = text.lower()
    patterns = (
        r"\bsubscribe\b.{0,30}\bchannel\b",
        r"\bsmash that like\b",
        r"\bthis video is sponsored by\b",
        r"\buse code\b.{0,20}\bcheckout\b",
        r"\blink in the (?:description|bio)\b",
        r"\bring the bell\b",
        r"\bpatreon\b",
    )
    return any(re.search(p, lowered) for p in patterns)

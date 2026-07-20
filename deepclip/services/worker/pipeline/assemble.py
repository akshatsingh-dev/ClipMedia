"""Stage 7 — assembly into the final page JSON.

Sonnet writes the connective tissue: chapter bridges (Learn) or one-line captions
and end-card copy (Entertain), plus a "why this clip" per clip.

The load-bearing constraint (C3 stage 7): **bridges may contextualise but must
never introduce facts absent from the clips.** That is the anti-hallucination
rule for the entire product — the promise is real footage, and invented
connective text breaks it as surely as generated video would. It is enforced in
the prompt AND checked after the fact by `verify_no_new_facts`.
"""

from __future__ import annotations

import logging
import re

from ..llm.client import MODEL_SMART, LLMClient, LLMError, extract_json
from .outline import Outline
from .rank_learn import Candidate

log = logging.getLogger(__name__)

MAX_BRIDGE_SENTENCES = 3

LEARN_SYSTEM = """You assemble curated video pages. You write the connective \
tissue between real video clips.

ABSOLUTE RULE: bridge text may only contextualise what the clips already say. \
Never introduce a fact, date, name, or claim that is not present in the clip \
transcripts you are given. If you cannot write a bridge without adding \
information, write a shorter bridge that only frames what follows.

Bridges are 2-3 sentences maximum. Plain, declarative, no hype, no rhetorical \
questions, no "in this clip we see". Write for someone who will immediately \
watch the footage.

"why" is one clause on why THIS clip earned its place — what it shows that \
another clip would not.

Output JSON only."""

ENTERTAIN_SYSTEM = """You assemble curated clip feeds.

Write one short caption per clip — under 12 words, present tense, no hype \
adjectives, no emoji. Say what happens, not how good it is.

Order for pacing: open strong, vary the subject between adjacent clips, close on \
the strongest. The feed ENDS — write end-card copy that lands completion, never \
"keep scrolling".

Output JSON only."""

LEARN_PROMPT = """Page: {title}

Chapters and their selected clips (transcript excerpts are the ONLY facts \
available to you):

{chapters}

Return JSON:
{{"title":"...","chapters":[{{"title":"...","intro_text":"<2-3 sentences>",
  "clips":[{{"video_id":"...","t_start":<seconds>,"why":"..."}}]}}]}}

Keep every clip. Keep chapter order unless it is clearly wrong chronologically."""

ENTERTAIN_PROMPT = """Feed: {title}

Clips grouped by theme:

{groups}

Return JSON:
{{"title":"...","groups":[{{"label":"...","clips":[{{"video_id":"...",
  "t_start":<seconds>,"why":"<caption under 12 words>"}}]}}],
  "end_card":"<one sentence>"}}

Keep every clip."""


def _render_clip(c: Candidate) -> str:
    excerpt = c.text.replace("\n", " ")[:700]
    return (
        f'  - video_id={c.video_id} t_start={c.t_start:.0f} t_end={c.t_end:.0f} '
        f'channel="{c.channel_id}" title="{c.title[:80]}"\n'
        f"    transcript: {excerpt}"
    )


def _render_sections(sections: dict[str, list[Candidate]]) -> str:
    blocks = []
    for label, clips in sections.items():
        body = "\n".join(_render_clip(c) for c in clips)
        blocks.append(f"## {label}\n{body}")
    return "\n\n".join(blocks)


# -- fact verification -------------------------------------------------

_NUMBER = re.compile(r"\b\d{2,4}\b")
_PROPER = re.compile(r"\b[A-Z][a-z]{2,}\b")

# Words that begin sentences and would otherwise read as proper nouns.
_SENTENCE_STARTERS = {
    "The", "This", "That", "These", "Those", "His", "Her", "Their", "Its",
    "After", "Before", "During", "When", "While", "Then", "But", "And", "For",
    "From", "With", "Within", "Here", "There", "What", "Which", "Who", "Where",
    "Both", "Each", "Every", "Most", "Many", "Some", "Few", "One", "Two",
    "Later", "Earlier", "Today", "Still", "Yet", "Now", "Once", "Over",
}


def verify_no_new_facts(bridge: str, evidence: str) -> list[str]:
    """Return specifics in `bridge` that do not appear in `evidence`.

    A blunt check — numbers and proper nouns only — but those are exactly the
    hallucinations that matter on a history page (wrong dates, wrong names).
    Non-empty result means the bridge asserted something the footage never said.
    """
    if not bridge.strip():
        return []
    ev = evidence.lower()
    unsupported: list[str] = []

    for number in set(_NUMBER.findall(bridge)):
        if number not in ev:
            unsupported.append(number)

    for i, token in enumerate(re.findall(r"\S+", bridge)):
        word = token.strip(".,;:!?\"'()")
        if not _PROPER.fullmatch(word):
            continue
        if word in _SENTENCE_STARTERS:
            continue
        if i == 0 and word in _SENTENCE_STARTERS:
            continue
        if word.lower() not in ev:
            unsupported.append(word)

    return sorted(set(unsupported))


def _clip_lookup(sections: dict[str, list[Candidate]]) -> dict[tuple[str, int], Candidate]:
    """Index by (video_id, rounded t_start) — the model echoes these back."""
    out = {}
    for clips in sections.values():
        for c in clips:
            out[(c.video_id, int(round(c.t_start)))] = c
    return out


def _resolve(model_clip: dict, lookup: dict[tuple[str, int], Candidate]) -> Candidate | None:
    vid = str(model_clip.get("video_id", "")).strip()
    if not vid:
        return None
    try:
        t = int(round(float(model_clip.get("t_start", -1))))
    except (TypeError, ValueError):
        t = -1
    if (vid, t) in lookup:
        return lookup[(vid, t)]
    # The model may round differently; fall back to nearest start on that video.
    same_video = [(k, v) for k, v in lookup.items() if k[0] == vid]
    if not same_video:
        return None
    return min(same_video, key=lambda kv: abs(kv[0][1] - t))[1]


def assemble_learn(
    outline: Outline,
    chapter_clips: dict[str, list[Candidate]],
    llm: LLMClient,
    strict: bool = True,
) -> dict:
    """Build the final Learn page JSON.

    `strict` drops bridge sentences containing unsupported specifics. Default on:
    a silently-wrong date on a history page is worse than a blander bridge.
    """
    if not chapter_clips:
        raise LLMError("nothing to assemble: no chapters have clips")

    prompt = LEARN_PROMPT.format(
        title=outline.title, chapters=_render_sections(chapter_clips)
    )
    resp = llm.complete(prompt, system=LEARN_SYSTEM, model=MODEL_SMART, max_tokens=4096)
    data = extract_json(resp.text)
    if not isinstance(data, dict):
        raise LLMError("assembly did not return an object")

    lookup = _clip_lookup(chapter_clips)
    evidence = " ".join(c.text for clips in chapter_clips.values() for c in clips)

    chapters_out = []
    for ch in data.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        title = str(ch.get("title", "")).strip()
        intro = _trim_sentences(str(ch.get("intro_text", "")).strip())

        if strict and intro:
            unsupported = verify_no_new_facts(intro, evidence)
            if unsupported:
                log.warning(
                    "chapter %r bridge asserted unsupported specifics %s; trimming",
                    title,
                    unsupported,
                )
                intro = _drop_unsupported_sentences(intro, evidence)

        clips_out = []
        for mc in ch.get("clips") or []:
            if not isinstance(mc, dict):
                continue
            cand = _resolve(mc, lookup)
            if cand is None:
                continue
            clips_out.append(
                {
                    "video_id": cand.video_id,
                    "t_start": cand.t_start,
                    "t_end": cand.t_end,
                    "why": str(mc.get("why", "")).strip(),
                }
            )
        if clips_out:
            chapters_out.append(
                {"title": title, "intro_text": intro, "clips": clips_out}
            )

    if not chapters_out:
        raise LLMError("assembly produced no usable chapters")

    return {
        "title": str(data.get("title") or outline.title).strip(),
        "mode": "learn",
        "query": outline.query,
        "chapters": chapters_out,
    }


def assemble_entertain(
    outline: Outline,
    group_clips: dict[str, list[Candidate]],
    llm: LLMClient,
) -> dict:
    if not group_clips:
        raise LLMError("nothing to assemble: no groups have clips")

    prompt = ENTERTAIN_PROMPT.format(
        title=outline.title, groups=_render_sections(group_clips)
    )
    resp = llm.complete(
        prompt, system=ENTERTAIN_SYSTEM, model=MODEL_SMART, max_tokens=4096
    )
    data = extract_json(resp.text)
    if not isinstance(data, dict):
        raise LLMError("assembly did not return an object")

    lookup = _clip_lookup(group_clips)
    groups_out = []
    for grp in data.get("groups") or []:
        if not isinstance(grp, dict):
            continue
        clips_out = []
        for mc in grp.get("clips") or []:
            if not isinstance(mc, dict):
                continue
            cand = _resolve(mc, lookup)
            if cand is None:
                continue
            clips_out.append(
                {
                    "video_id": cand.video_id,
                    "t_start": cand.t_start,
                    "t_end": cand.t_end,
                    "why": str(mc.get("why", "")).strip(),
                }
            )
        if clips_out:
            groups_out.append(
                {"label": str(grp.get("label", "")).strip(), "clips": clips_out}
            )

    if not groups_out:
        raise LLMError("assembly produced no usable groups")

    return {
        "title": str(data.get("title") or outline.title).strip(),
        "mode": "entertain",
        "query": outline.query,
        "groups": groups_out,
        "end_card": str(data.get("end_card", "")).strip(),
    }


_SENT = re.compile(r"(?<=[.!?])\s+")


def _trim_sentences(text: str, limit: int = MAX_BRIDGE_SENTENCES) -> str:
    parts = [p for p in _SENT.split(text) if p.strip()]
    return " ".join(parts[:limit]).strip()


def _drop_unsupported_sentences(text: str, evidence: str) -> str:
    """Keep only sentences whose specifics are backed by the transcripts."""
    kept = [s for s in _SENT.split(text) if s.strip() and not verify_no_new_facts(s, evidence)]
    return " ".join(kept).strip()

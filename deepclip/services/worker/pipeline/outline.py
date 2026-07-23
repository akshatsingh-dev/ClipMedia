"""Stage 1 — intent classification + outline.

Normalise the query, then one Sonnet call classifies mode and produces the plan:
chapters for Learn, groupings for Entertain. Everything downstream keys off this,
so it validates hard and fails loudly rather than passing a malformed plan on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..llm.client import MODEL_SMART, LLMClient, LLMError, extract_json

# 6-10 chapters for a life, 4-8 concept nodes for a topic, 3-5 groupings for
# entertainment (spec C3 stage 1).
MIN_CHAPTERS, MAX_CHAPTERS = 4, 10
MIN_GROUPINGS, MAX_GROUPINGS = 3, 5

# The lenses for the multi-perspective view (research/perspective-streams.md).
# Fixed and labeled so a build is always balanced by construction — you cannot
# get a one-sided "perspectives" page.
LENS_LABELS = ("supportive", "critical", "neutral")
MIN_LENSES = 2  # a perspectives page with <2 lenses is invalid — that is the guardrail

SYSTEM = """You plan video-curation pages. You never write prose for the user; \
you only produce JSON plans that a retrieval pipeline consumes.

Two modes:
- "learn": the user wants to understand a person, event, or topic. Plan chapters \
that together tell a complete story in a sensible order.
- "entertain": the user wants the best moments of a subject/vibe. Plan groupings \
that carve the subject into distinct flavours.

Rules:
- search_hints must be phrases a person would actually type into YouTube. Vary \
them; do not just restate the chapter title.
- coverage_goals are concrete facts or beats the chapter must cover.
- Mark a chapter contested:true when mainstream accounts genuinely disagree about \
it, so the ranker can enforce multiple perspectives.
- Output JSON only. No commentary."""

LEARN_SHAPE = """{"mode":"learn","entity_type":"person|event|topic|concept",
 "title":"<page title>",
 "chapters":[{"title":"...","search_hints":["...","..."],
              "coverage_goals":["...","..."],"contested":false}]}"""

ENTERTAIN_SHAPE = """{"mode":"entertain","subject":"...","vibe":"...",
 "title":"<page title>",
 "search_hints":["...","..."],
 "groupings":[{"label":"...","search_hints":["..."]}]}"""

PROMPT = """Query: {query}

Decide the mode, then produce the matching plan.

If learn, use this shape ({min_ch}-{max_ch} chapters, chronological or logical \
order):
{learn_shape}

If entertain, use this shape ({min_gr}-{max_gr} groupings):
{entertain_shape}

JSON only."""


PERSPECTIVES_SYSTEM = """You plan a multi-perspective video page about a \
contested subject. The goal is that a viewer sees the subject through several \
labeled lenses — supportive, critical, and neutral — each built from real clips.

You NEVER take a side. You plan honest search hints for each lens so the page is \
balanced. For "supportive", hints that surface the case FOR; for "critical", the \
case AGAINST; for "neutral", explanatory or fact-checking coverage.

Output JSON only. No commentary."""

PERSPECTIVES_SHAPE = """{"mode":"perspectives","subject":"<subject>",
 "title":"<neutral page title>",
 "lenses":[{"label":"supportive","search_hints":["...","..."]},
           {"label":"critical","search_hints":["...","..."]},
           {"label":"neutral","search_hints":["...","..."]}]}"""

PERSPECTIVES_PROMPT = """Subject: {subject}

Plan a balanced multi-perspective page. Produce all three lenses (supportive, \
critical, neutral), each with search hints a person would actually type into \
YouTube to find that side's real footage.

{shape}

JSON only."""


def normalize_query(query: str) -> str:
    """Cache key. Case/whitespace/punctuation-insensitive so near-identical
    queries hit the same prebuilt page rather than paying to rebuild it."""
    text = unicodedata.normalize("NFKD", query or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    # Apostrophes are elided, not spaced: "gandhi's" -> "gandhis". Splitting on
    # them would make every possessive miss the cache and pay to rebuild.
    text = re.sub(r"['’ʼ]", "", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class Chapter:
    title: str
    search_hints: list[str] = field(default_factory=list)
    coverage_goals: list[str] = field(default_factory=list)
    contested: bool = False


@dataclass
class Grouping:
    label: str
    search_hints: list[str] = field(default_factory=list)


@dataclass
class Outline:
    mode: str
    title: str
    query: str
    query_norm: str
    entity_type: str | None = None
    subject: str | None = None
    vibe: str | None = None
    chapters: list[Chapter] = field(default_factory=list)
    groupings: list[Grouping] = field(default_factory=list)
    search_hints: list[str] = field(default_factory=list)

    def all_hints(self) -> list[str]:
        """Every hint the retrieval stage should run, de-duplicated in order.

        Order is preserved because quota may run out partway through; the most
        important hints must be attempted first.
        """
        seen: set[str] = set()
        out: list[str] = []
        for hint in (
            self.search_hints
            + [h for c in self.chapters for h in c.search_hints]
            + [h for g in self.groupings for h in g.search_hints]
        ):
            key = hint.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(hint.strip())
        return out

    def entity_names(self) -> list[str]:
        """Proper nouns for the stage-4 name-repair pass.

        Auto-captions mangle names ("Jinnah" -> "gina"); repair needs to know
        which names to expect, and the outline is where they first appear.
        """
        names: set[str] = set()
        for text in [self.title, self.subject or ""] + [c.title for c in self.chapters]:
            for match in re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*", text or ""):
                names.add(match)
        return sorted(names)


def _as_str_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def parse_outline(data: dict, query: str) -> Outline:
    """Validate a model plan into an Outline, or raise LLMError."""
    if not isinstance(data, dict):
        raise LLMError(f"outline must be an object, got {type(data).__name__}")

    mode = str(data.get("mode", "")).strip().lower()
    if mode not in {"learn", "entertain"}:
        raise LLMError(f"invalid mode: {mode!r}")

    title = str(data.get("title") or query).strip()
    outline = Outline(
        mode=mode,
        title=title,
        query=query,
        query_norm=normalize_query(query),
        search_hints=_as_str_list(data.get("search_hints")),
    )

    if mode == "learn":
        outline.entity_type = str(data.get("entity_type") or "topic").strip()
        raw = data.get("chapters")
        if not isinstance(raw, list) or not raw:
            raise LLMError("learn outline needs a non-empty chapters list")
        for item in raw[:MAX_CHAPTERS]:
            if not isinstance(item, dict) or not str(item.get("title", "")).strip():
                continue
            outline.chapters.append(
                Chapter(
                    title=str(item["title"]).strip(),
                    search_hints=_as_str_list(item.get("search_hints")),
                    coverage_goals=_as_str_list(item.get("coverage_goals")),
                    contested=bool(item.get("contested", False)),
                )
            )
        if not outline.chapters:
            raise LLMError("no valid chapters in outline")
    else:
        outline.subject = str(data.get("subject") or query).strip()
        outline.vibe = str(data.get("vibe") or "").strip()
        raw = data.get("groupings")
        if not isinstance(raw, list) or not raw:
            raise LLMError("entertain outline needs a non-empty groupings list")
        for item in raw[:MAX_GROUPINGS]:
            # Groupings may arrive as bare strings.
            if isinstance(item, str):
                if item.strip():
                    outline.groupings.append(Grouping(label=item.strip()))
                continue
            if not isinstance(item, dict) or not str(item.get("label", "")).strip():
                continue
            outline.groupings.append(
                Grouping(
                    label=str(item["label"]).strip(),
                    search_hints=_as_str_list(item.get("search_hints")),
                )
            )
        if not outline.groupings:
            raise LLMError("no valid groupings in outline")

    # A plan with no hints cannot retrieve anything — fail here rather than
    # letting stage 2 quietly return zero candidates.
    if not outline.all_hints():
        raise LLMError("outline produced no search hints")

    return outline


def build_outline(query: str, llm: LLMClient) -> Outline:
    prompt = PROMPT.format(
        query=query,
        min_ch=MIN_CHAPTERS,
        max_ch=MAX_CHAPTERS,
        min_gr=MIN_GROUPINGS,
        max_gr=MAX_GROUPINGS,
        learn_shape=LEARN_SHAPE,
        entertain_shape=ENTERTAIN_SHAPE,
    )
    resp = llm.complete(prompt, system=SYSTEM, model=MODEL_SMART, max_tokens=2048)
    return parse_outline(extract_json(resp.text), query)


def parse_perspectives_outline(data: dict, query: str) -> Outline:
    """Validate a perspectives plan. Lenses are stored as groupings so the rest
    of the pipeline (retrieval, ranking) reuses the entertain path unchanged."""
    if not isinstance(data, dict):
        raise LLMError("perspectives outline must be an object")
    outline = Outline(
        mode="perspectives",
        title=str(data.get("title") or query).strip(),
        query=query,
        query_norm=normalize_query(query),
        subject=str(data.get("subject") or query).strip(),
    )
    raw = data.get("lenses")
    if not isinstance(raw, list):
        raise LLMError("perspectives outline needs a lenses list")
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip().lower()
        if label not in LENS_LABELS:
            continue
        outline.groupings.append(
            Grouping(label=label, search_hints=_as_str_list(item.get("search_hints")))
        )
    # The guardrail: a perspectives page must be balanced or it does not ship.
    if len({g.label for g in outline.groupings}) < MIN_LENSES:
        raise LLMError(
            f"perspectives page needs >= {MIN_LENSES} lenses; a one-sided "
            "perspectives page is invalid by design"
        )
    if not outline.all_hints():
        raise LLMError("perspectives outline produced no search hints")
    return outline


def build_perspectives_outline(subject: str, llm: LLMClient) -> Outline:
    prompt = PERSPECTIVES_PROMPT.format(subject=subject, shape=PERSPECTIVES_SHAPE)
    resp = llm.complete(
        prompt, system=PERSPECTIVES_SYSTEM, model=MODEL_SMART, max_tokens=2048
    )
    return parse_perspectives_outline(extract_json(resp.text), subject)

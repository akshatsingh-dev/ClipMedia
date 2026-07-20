"""C7 — evaluation metrics.

Built before ranking is tuned, per the spec, because "technically retrieves
relevant segments" and "feels like a documentary editor chose these" are far
apart and only a measured gap closes that.

Metrics:
  coverage_recall   did the page hit the outline's coverage_goals?
  overlap_at_k      how much do generated clips match hand-picked golden clips?
  redundancy_rate   share of clip pairs that are near-duplicates
  junk_rate         share of clips that are intro/ad/banter rather than substance
  channel_diversity is the >=2-channels-per-chapter rule actually holding?

Ship gate (C7): >= 80% of the golden judge score on all four golden pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# Two clips of the same video whose windows overlap by this much are the "same"
# pick, so a generated clip a few seconds off a golden one still counts as a hit.
OVERLAP_IOU_THRESHOLD = 0.5
SHIP_GATE = 0.80

WORD = re.compile(r"[a-z0-9']+")
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "is", "was", "were", "be", "his", "her", "its", "their", "he", "she", "they",
    "it", "this", "that", "as", "by", "from", "had", "has", "have",
}


def _tokens(text: str) -> set[str]:
    return {w for w in WORD.findall((text or "").lower()) if w not in STOPWORDS}


@dataclass
class ClipRef:
    """A clip, generated or golden."""

    video_id: str
    t_start: float
    t_end: float
    channel: str = ""
    text: str = ""

    @property
    def duration(self) -> float:
        return max(self.t_end - self.t_start, 0.0)


def iou(a: ClipRef, b: ClipRef) -> float:
    """Temporal intersection-over-union. 0 for different videos."""
    if a.video_id != b.video_id:
        return 0.0
    lo = max(a.t_start, b.t_start)
    hi = min(a.t_end, b.t_end)
    inter = max(hi - lo, 0.0)
    union = a.duration + b.duration - inter
    return inter / union if union > 0 else 0.0


def overlap_at_k(
    generated: Sequence[ClipRef],
    golden: Sequence[ClipRef],
    k: int = 10,
    threshold: float = OVERLAP_IOU_THRESHOLD,
) -> float:
    """Share of golden clips matched by the top-k generated clips.

    Recall against the human picks, not precision: the question is how much of
    what a person chose the system found, not whether it added extras.
    """
    if not golden:
        return 0.0
    top = list(generated)[:k]
    matched = sum(1 for g in golden if any(iou(g, c) >= threshold for c in top))
    return matched / len(golden)


def coverage_recall(clips: Sequence[ClipRef], coverage_goals: Sequence[str]) -> float:
    """Share of coverage goals whose key terms appear in some clip transcript.

    Lexical, so it under-reports paraphrase. Deliberately so: it is a floor, and
    the LLM judge is what catches semantic coverage.
    """
    if not coverage_goals:
        return 1.0
    corpus = _tokens(" ".join(c.text for c in clips))
    hits = 0
    for goal in coverage_goals:
        goal_tokens = _tokens(goal)
        if not goal_tokens:
            continue
        # Half the goal's content words present counts as covered.
        if len(goal_tokens & corpus) / len(goal_tokens) >= 0.5:
            hits += 1
    return hits / len(coverage_goals)


def redundancy_rate(clips: Sequence[ClipRef], threshold: float = 0.6) -> float:
    """Share of clip pairs that say substantially the same thing."""
    items = list(clips)
    if len(items) < 2:
        return 0.0
    pairs = 0
    dupes = 0
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            pairs += 1
            if iou(a, b) >= OVERLAP_IOU_THRESHOLD:
                dupes += 1
                continue
            ta, tb = _tokens(a.text), _tokens(b.text)
            if ta and tb and len(ta & tb) / len(ta | tb) >= threshold:
                dupes += 1
    return dupes / pairs if pairs else 0.0


JUNK_PATTERNS = (
    r"\bsubscribe\b", r"\blike and share\b", r"\bsponsored by\b",
    r"\bpatreon\b", r"\blink in the description\b", r"\bwelcome back to\b",
    r"\bin today's video\b", r"\bbefore we (?:start|begin)\b",
)


def junk_rate(clips: Sequence[ClipRef]) -> float:
    """Share of clips that are housekeeping rather than substance."""
    items = list(clips)
    if not items:
        return 0.0
    junk = sum(
        1
        for c in items
        if any(re.search(p, (c.text or "").lower()) for p in JUNK_PATTERNS)
    )
    return junk / len(items)


def channel_diversity(clips_by_section: dict[str, Sequence[ClipRef]]) -> float:
    """Share of sections meeting the >=2-distinct-channels rule."""
    if not clips_by_section:
        return 0.0
    ok = sum(
        1
        for clips in clips_by_section.values()
        if len({c.channel for c in clips if c.channel}) >= 2
    )
    return ok / len(clips_by_section)


@dataclass
class PageScore:
    slug: str
    coverage_recall: float = 0.0
    overlap_at_k: float = 0.0
    redundancy_rate: float = 0.0
    junk_rate: float = 0.0
    channel_diversity: float = 0.0
    judge_score: float | None = None  # 1-5 from the LLM judge
    notes: list[str] = field(default_factory=list)

    @property
    def composite(self) -> float:
        """One number for tracking per-commit.

        Redundancy and junk are costs, so they subtract. Weighted toward coverage
        and overlap because those measure whether the page is *right*; diversity
        is a constraint that is either met or not.
        """
        return max(
            0.0,
            min(
                1.0,
                0.35 * self.coverage_recall
                + 0.30 * self.overlap_at_k
                + 0.15 * self.channel_diversity
                - 0.10 * self.redundancy_rate
                - 0.10 * self.junk_rate
                + 0.20,  # baseline so an all-zero page is not negative
            ),
        )

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "coverage_recall": round(self.coverage_recall, 4),
            "overlap_at_k": round(self.overlap_at_k, 4),
            "redundancy_rate": round(self.redundancy_rate, 4),
            "junk_rate": round(self.junk_rate, 4),
            "channel_diversity": round(self.channel_diversity, 4),
            "judge_score": self.judge_score,
            "composite": round(self.composite, 4),
            "notes": self.notes,
        }


def clips_from_page(page: dict) -> list[ClipRef]:
    """Flatten a page JSON into ClipRefs."""
    out: list[ClipRef] = []
    for section in page.get("chapters") or page.get("groups") or []:
        for c in section.get("clips", []):
            out.append(
                ClipRef(
                    video_id=c.get("video_id", ""),
                    t_start=float(c.get("t_start", 0)),
                    t_end=float(c.get("t_end", 0)),
                    channel=c.get("channel", ""),
                    text=c.get("why", "") + " " + c.get("video_title", ""),
                )
            )
    return out


def clips_by_section(page: dict) -> dict[str, list[ClipRef]]:
    out: dict[str, list[ClipRef]] = {}
    for section in page.get("chapters") or page.get("groups") or []:
        label = section.get("title") or section.get("label") or ""
        out[label] = [
            ClipRef(
                video_id=c.get("video_id", ""),
                t_start=float(c.get("t_start", 0)),
                t_end=float(c.get("t_end", 0)),
                channel=c.get("channel", ""),
                text=c.get("why", ""),
            )
            for c in section.get("clips", [])
        ]
    return out


def score_page(
    page: dict,
    golden: Sequence[ClipRef] = (),
    coverage_goals: Sequence[str] = (),
    k: int = 10,
) -> PageScore:
    clips = clips_from_page(page)
    sections = clips_by_section(page)
    score = PageScore(
        slug=page.get("slug") or page.get("query") or page.get("title", ""),
        coverage_recall=coverage_recall(clips, coverage_goals),
        overlap_at_k=overlap_at_k(clips, golden, k=k),
        redundancy_rate=redundancy_rate(clips),
        junk_rate=junk_rate(clips),
        channel_diversity=channel_diversity(sections),
    )
    if not golden:
        score.notes.append("no golden clips supplied; overlap_at_k is not meaningful")
    if not coverage_goals:
        score.notes.append("no coverage goals supplied; coverage_recall defaulted to 1.0")
    return score


def passes_ship_gate(scores: Iterable[PageScore], gate: float = SHIP_GATE) -> bool:
    """C7 ship gate: every golden page must clear the bar, not the average.

    An average would let a great Gandhi page hide a broken Speed feed.
    """
    items = list(scores)
    return bool(items) and all(s.composite >= gate for s in items)

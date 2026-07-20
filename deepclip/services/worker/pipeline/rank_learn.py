"""Stage 6 — Learn Mode ranking.

score = 0.40*cosine + 0.20*quality + 0.15*channel_credibility
      + 0.10*transcript_kind_prior + 0.10*visual_richness(0 in v1)
      + 0.05*recency_or_archival
      - drop if cosine > 0.85 vs any already-selected segment

Hard constraint: >= 2 distinct channels per chapter (LearnLens speaker-switching).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

REDUNDANCY_THRESHOLD = 0.85
MIN_CHANNELS_PER_CHAPTER = 2
CLIPS_PER_CHAPTER_MIN = 2
CLIPS_PER_CHAPTER_MAX = 4

WEIGHTS = {
    "cosine": 0.40,
    "quality": 0.20,
    "credibility": 0.15,
    "transcript_kind": 0.10,
    "visual_richness": 0.10,
    "recency": 0.05,
}

# manual > auto > whisper. Auto-captions mangle proper nouns, which matters
# more in Learn Mode than anywhere else ("Jinnah" -> "gina").
TRANSCRIPT_KIND_PRIOR = {"manual": 1.0, "auto": 0.6, "whisper": 0.4, None: 0.0}


@dataclass
class Candidate:
    """A segment plus the video/channel facts ranking needs."""

    segment_id: int
    video_id: str
    channel_id: str
    t_start: float
    t_end: float
    text: str
    cosine: float
    quality: float = 0.5
    intensity: float = 0.5
    credibility: float = 0.5
    transcript_kind: str | None = None
    visual_richness: float = 0.0  # 0 in v1; stage 8 fills this
    published_at: datetime | None = None
    view_count: int = 0
    duration_s: int = 0
    title: str = ""
    is_short: bool = False
    embedding: list[float] = field(default_factory=list)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def recency_score(published_at: datetime | None, half_life_days: float = 1825.0) -> float:
    """Mild recency preference. Long half-life (~5y): in history, old is fine."""
    if published_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max((now - published_at).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / half_life_days)


def score_candidate(c: Candidate) -> float:
    return (
        WEIGHTS["cosine"] * c.cosine
        + WEIGHTS["quality"] * c.quality
        + WEIGHTS["credibility"] * c.credibility
        + WEIGHTS["transcript_kind"] * TRANSCRIPT_KIND_PRIOR.get(c.transcript_kind, 0.0)
        + WEIGHTS["visual_richness"] * c.visual_richness
        + WEIGHTS["recency"] * recency_score(c.published_at)
    )


def _is_redundant(c: Candidate, selected: list[Candidate], threshold: float) -> bool:
    """Near-duplicate content check against what is already in the chapter."""
    for s in selected:
        if c.embedding and s.embedding:
            if cosine_similarity(c.embedding, s.embedding) > threshold:
                return True
        elif c.video_id == s.video_id and abs(c.t_start - s.t_start) < 30.0:
            # No embeddings: overlapping window of the same video is a dupe.
            return True
    return False


def rank_chapter(
    candidates: list[Candidate],
    min_clips: int = CLIPS_PER_CHAPTER_MIN,
    max_clips: int = CLIPS_PER_CHAPTER_MAX,
    min_channels: int = MIN_CHANNELS_PER_CHAPTER,
    redundancy_threshold: float = REDUNDANCY_THRESHOLD,
) -> list[Candidate]:
    """Select clips for one chapter under the diversity constraint.

    Greedy by score, skipping redundant picks. If the result would come from a
    single channel, the lowest-scoring pick is swapped for the best candidate
    from a different channel — speaker variety is a hard constraint, so it wins
    over raw score at the margin.
    """
    ordered = sorted(candidates, key=score_candidate, reverse=True)
    selected: list[Candidate] = []

    for c in ordered:
        if len(selected) >= max_clips:
            break
        if _is_redundant(c, selected, redundancy_threshold):
            continue
        selected.append(c)

    if len(selected) < min_clips:
        return selected  # thin chapter; caller decides whether to widen retrieval

    channels = {c.channel_id for c in selected}
    if len(channels) < min_channels:
        incumbent = channels.pop() if channels else None
        alt = next(
            (
                c
                for c in ordered
                if c.channel_id != incumbent
                and not _is_redundant(c, selected[:-1], redundancy_threshold)
            ),
            None,
        )
        if alt is not None:
            selected[-1] = alt

    return selected


def rank_learn_page(
    chapter_candidates: dict[str, list[Candidate]], **kwargs
) -> dict[str, list[Candidate]]:
    """Rank every chapter, suppressing clips already used earlier in the page.

    A clip that was perfect for 'Salt March' should not reappear under 'Legacy';
    repetition across chapters is the fastest way for a page to feel machine-made.
    """
    used: set[tuple[str, float]] = set()
    out: dict[str, list[Candidate]] = {}
    for chapter, cands in chapter_candidates.items():
        fresh = [c for c in cands if (c.video_id, c.t_start) not in used]
        picked = rank_chapter(fresh, **kwargs)
        out[chapter] = picked
        used.update((c.video_id, c.t_start) for c in picked)
    return out

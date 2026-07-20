"""Stage 6 — Entertain Mode ranking.

score = 0.35*cosine(vibe query) + 0.30*intensity + 0.20*engagement_velocity
      + 0.10*clip_density + 0.05*recency
      - redundancy drop; also drop near-duplicate reuploads
        (title-similarity + duration match heuristic)

20-30 clips per feed, interleaved across groupings, best-first.
"""

from __future__ import annotations

import difflib
import math
import re
from datetime import datetime, timezone

from .rank_learn import Candidate, _is_redundant, recency_score

WEIGHTS = {
    "cosine": 0.35,
    "intensity": 0.30,
    "engagement_velocity": 0.20,
    "clip_density": 0.10,
    "recency": 0.05,
}

FEED_MIN_CLIPS = 20
FEED_MAX_CLIPS = 30

REUPLOAD_TITLE_SIMILARITY = 0.85
REUPLOAD_DURATION_TOLERANCE_S = 2.0

# Reaction cues that mark an actual moment rather than talking.
INTENSITY_CUES = (
    "[laughter]", "[laughs]", "[screaming]", "[screams]", "[applause]",
    "[cheering]", "[gasps]", "[music]", "[shouting]",
)


def engagement_velocity(view_count: int, published_at: datetime | None) -> float:
    """Views/day since publish, log-scaled to 0-1.

    Raw views favour anything old; velocity surfaces clips that are actually
    hitting right now. Log scale so one viral outlier doesn't flatten the field.
    """
    if not view_count or published_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max((now - published_at).total_seconds() / 86400.0, 1.0)
    per_day = view_count / age_days
    # 1M views/day saturates to ~1.0
    return min(math.log10(per_day + 1) / 6.0, 1.0)


def clip_density(duration_s: int, is_short: bool) -> float:
    """Shorts and compilations rank up — the creator already found the moment."""
    if is_short:
        return 1.0
    if duration_s <= 0:
        return 0.0
    if duration_s <= 600:      # <=10min: likely a clip channel
        return 0.7
    if duration_s <= 1800:     # <=30min: compilation territory
        return 0.4
    return 0.1                 # full VOD/stream: mostly dead air


def intensity_from_text(text: str) -> float:
    """Heuristic fallback when the Haiku scoring pass (stage 5) hasn't run.

    Counts non-speech reaction cues and exclamation cadence. Deliberately crude —
    the LLM score supersedes it.
    """
    if not text:
        return 0.0
    lowered = text.lower()
    cue_hits = sum(lowered.count(cue) for cue in INTENSITY_CUES)
    exclamations = text.count("!")
    caps_words = len(re.findall(r"\b[A-Z]{3,}\b", text))
    raw = cue_hits * 0.25 + exclamations * 0.08 + caps_words * 0.05
    return min(raw, 1.0)


def score_candidate(c: Candidate) -> float:
    return (
        WEIGHTS["cosine"] * c.cosine
        + WEIGHTS["intensity"] * c.intensity
        + WEIGHTS["engagement_velocity"] * engagement_velocity(c.view_count, c.published_at)
        + WEIGHTS["clip_density"] * clip_density(c.duration_s, c.is_short)
        + WEIGHTS["recency"] * recency_score(c.published_at, half_life_days=365.0)
    )


def is_reupload(a: Candidate, b: Candidate) -> bool:
    """Title-similarity + duration match. Reupload farms are rampant in this space."""
    if abs(a.duration_s - b.duration_s) > REUPLOAD_DURATION_TOLERANCE_S:
        return False
    if not a.title or not b.title:
        return False
    ratio = difflib.SequenceMatcher(
        None, a.title.lower().strip(), b.title.lower().strip()
    ).ratio()
    return ratio >= REUPLOAD_TITLE_SIMILARITY


def rank_group(candidates: list[Candidate], limit: int = FEED_MAX_CLIPS) -> list[Candidate]:
    ordered = sorted(candidates, key=score_candidate, reverse=True)
    selected: list[Candidate] = []
    for c in ordered:
        if len(selected) >= limit:
            break
        if _is_redundant(c, selected, threshold=0.85):
            continue
        if any(is_reupload(c, s) for s in selected):
            continue
        selected.append(c)
    return selected


def interleave(groups: dict[str, list[Candidate]], limit: int = FEED_MAX_CLIPS):
    """Round-robin across groupings, best-first within each.

    Straight score order would front-load one grouping and make the feed feel
    repetitive by clip 5; alternating subjects is what keeps a scroll alive.
    Returns [(grouping_label, candidate)].
    """
    ranked = {label: rank_group(c, limit) for label, c in groups.items()}
    out: list[tuple[str, Candidate]] = []
    idx = 0
    while len(out) < limit:
        added = False
        # Strongest group first on each pass, so the feed opens strong.
        for label in sorted(
            ranked, key=lambda l: score_candidate(ranked[l][0]) if ranked[l] else -1.0,
            reverse=True,
        ):
            clips = ranked[label]
            if idx < len(clips):
                out.append((label, clips[idx]))
                added = True
                if len(out) >= limit:
                    break
        if not added:
            break
        idx += 1
    return out


def build_feed(
    groups: dict[str, list[Candidate]], limit: int = FEED_MAX_CLIPS
) -> list[tuple[str, Candidate]]:
    """Final feed order: open strong, vary subjects, close strongest (stage 7).

    The feed ENDS. No infinite scroll — that rule is inviolable (A4.4/D6).
    """
    feed = interleave(groups, limit)
    if len(feed) > 2:
        # Strongest closes, second-strongest opens. interleave() already leaves
        # the best clip at the front, so it has to be moved, not left alone.
        best_idx = max(range(len(feed)), key=lambda i: score_candidate(feed[i][1]))
        if best_idx != len(feed) - 1:
            feed.append(feed.pop(best_idx))
    return feed

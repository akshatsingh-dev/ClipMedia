"""Moment detection — choosing the exact t_start / t_end of a clip.

This is the part that separates "retrieved a relevant segment" from "an editor
chose this". Segmentation (segment.py) packs transcripts into fixed 30-90s
windows for *retrieval*; those boundaries are arbitrary and land mid-thought.
This module re-cuts a chosen region into an actual moment.

The two modes need different algorithms because they define "moment" differently:

  Learn      a self-contained explanation. Starts where a concept is introduced,
             ends where it resolves. Boundaries follow TOPIC SHIFTS.

  Entertain  a reaction peak. Needs pre-roll so the viewer sees the setup, and
             ends as the reaction decays. Boundaries follow INTENSITY.

Learn boundary detection is TextTiling (Hearst 1997): slide a window over the
token stream, measure lexical cohesion across each gap, and cut at the valleys.
It is unsupervised, deterministic, cheap, and needs no model — which matters
because this runs over every candidate video, where an LLM call per video would
dominate the cost model (C8).

Everything here is pure functions over transcript cues. No network, no API keys.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..sources.base import Transcript, TranscriptCue

# -- Learn tuning -------------------------------------------------------
BLOCK_SIZE = 6            # sentences per side of a TextTiling comparison window
SMOOTHING_WINDOW = 2      # rounds of moving average over the gap scores
DEPTH_THRESHOLD_SD = 0.5  # cut at valleys deeper than mean - 0.5*sd

LEARN_MIN_S = 25.0
LEARN_MAX_S = 240.0
LEARN_TARGET_S = 110.0

# -- Entertain tuning ---------------------------------------------------
# Pre-roll is the whole trick: cutting exactly on the laugh loses the setup and
# the clip is incomprehensible. Post-roll lets the reaction land.
ENTERTAIN_PREROLL_S = 4.0
ENTERTAIN_POSTROLL_S = 2.5
ENTERTAIN_MIN_S = 8.0
ENTERTAIN_MAX_S = 75.0

REACTION_CUES = (
    "laughter", "laughs", "laughing", "screaming", "screams", "shouting",
    "applause", "cheering", "cheers", "gasps", "gasp", "yelling",
)
NON_SPEECH = re.compile(r"\[([^\]]+)\]")
WORD = re.compile(r"[a-z0-9']+")

# Discourse markers that open an explanation. A clip that starts on one of these
# feels deliberate; one that starts on "...and that's why" feels like a machine
# grabbed the middle of a sentence.
OPENING_MARKERS = (
    "so", "now", "okay", "ok", "alright", "right", "let's", "lets", "first",
    "here's", "heres", "the idea", "imagine", "suppose", "consider", "think about",
    "what if", "but", "however", "the point", "in other words", "basically",
)

# Pronouns/anaphora at the start mean the clip depends on something we cut away.
ANAPHORIC_OPENERS = (
    "it", "this", "that", "they", "he", "she", "these", "those", "them",
    "its", "their", "which", "such",
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "at", "for", "with", "as", "is", "are", "was", "were", "be", "been", "am",
    "i", "you", "we", "they", "it", "he", "she", "this", "that", "these", "those",
    "so", "just", "very", "really", "there", "here", "what", "which", "who",
    "have", "has", "had", "do", "does", "did", "not", "no", "can", "will",
    "would", "could", "should", "my", "your", "our", "their", "his", "her", "its",
}


@dataclass
class Sentence:
    """A sentence with its own timing, reconstructed from caption cues.

    Caption cues do not align to sentences — they are display chunks. Everything
    downstream reasons about sentences, so this is the unit we rebuild first.
    """

    t_start: float
    t_end: float
    text: str

    def tokens(self) -> list[str]:
        return [w for w in WORD.findall(self.text.lower()) if w not in STOPWORDS]


@dataclass
class Moment:
    """A candidate clip with real boundaries and the reason it was cut there."""

    t_start: float
    t_end: float
    text: str
    score: float
    reason: str

    @property
    def duration_s(self) -> float:
        return self.t_end - self.t_start


# -- sentence reconstruction -------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def cues_to_sentences(cues: list[TranscriptCue]) -> list[Sentence]:
    """Rebuild sentences from cues, interpolating timing within a cue.

    A cue like "...that's the idea. Now the next part..." contains a boundary,
    so its time is split proportionally by character offset. Auto-captions often
    carry no punctuation at all; in that case each cue becomes its own sentence
    and the TextTiling pass still works, since it operates on token blocks.
    """
    sentences: list[Sentence] = []
    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        parts = [p for p in _SENT_SPLIT.split(text) if p.strip()]
        if len(parts) <= 1:
            sentences.append(Sentence(cue.t_start, cue.t_end, text))
            continue
        span = max(cue.t_end - cue.t_start, 0.0)
        total_chars = sum(len(p) for p in parts) or 1
        offset = 0.0
        for part in parts:
            frac = len(part) / total_chars
            start = cue.t_start + offset
            end = start + span * frac
            sentences.append(Sentence(start, end, part.strip()))
            offset += span * frac
    return _merge_unpunctuated_runs(sentences)


def _merge_unpunctuated_runs(sentences: list[Sentence], max_merge_s: float = 8.0):
    """Glue sub-clause fragments so a 'sentence' is a real unit of thought.

    Auto-captions emit 2-4 word cues. Left alone, every TextTiling block would
    span a couple of seconds and boundary detection would be noise.
    """
    if not sentences:
        return []
    out = [sentences[0]]
    for s in sentences[1:]:
        prev = out[-1]
        ends_clean = prev.text.rstrip().endswith((".", "!", "?"))
        if not ends_clean and (prev.t_end - prev.t_start) < max_merge_s:
            out[-1] = Sentence(prev.t_start, s.t_end, f"{prev.text} {s.text}".strip())
        else:
            out.append(s)
    return out


# -- Learn: TextTiling topic boundaries --------------------------------


def _block_similarity(left: list[Sentence], right: list[Sentence]) -> float:
    """Cosine similarity of token-count vectors either side of a gap."""
    lt: dict[str, int] = {}
    rt: dict[str, int] = {}
    for s in left:
        for w in s.tokens():
            lt[w] = lt.get(w, 0) + 1
    for s in right:
        for w in s.tokens():
            rt[w] = rt.get(w, 0) + 1
    if not lt or not rt:
        return 0.0
    shared = set(lt) & set(rt)
    dot = sum(lt[w] * rt[w] for w in shared)
    nl = math.sqrt(sum(v * v for v in lt.values()))
    nr = math.sqrt(sum(v * v for v in rt.values()))
    return dot / (nl * nr) if nl and nr else 0.0


def _smooth(values: list[float], window: int) -> list[float]:
    if window <= 0 or len(values) < 3:
        return list(values)
    out = []
    for i in range(len(values)):
        lo = max(0, i - window)
        hi = min(len(values), i + window + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def topic_boundaries(
    sentences: list[Sentence],
    block_size: int = BLOCK_SIZE,
    depth_threshold_sd: float = DEPTH_THRESHOLD_SD,
) -> list[int]:
    """TextTiling. Returns sentence indices where a new topic begins.

    For each gap, compare the block of sentences before it with the block after.
    Low similarity = the vocabulary changed = a topic shift. Cut at valleys whose
    depth (drop from surrounding peaks) exceeds mean - k*sd.
    """
    n = len(sentences)
    if n < block_size * 2:
        return []

    gaps = [
        _block_similarity(
            sentences[max(0, i - block_size) : i], sentences[i : i + block_size]
        )
        for i in range(1, n)
    ]
    gaps = _smooth(gaps, SMOOTHING_WINDOW)

    # Depth score: how far this valley sits below the nearest peak on each side.
    depths = []
    for i, val in enumerate(gaps):
        left = val
        for j in range(i - 1, -1, -1):
            if gaps[j] < left:
                break
            left = gaps[j]
        right = val
        for j in range(i + 1, len(gaps)):
            if gaps[j] < right:
                break
            right = gaps[j]
        depths.append((left - val) + (right - val))

    if not depths:
        return []
    mean = sum(depths) / len(depths)
    var = sum((d - mean) ** 2 for d in depths) / len(depths)
    cutoff = mean + depth_threshold_sd * math.sqrt(var)

    # A boundary is a local maximum of depth above the cutoff.
    boundaries = []
    for i, d in enumerate(depths):
        if d < cutoff or d <= 0:
            continue
        if i > 0 and depths[i - 1] > d:
            continue
        if i < len(depths) - 1 and depths[i + 1] > d:
            continue
        boundaries.append(i + 1)  # gap i sits before sentence i+1
    return boundaries


# -- boundary quality --------------------------------------------------


def opening_quality(sentence: Sentence) -> float:
    """How much a sentence sounds like the start of something. 0-1.

    Penalises anaphora hard: "it does that by..." tells the viewer they missed
    the setup, which is the most common way an auto-cut clip feels broken.
    """
    text = sentence.text.strip().lower()
    if not text:
        return 0.0
    words = WORD.findall(text)
    if not words:
        return 0.0

    score = 0.5
    if any(text.startswith(m) for m in OPENING_MARKERS):
        score += 0.35
    if words[0] in ANAPHORIC_OPENERS:
        score -= 0.4
    # Mid-sentence starts (lowercase continuation with no marker) read as broken.
    if not sentence.text.strip()[:1].isupper() and not any(
        text.startswith(m) for m in OPENING_MARKERS
    ):
        score -= 0.15
    return max(0.0, min(1.0, score))


def closing_quality(sentence: Sentence) -> float:
    """How much a sentence sounds like a resolution. 0-1."""
    text = sentence.text.strip()
    if not text:
        return 0.0
    score = 0.5
    if text.endswith((".", "!", "?")):
        score += 0.3
    else:
        # No terminal punctuation: the sentence was cut, not finished.
        score -= 0.2
    # Trailing conjunctions and dangling copulas mean the thought continues.
    if re.search(
        r"\b(and|but|so|because|which|that|or|then|is|are|was|were|of|to|the|a|an)"
        r"\s*[,]?$",
        text.lower().rstrip("."),
    ):
        score -= 0.4
    return max(0.0, min(1.0, score))


# -- Entertain: intensity curve ----------------------------------------


def sentence_intensity(sentence: Sentence) -> float:
    """Reaction intensity of one sentence, 0-1.

    Combines non-speech caption cues (the strongest signal available from text),
    exclamation cadence, shouted caps, and token repetition ("no no no no"),
    which is what excitement actually looks like in a transcript.
    """
    text = sentence.text
    if not text.strip():
        return 0.0
    lowered = text.lower()

    cue_score = 0.0
    for tag in NON_SPEECH.findall(lowered):
        if any(cue in tag for cue in REACTION_CUES):
            cue_score += 0.45
        else:
            cue_score += 0.05  # [music] etc: weak but not nothing

    exclam = min(text.count("!") * 0.12, 0.36)
    caps = min(len(re.findall(r"\b[A-Z]{3,}\b", text)) * 0.10, 0.3)

    words = WORD.findall(lowered)
    repeat = 0.0
    run = 1
    for a, b in zip(words, words[1:]):
        run = run + 1 if a == b else 1
        repeat = max(repeat, (run - 1) * 0.12)
    repeat = min(repeat, 0.3)

    # Fast delivery is a decent proxy for excitement.
    dur = max(sentence.t_end - sentence.t_start, 0.5)
    rate = len(words) / dur
    pace = min(max((rate - 2.5) / 4.0, 0.0), 0.2)

    return min(cue_score + exclam + caps + repeat + pace, 1.0)


def intensity_curve(sentences: list[Sentence]) -> list[float]:
    """Per-sentence intensity, lightly smoothed so one cue doesn't dominate."""
    return _smooth([sentence_intensity(s) for s in sentences], 1)


def find_peaks(curve: list[float], min_value: float = 0.25) -> list[int]:
    """Local maxima above a floor, strongest first."""
    peaks = []
    for i, v in enumerate(curve):
        if v < min_value:
            continue
        left_ok = i == 0 or curve[i - 1] <= v
        right_ok = i == len(curve) - 1 or curve[i + 1] <= v
        if left_ok and right_ok:
            peaks.append(i)
    return sorted(peaks, key=lambda i: curve[i], reverse=True)


# -- the entry points --------------------------------------------------


def detect_learn_moments(
    transcript: Transcript,
    min_s: float = LEARN_MIN_S,
    max_s: float = LEARN_MAX_S,
    target_s: float = LEARN_TARGET_S,
) -> list[Moment]:
    """Cut a transcript into explanation-shaped moments at topic boundaries."""
    sentences = cues_to_sentences(transcript.cues)
    if not sentences:
        return []

    bounds = topic_boundaries(sentences)
    starts = [0] + bounds
    ends = bounds + [len(sentences)]

    moments: list[Moment] = []
    for s_idx, e_idx in zip(starts, ends):
        if s_idx >= e_idx:
            continue
        span = sentences[s_idx:e_idx]
        s_idx, e_idx = _refine_learn_edges(sentences, s_idx, e_idx, min_s, max_s)
        if s_idx >= e_idx:
            continue
        span = sentences[s_idx:e_idx]
        t_start, t_end = span[0].t_start, span[-1].t_end
        dur = t_end - t_start
        if dur < min_s:
            continue

        open_q = opening_quality(span[0])
        close_q = closing_quality(span[-1])
        # Prefer clips near the target length; very long ones lose the viewer.
        length_fit = 1.0 - min(abs(dur - target_s) / target_s, 1.0)
        score = 0.45 * open_q + 0.30 * close_q + 0.25 * length_fit

        moments.append(
            Moment(
                t_start=t_start,
                t_end=t_end,
                text=" ".join(s.text for s in span),
                score=score,
                reason=(
                    f"topic boundary; open={open_q:.2f} close={close_q:.2f} "
                    f"len={dur:.0f}s"
                ),
            )
        )
    return sorted(moments, key=lambda m: m.score, reverse=True)


def _refine_learn_edges(
    sentences: list[Sentence], s_idx: int, e_idx: int, min_s: float, max_s: float
) -> tuple[int, int]:
    """Nudge edges to better sentences, then enforce the duration ceiling.

    The topic boundary is approximately right but often one sentence off. Look a
    couple of sentences either way for a cleaner opening/closing line.
    """
    best_s, best_score = s_idx, opening_quality(sentences[s_idx])
    for cand in range(max(0, s_idx - 1), min(len(sentences), s_idx + 3)):
        if cand >= e_idx:
            break
        q = opening_quality(sentences[cand])
        if q > best_score:
            best_s, best_score = cand, q

    best_e, best_score = e_idx, closing_quality(sentences[e_idx - 1])
    for cand in range(max(best_s + 1, e_idx - 2), min(len(sentences), e_idx + 2) + 1):
        if cand > len(sentences):
            break
        q = closing_quality(sentences[cand - 1])
        if q > best_score:
            best_e, best_score = cand, q

    # Trim from the end to respect max duration — never from the start, which
    # would undo the opening-quality work above.
    while best_e > best_s + 1 and (
        sentences[best_e - 1].t_end - sentences[best_s].t_start
    ) > max_s:
        best_e -= 1

    return best_s, best_e


def detect_entertain_moments(
    transcript: Transcript,
    preroll_s: float = ENTERTAIN_PREROLL_S,
    postroll_s: float = ENTERTAIN_POSTROLL_S,
    min_s: float = ENTERTAIN_MIN_S,
    max_s: float = ENTERTAIN_MAX_S,
    max_moments: int = 8,
) -> list[Moment]:
    """Cut a transcript at reaction peaks, with setup pre-roll included."""
    sentences = cues_to_sentences(transcript.cues)
    if not sentences:
        return []

    curve = intensity_curve(sentences)
    peaks = find_peaks(curve)
    if not peaks:
        return []

    moments: list[Moment] = []
    claimed: list[tuple[float, float]] = []

    for peak in peaks:
        if len(moments) >= max_moments:
            break
        s_idx, e_idx = _expand_around_peak(sentences, curve, peak, min_s, max_s)
        span = sentences[s_idx:e_idx]
        if not span:
            continue

        t_start = max(0.0, span[0].t_start - preroll_s)
        t_end = span[-1].t_end + postroll_s
        if t_end - t_start < min_s:
            t_end = t_start + min_s
        if t_end - t_start > max_s:
            t_end = t_start + max_s

        # Peaks near each other describe the same moment; keep only the best.
        if any(t_start < c_end and t_end > c_start for c_start, c_end in claimed):
            continue
        claimed.append((t_start, t_end))

        peak_v = curve[peak]
        mean_v = sum(curve) / len(curve)
        prominence = peak_v - mean_v
        score = min(0.6 * peak_v + 0.4 * max(prominence, 0.0) * 2.0, 1.0)

        moments.append(
            Moment(
                t_start=t_start,
                t_end=t_end,
                text=" ".join(s.text for s in span),
                score=score,
                reason=(
                    f"reaction peak {peak_v:.2f} (mean {mean_v:.2f}); "
                    f"+{preroll_s:.0f}s pre-roll"
                ),
            )
        )
    return sorted(moments, key=lambda m: m.score, reverse=True)


def _expand_around_peak(
    sentences: list[Sentence],
    curve: list[float],
    peak: int,
    min_s: float,
    max_s: float,
) -> tuple[int, int]:
    """Grow outward from a peak while intensity stays elevated.

    The moment is the whole elevated region, not the single loudest sentence —
    stopping at the peak alone yields a 2-second clip with no shape.
    """
    floor = curve[peak] * 0.35
    s_idx = peak
    while s_idx > 0 and curve[s_idx - 1] >= floor:
        if sentences[peak].t_end - sentences[s_idx - 1].t_start > max_s:
            break
        s_idx -= 1

    e_idx = peak + 1
    while e_idx < len(sentences) and curve[e_idx] >= floor:
        if sentences[e_idx].t_end - sentences[s_idx].t_start > max_s:
            break
        e_idx += 1

    # Guarantee the minimum by extending forward, then backward.
    while (
        e_idx < len(sentences)
        and sentences[e_idx - 1].t_end - sentences[s_idx].t_start < min_s
    ):
        e_idx += 1
    while (
        s_idx > 0
        and sentences[e_idx - 1].t_end - sentences[s_idx].t_start < min_s
    ):
        s_idx -= 1

    return s_idx, e_idx


def detect_moments(transcript: Transcript, mode: str) -> list[Moment]:
    """Dispatch on mode. 'learn' | 'entertain'."""
    if mode == "entertain":
        return detect_entertain_moments(transcript)
    if mode == "learn":
        return detect_learn_moments(transcript)
    raise ValueError(f"unknown mode: {mode!r}")

"""Stage 5a — segmentation.

Rule (master doc C2): semantic boundaries, 30-90s target, 15s overlap,
sentence-aligned from caption timings, merge fragments <10s.

Non-speech caption cues ('[laughter]', '[screaming]') are preserved verbatim —
for Entertain Mode they are intensity features, not noise (stage 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..sources.base import Transcript, TranscriptCue

TARGET_MIN_S = 30.0
TARGET_MAX_S = 90.0
OVERLAP_S = 15.0
MIN_FRAGMENT_S = 10.0

_SENTENCE_END = re.compile(r"[.!?]['\")\]]*\s*$")
NON_SPEECH_CUE = re.compile(r"\[[^\]]+\]")


@dataclass
class Segment:
    video_id: str
    t_start: float
    t_end: float
    text: str

    @property
    def duration_s(self) -> float:
        return self.t_end - self.t_start

    def non_speech_cues(self) -> list[str]:
        """Intensity features for Entertain ranking."""
        return [c.lower() for c in NON_SPEECH_CUE.findall(self.text)]


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def segment_transcript(
    transcript: Transcript,
    target_min_s: float = TARGET_MIN_S,
    target_max_s: float = TARGET_MAX_S,
    overlap_s: float = OVERLAP_S,
    min_fragment_s: float = MIN_FRAGMENT_S,
) -> list[Segment]:
    """Greedy sentence-aligned packing.

    Accumulate cues until >= target_min_s, then close at the next sentence
    boundary; force-close at target_max_s so one run-on monologue cannot
    produce a 6-minute segment.
    """
    cues = [c for c in transcript.cues if c.text.strip()]
    if not cues:
        return []

    segments: list[Segment] = []
    buf: list[TranscriptCue] = []

    def flush() -> None:
        if not buf:
            return
        segments.append(
            Segment(
                video_id=transcript.video_id,
                t_start=buf[0].t_start,
                t_end=buf[-1].t_end,
                text=" ".join(c.text.strip() for c in buf),
            )
        )

    for cue in cues:
        buf.append(cue)
        span = buf[-1].t_end - buf[0].t_start
        if span >= target_max_s or (span >= target_min_s and _ends_sentence(cue.text)):
            flush()
            buf = _overlap_tail(buf, overlap_s) if overlap_s > 0 else []

    # Trailing buffer: only keep it if it is not just the overlap tail repeating.
    if buf:
        span = buf[-1].t_end - buf[0].t_start
        is_pure_overlap = bool(segments) and buf[-1].t_end <= segments[-1].t_end
        if span >= min_fragment_s and not is_pure_overlap:
            flush()

    return _merge_short_fragments(segments, min_fragment_s)


def _overlap_tail(buf: list[TranscriptCue], overlap_s: float) -> list[TranscriptCue]:
    """Carry the last `overlap_s` of cues into the next segment.

    Overlap keeps a point made across a boundary retrievable from either side.
    """
    if not buf:
        return []
    cutoff = buf[-1].t_end - overlap_s
    return [c for c in buf if c.t_end > cutoff]


def _merge_short_fragments(segments: list[Segment], min_s: float) -> list[Segment]:
    """Merge sub-`min_s` fragments into the previous segment (or the next, if first)."""
    if not segments:
        return []
    out: list[Segment] = []
    for seg in segments:
        if seg.duration_s < min_s and out:
            prev = out[-1]
            out[-1] = Segment(
                video_id=prev.video_id,
                t_start=prev.t_start,
                t_end=max(prev.t_end, seg.t_end),
                text=f"{prev.text} {seg.text}".strip(),
            )
        else:
            out.append(seg)
    # A leading fragment can survive the loop; fold it forward.
    if len(out) > 1 and out[0].duration_s < min_s:
        head, nxt = out[0], out[1]
        out[1] = Segment(
            video_id=nxt.video_id,
            t_start=head.t_start,
            t_end=nxt.t_end,
            text=f"{head.text} {nxt.text}".strip(),
        )
        out.pop(0)
    return out


def snap_to_sentence_start(segment: Segment, transcript: Transcript) -> float:
    """Stage 7: snap t_start back to the nearest sentence boundary.

    Starting a clip mid-sentence is the single most obvious tell of a machine
    edit, so assembly always runs this before emitting a clip.
    """
    candidates = [
        c.t_start
        for i, c in enumerate(transcript.cues)
        if c.t_start <= segment.t_start
        and (i == 0 or _ends_sentence(transcript.cues[i - 1].text))
    ]
    return max(candidates) if candidates else segment.t_start

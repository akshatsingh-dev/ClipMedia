import pytest

from services.worker.pipeline.segment import (
    MIN_FRAGMENT_S,
    TARGET_MAX_S,
    Segment,
    segment_transcript,
    snap_to_sentence_start,
)
from services.worker.sources.base import Transcript, TranscriptCue


def transcript(cues, video_id="v1"):
    return Transcript(
        video_id=video_id,
        kind="manual",
        lang="en",
        cues=[TranscriptCue(s, e, t) for s, e, t in cues],
    )


def steady(n, step=5.0, text="filler words here"):
    """n cues of `step` seconds, no sentence endings."""
    return [(i * step, (i + 1) * step, text) for i in range(n)]


def test_empty_transcript_yields_nothing():
    assert segment_transcript(transcript([])) == []


def test_blank_cues_ignored():
    assert segment_transcript(transcript([(0, 5, "   "), (5, 10, "")])) == []


def test_closes_at_sentence_boundary_after_min_target():
    cues = steady(7) + [(35.0, 40.0, "And that was the end.")] + steady(6)
    segs = segment_transcript(transcript(cues))
    assert segs[0].t_end == 40.0, "should close on the sentence, not mid-thought"


def test_force_closes_at_max_duration():
    """A run-on monologue must not produce one giant segment."""
    segs = segment_transcript(transcript(steady(60)))
    assert segs, "expected segments"
    for s in segs:
        assert s.duration_s <= TARGET_MAX_S + 1e-6


def test_overlap_carried_between_segments():
    segs = segment_transcript(transcript(steady(60)), overlap_s=15.0)
    assert len(segs) >= 2
    # Consecutive segments share time: end of one is past the start of the next.
    assert segs[1].t_start < segs[0].t_end


def test_no_overlap_when_disabled():
    segs = segment_transcript(transcript(steady(60)), overlap_s=0.0)
    for a, b in zip(segs, segs[1:]):
        assert b.t_start >= a.t_end


def test_short_fragments_merged_away():
    cues = steady(8) + [(40.0, 41.0, "Tiny.")]
    segs = segment_transcript(transcript(cues), overlap_s=0.0)
    for s in segs:
        assert s.duration_s >= MIN_FRAGMENT_S


def test_segments_carry_video_id_and_ordered_time():
    segs = segment_transcript(transcript(steady(40), video_id="abc"))
    assert all(s.video_id == "abc" for s in segs)
    for s in segs:
        assert s.t_end > s.t_start
    for a, b in zip(segs, segs[1:]):
        assert b.t_start >= a.t_start


def test_non_speech_cues_preserved_as_intensity_features():
    """Entertain Mode ranks on these; stripping them would destroy the signal."""
    cues = steady(7) + [(35.0, 40.0, "[laughter] that was insane! [screaming]")]
    segs = segment_transcript(transcript(cues))
    joined = " ".join(s.text for s in segs)
    assert "[laughter]" in joined
    assert "[screaming]" in segs[0].non_speech_cues()[1] or "[screaming]" in joined


def test_non_speech_cues_extraction():
    seg = Segment("v", 0, 30, "wow [laughter] no way [applause]")
    assert seg.non_speech_cues() == ["[laughter]", "[applause]"]


def test_snap_to_sentence_start_moves_back_to_boundary():
    tr = transcript(
        [
            (0.0, 5.0, "Intro sentence ends here."),
            (5.0, 10.0, "This is the real start of the point"),
            (10.0, 15.0, "continuing the same thought."),
        ]
    )
    seg = Segment("v1", 10.0, 40.0, "continuing the same thought.")
    # 10.0 begins mid-sentence; the boundary is the cue after the '.' at 5.0.
    assert snap_to_sentence_start(seg, tr) == 5.0


def test_snap_is_noop_when_already_aligned():
    tr = transcript([(0.0, 5.0, "First sentence."), (5.0, 10.0, "Second sentence.")])
    seg = Segment("v1", 0.0, 10.0, "First sentence.")
    assert snap_to_sentence_start(seg, tr) == 0.0

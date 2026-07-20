import pytest

from services.worker.pipeline.moments import (
    Sentence,
    closing_quality,
    cues_to_sentences,
    detect_entertain_moments,
    detect_learn_moments,
    detect_moments,
    find_peaks,
    intensity_curve,
    opening_quality,
    sentence_intensity,
    topic_boundaries,
)
from services.worker.sources.base import Transcript, TranscriptCue


def tr(cues, video_id="v1", kind="manual"):
    """Accepts (start, end, text) tuples or TranscriptCue objects."""
    return Transcript(
        video_id=video_id,
        kind=kind,
        lang="en",
        cues=[c if isinstance(c, TranscriptCue) else TranscriptCue(*c) for c in cues],
    )


def sent(text, t_start=0.0, t_end=4.0):
    return Sentence(t_start, t_end, text)


# -- sentence reconstruction -------------------------------------------


def test_cue_splits_into_sentences_with_interpolated_timing():
    s = cues_to_sentences([TranscriptCue(0.0, 10.0, "First part here. Second part.")])
    assert len(s) == 2
    assert s[0].t_start == 0.0
    # Boundary lands inside the cue, proportional to characters.
    assert 0.0 < s[0].t_end < 10.0
    assert s[1].t_end == pytest.approx(10.0, abs=0.01)


def test_sentences_stay_in_order_and_do_not_go_backwards():
    s = cues_to_sentences(
        [TranscriptCue(0, 6, "One. Two. Three."), TranscriptCue(6, 12, "Four. Five.")]
    )
    for a, b in zip(s, s[1:]):
        assert b.t_start >= a.t_start


def test_unpunctuated_autocaption_fragments_merge():
    """Auto-captions emit 2-4 word cues with no punctuation."""
    cues = [TranscriptCue(i * 1.0, i * 1.0 + 1.0, f"word{i} and then") for i in range(8)]
    s = cues_to_sentences(cues)
    assert len(s) < 8, "fragments should glue into larger units"


def test_empty_and_blank_cues():
    assert cues_to_sentences([]) == []
    assert cues_to_sentences([TranscriptCue(0, 1, "   ")]) == []


# -- opening / closing quality -----------------------------------------


def test_anaphoric_opener_penalised():
    """'It does that by...' means the viewer missed the setup."""
    good = opening_quality(sent("So the key idea is that weights are adjusted."))
    bad = opening_quality(sent("it does that by adjusting them."))
    assert good > bad
    assert bad < 0.4


def test_discourse_marker_boosts_opening():
    assert opening_quality(sent("Now imagine a network with two layers.")) > 0.7


def test_trailing_conjunction_penalised_in_closing():
    good = closing_quality(sent("And that is how backpropagation works."))
    bad = closing_quality(sent("which means that the gradient is"))
    assert good > bad
    assert bad < 0.4


def test_quality_bounded_and_blank_safe():
    for f in (opening_quality, closing_quality):
        assert f(sent("")) == 0.0
        assert 0.0 <= f(sent("Anything at all here.")) <= 1.0


# -- TextTiling ---------------------------------------------------------


def test_topic_boundary_found_at_vocabulary_shift():
    """Two blocks with disjoint vocabulary should produce a cut between them."""
    topic_a = [
        sent(f"Gradient descent adjusts the loss surface step {i}.", i * 5.0, i * 5.0 + 5)
        for i in range(8)
    ]
    topic_b = [
        sent(
            f"Transformers use attention across token sequences {i}.",
            40.0 + i * 5.0,
            45.0 + i * 5.0,
        )
        for i in range(8)
    ]
    bounds = topic_boundaries(topic_a + topic_b)
    assert bounds, "expected at least one boundary"
    # The true shift is at index 8; allow a couple of sentences of slack.
    assert any(abs(b - 8) <= 3 for b in bounds), f"boundaries {bounds} missed the shift"


def test_no_boundaries_on_short_input():
    assert topic_boundaries([sent("One.")]) == []
    assert topic_boundaries([]) == []


def test_homogeneous_text_yields_few_boundaries():
    same = [sent(f"The same topic repeated again {i}.", i * 5.0, i * 5.0 + 5) for i in range(20)]
    assert len(topic_boundaries(same)) <= 3


# -- intensity ----------------------------------------------------------


def test_reaction_cues_dominate_intensity():
    hot = sentence_intensity(sent("[laughter] [screaming] NO WAY!!!"))
    cold = sentence_intensity(sent("Today we will calmly review the material."))
    assert hot > cold
    assert hot > 0.6


def test_music_cue_is_weaker_than_laughter():
    assert sentence_intensity(sent("[music]")) < sentence_intensity(sent("[laughter]"))


def test_token_repetition_reads_as_excitement():
    rep = sentence_intensity(sent("no no no no no"))
    plain = sentence_intensity(sent("the value goes down"))
    assert rep > plain


def test_intensity_bounded():
    v = sentence_intensity(sent("[laughter] [screaming] [applause] NO WAY!!!! STOP STOP STOP"))
    assert 0.0 <= v <= 1.0


def test_find_peaks_orders_by_height():
    curve = [0.1, 0.9, 0.1, 0.5, 0.1]
    assert find_peaks(curve)[0] == 1


def test_find_peaks_respects_floor():
    assert find_peaks([0.05, 0.1, 0.05], min_value=0.25) == []


# -- Learn moments ------------------------------------------------------


def _learn_transcript():
    cues = []
    t = 0.0
    for i in range(10):
        cues.append(TranscriptCue(t, t + 6.0, f"So gradient descent lowers the loss value {i}."))
        t += 6.0
    for i in range(10):
        cues.append(TranscriptCue(t, t + 6.0, f"Now attention layers compare token pairs {i}."))
        t += 6.0
    return tr(cues)


def test_learn_moments_respect_duration_bounds():
    for m in detect_learn_moments(_learn_transcript()):
        assert m.duration_s >= 25.0
        assert m.duration_s <= 240.0 + 1e-6


def test_learn_moments_prefer_clean_openings():
    moments = detect_learn_moments(_learn_transcript())
    assert moments
    assert moments[0].text.strip()[0].isupper()


def test_learn_moments_sorted_by_score_and_carry_reason():
    moments = detect_learn_moments(_learn_transcript())
    scores = [m.score for m in moments]
    assert scores == sorted(scores, reverse=True)
    assert all(m.reason for m in moments)


def test_learn_moment_times_are_sane():
    for m in detect_learn_moments(_learn_transcript()):
        assert m.t_end > m.t_start >= 0.0


# -- Entertain moments --------------------------------------------------


def _entertain_transcript():
    cues = []
    t = 0.0
    for i in range(6):
        cues.append(TranscriptCue(t, t + 4.0, f"okay so we are just walking around {i}."))
        t += 4.0
    cues.append(TranscriptCue(t, t + 4.0, "WAIT WHAT!!! [screaming] no no no no!"))
    t += 4.0
    cues.append(TranscriptCue(t, t + 4.0, "[laughter] that was insane!!!"))
    t += 4.0
    for i in range(6):
        cues.append(TranscriptCue(t, t + 4.0, f"anyway back to normal talking {i}."))
        t += 4.0
    return tr(cues)


def test_entertain_moment_includes_preroll_before_the_peak():
    """Cutting on the laugh loses the setup — the clip must start earlier."""
    moments = detect_entertain_moments(_entertain_transcript())
    assert moments
    peak_time = 24.0  # the "WAIT WHAT" cue starts here
    assert moments[0].t_start < peak_time, "clip should open before the reaction"


def test_entertain_moment_respects_bounds():
    for m in detect_entertain_moments(_entertain_transcript()):
        assert m.duration_s >= 8.0 - 1e-6
        assert m.duration_s <= 75.0 + 1e-6


def test_entertain_never_starts_negative():
    """A peak in the first seconds must not produce a negative t_start."""
    cues = [TranscriptCue(0.0, 3.0, "[screaming] WHAT!!!")]
    cues += [TranscriptCue(3.0 + i * 4, 7.0 + i * 4, f"calm talking {i}.") for i in range(6)]
    for m in detect_entertain_moments(tr(cues)):
        assert m.t_start >= 0.0


def test_overlapping_peaks_deduped():
    """Adjacent peaks describe one moment, not several."""
    cues = []
    t = 0.0
    for i in range(4):
        cues.append(TranscriptCue(t, t + 4.0, f"quiet setup {i}."))
        t += 4.0
    for i in range(4):
        cues.append(TranscriptCue(t, t + 4.0, "[laughter] WOW!!!"))
        t += 4.0
    moments = detect_entertain_moments(tr(cues))
    for a, b in zip(moments, moments[1:]):
        assert not (a.t_start < b.t_end and a.t_end > b.t_start), "overlapping moments"


def test_flat_transcript_yields_no_entertain_moments():
    cues = [TranscriptCue(i * 4.0, i * 4.0 + 4.0, f"just talking {i}.") for i in range(10)]
    assert detect_entertain_moments(tr(cues)) == []


# -- dispatch -----------------------------------------------------------


def test_detect_moments_dispatch():
    t = _learn_transcript()
    assert detect_moments(t, "learn") == detect_learn_moments(t)
    assert detect_moments(_entertain_transcript(), "entertain")


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        detect_moments(_learn_transcript(), "nonsense")


def test_empty_transcript_safe_in_both_modes():
    empty = tr([])
    assert detect_learn_moments(empty) == []
    assert detect_entertain_moments(empty) == []

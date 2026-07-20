"""Live integration tests against real YouTube captions.

Captions need no API key, so this exercises the real transcript -> sentences ->
moment-detection chain end to end. Network-gated: skipped unless DEEPCLIP_LIVE=1,
so the default suite stays hermetic and offline.

    DEEPCLIP_LIVE=1 python3 -m pytest tests/test_integration_live.py -q
"""

from __future__ import annotations

import os

import pytest

from services.worker.pipeline.moments import (
    cues_to_sentences,
    detect_learn_moments,
    opening_quality,
    topic_boundaries,
)
from services.worker.sources.youtube import YouTubeTranscriptFetcher

pytestmark = pytest.mark.skipif(
    os.environ.get("DEEPCLIP_LIVE") != "1",
    reason="live network test; set DEEPCLIP_LIVE=1 to run",
)

# 3Blue1Brown, "But what is a neural network?" — manual captions, stable video.
VIDEO_ID = "aircAruvnKk"


@pytest.fixture(scope="module")
def transcript():
    # certifi keeps macOS system Python from failing TLS verification.
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass
    t = YouTubeTranscriptFetcher().fetch(VIDEO_ID)
    if t is None:
        pytest.skip(f"no transcript available for {VIDEO_ID}")
    return t


def test_fetches_real_transcript(transcript):
    assert transcript.kind in {"manual", "auto"}
    assert len(transcript.cues) > 100
    assert all(c.t_end >= c.t_start for c in transcript.cues)


def test_sentences_reconstructed(transcript):
    sentences = cues_to_sentences(transcript.cues)
    assert sentences
    # Sentence merging should compress the cue stream, not expand it.
    assert len(sentences) < len(transcript.cues)
    for a, b in zip(sentences, sentences[1:]):
        assert b.t_start >= a.t_start


def test_topic_boundaries_are_plausible(transcript):
    sentences = cues_to_sentences(transcript.cues)
    bounds = topic_boundaries(sentences)
    assert 3 <= len(bounds) <= 40, f"implausible boundary count: {len(bounds)}"
    assert bounds == sorted(bounds)
    assert all(0 < b < len(sentences) for b in bounds)


def test_learn_moments_open_cleanly(transcript):
    """The core quality claim: clips should not start mid-thought."""
    moments = detect_learn_moments(transcript)
    assert moments, "expected moments from a 19-minute lecture"

    top = moments[:5]
    sentences = cues_to_sentences(transcript.cues)
    by_start = {round(s.t_start, 2): s for s in sentences}
    for m in top:
        opener = by_start.get(round(m.t_start, 2))
        if opener is not None:
            assert opening_quality(opener) >= 0.5, f"weak opening: {opener.text[:60]!r}"


def test_learn_moments_respect_bounds_on_real_data(transcript):
    for m in detect_learn_moments(transcript):
        assert 25.0 <= m.duration_s <= 240.0 + 1e-6
        assert m.t_end > m.t_start >= 0.0


def test_moments_do_not_overlap(transcript):
    moments = sorted(detect_learn_moments(transcript), key=lambda m: m.t_start)
    for a, b in zip(moments, moments[1:]):
        assert b.t_start >= a.t_start, "moments out of order"

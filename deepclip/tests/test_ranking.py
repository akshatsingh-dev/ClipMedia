from datetime import datetime, timedelta, timezone

import pytest

from services.worker.pipeline.rank_entertain import (
    build_feed,
    clip_density,
    engagement_velocity,
    intensity_from_text,
    interleave,
    is_reupload,
    rank_group,
)
from services.worker.pipeline.rank_entertain import score_candidate as ent_score
from services.worker.pipeline.rank_learn import (
    Candidate,
    cosine_similarity,
    rank_chapter,
    rank_learn_page,
    recency_score,
    score_candidate,
)

NOW = datetime.now(timezone.utc)


def cand(sid, channel="UC1", cosine=0.5, **kw):
    return Candidate(
        segment_id=sid,
        video_id=kw.pop("video_id", f"v{sid}"),
        channel_id=channel,
        t_start=kw.pop("t_start", sid * 100.0),
        t_end=kw.pop("t_end", sid * 100.0 + 60),
        text=kw.pop("text", f"text {sid}"),
        cosine=cosine,
        **kw,
    )


# -- scoring primitives -------------------------------------------------


def test_cosine_similarity_basics():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == 0.0
    assert cosine_similarity([1, 0], [1, 0, 0]) == 0.0, "dim mismatch is not a crash"


def test_learn_score_respects_weights():
    """Cosine is 0.40 of the score, so it must dominate a pure-cosine delta."""
    lo = cand(1, cosine=0.0)
    hi = cand(2, cosine=1.0)
    assert score_candidate(hi) - score_candidate(lo) == pytest.approx(0.40)


def test_transcript_kind_prior_ordering():
    manual = cand(1, transcript_kind="manual")
    auto = cand(2, transcript_kind="auto")
    whisper = cand(3, transcript_kind="whisper")
    none = cand(4, transcript_kind=None)
    scores = [score_candidate(c) for c in (manual, auto, whisper, none)]
    assert scores == sorted(scores, reverse=True)


def test_recency_score_decays():
    fresh = recency_score(NOW)
    old = recency_score(NOW - timedelta(days=1825))
    assert fresh > old
    assert old == pytest.approx(0.5, abs=0.01), "one half-life ~= 0.5"
    assert recency_score(None) == 0.5


def test_naive_datetime_does_not_crash():
    assert 0.0 <= recency_score(datetime(2020, 1, 1)) <= 1.0


# -- Learn chapter selection -------------------------------------------


def test_rank_chapter_orders_by_score_and_caps():
    cands = [cand(i, cosine=i / 10) for i in range(10)]
    picked = rank_chapter(cands, max_clips=4)
    assert len(picked) == 4
    assert [c.segment_id for c in picked] == [9, 8, 7, 6]


def test_redundancy_drop_on_high_cosine_embeddings():
    a = cand(1, cosine=0.9, embedding=[1.0, 0.0, 0.0])
    dupe = cand(2, cosine=0.88, embedding=[0.999, 0.01, 0.0])  # >0.85 vs a
    distinct = cand(3, cosine=0.80, channel="UC2", embedding=[0.0, 1.0, 0.0])
    picked = rank_chapter([a, dupe, distinct], max_clips=4)
    ids = [c.segment_id for c in picked]
    assert 1 in ids and 3 in ids
    assert 2 not in ids, "near-duplicate segment must be dropped"


def test_overlapping_same_video_treated_as_dupe_without_embeddings():
    a = cand(1, cosine=0.9, video_id="same", t_start=100.0)
    b = cand(2, cosine=0.85, video_id="same", t_start=110.0)  # within 30s
    picked = rank_chapter([a, b], max_clips=4)
    assert len(picked) == 1


def test_two_distinct_channels_enforced():
    """Hard constraint: a chapter from one voice is a spec violation."""
    same = [cand(i, channel="UC1", cosine=0.9 - i * 0.01) for i in range(4)]
    other = cand(99, channel="UC2", cosine=0.10)  # much worse, but different voice
    picked = rank_chapter(same + [other], max_clips=3)
    assert len({c.channel_id for c in picked}) >= 2


def test_channel_constraint_not_forced_when_already_diverse():
    a = cand(1, channel="UC1", cosine=0.9)
    b = cand(2, channel="UC2", cosine=0.8)
    picked = rank_chapter([a, b], max_clips=2)
    assert [c.segment_id for c in picked] == [1, 2], "no swap needed"


def test_thin_chapter_returns_what_it_has():
    picked = rank_chapter([cand(1)], min_clips=2)
    assert len(picked) == 1


def test_clip_not_reused_across_chapters():
    shared = cand(1, cosine=0.99, channel="UC1")
    filler = [cand(i, cosine=0.5, channel=f"UC{i}") for i in range(2, 8)]
    out = rank_learn_page(
        {"ch1": [shared] + filler, "ch2": [shared] + filler}, max_clips=2
    )
    ch1 = {(c.video_id, c.t_start) for c in out["ch1"]}
    ch2 = {(c.video_id, c.t_start) for c in out["ch2"]}
    assert not (ch1 & ch2), "same clip appeared in two chapters"


# -- Entertain ----------------------------------------------------------


def test_engagement_velocity_prefers_fast_climbers():
    viral = engagement_velocity(1_000_000, NOW - timedelta(days=2))
    slow = engagement_velocity(1_000_000, NOW - timedelta(days=2000))
    assert viral > slow
    assert engagement_velocity(0, NOW) == 0.0
    assert engagement_velocity(100, None) == 0.0
    assert 0.0 <= viral <= 1.0


def test_clip_density_favours_shorts():
    assert clip_density(45, is_short=True) == 1.0
    assert clip_density(300, False) > clip_density(1200, False) > clip_density(7200, False)
    assert clip_density(0, False) == 0.0


def test_intensity_from_text_reads_reaction_cues():
    hot = intensity_from_text("[laughter] NO WAY that just happened!!! [screaming]")
    cold = intensity_from_text("So in this video we will discuss the topic calmly.")
    assert hot > cold
    assert intensity_from_text("") == 0.0
    assert 0.0 <= hot <= 1.0


def test_entertain_weights_intensity_over_recency():
    base = dict(cosine=0.5, published_at=NOW, view_count=1000, duration_s=60)
    intense = cand(1, intensity=1.0, **base)
    dull = cand(2, intensity=0.0, **base)
    assert ent_score(intense) - ent_score(dull) == pytest.approx(0.30)


def test_reupload_detection():
    a = cand(1, title="IShowSpeed FUNNIEST Moments", duration_s=120)
    b = cand(2, title="ishowspeed funniest moments", duration_s=121)
    c = cand(3, title="Messi Solo Goal vs Getafe", duration_s=120)
    assert is_reupload(a, b)
    assert not is_reupload(a, c)
    assert not is_reupload(a, cand(4, title="IShowSpeed FUNNIEST Moments", duration_s=400))


def test_rank_group_drops_reuploads():
    a = cand(1, cosine=0.9, title="Speed Funny Moments", duration_s=100, video_id="x")
    b = cand(2, cosine=0.8, title="speed funny moments", duration_s=100, video_id="y")
    picked = rank_group([a, b])
    assert len(picked) == 1


def test_interleave_alternates_groups():
    groups = {
        "soccer": [cand(i, cosine=0.9, video_id=f"s{i}") for i in range(5)],
        "streams": [cand(i + 10, cosine=0.8, video_id=f"t{i}") for i in range(5)],
    }
    labels = [label for label, _ in interleave(groups, limit=6)]
    assert labels[0] != labels[1], "two of the same grouping back-to-back"
    assert set(labels) == {"soccer", "streams"}


def test_interleave_handles_uneven_groups():
    groups = {
        "a": [cand(i, video_id=f"a{i}") for i in range(5)],
        "b": [cand(10, video_id="b0")],
    }
    out = interleave(groups, limit=10)
    assert len(out) == 6, "should drain the long group, not stall on the short one"


def test_feed_respects_limit_and_ends():
    groups = {"g": [cand(i, video_id=f"v{i}") for i in range(100)]}
    feed = build_feed(groups, limit=25)
    assert len(feed) == 25, "the feed ends — no infinite scroll"


def test_feed_closes_on_strongest_clip():
    groups = {
        "g": [
            cand(1, cosine=0.5, video_id="a"),
            cand(2, cosine=0.99, intensity=1.0, video_id="b"),
            cand(3, cosine=0.4, video_id="c"),
        ]
    }
    feed = build_feed(groups, limit=3)
    assert feed[-1][1].video_id == "b", "strongest clip should close the feed"


def test_empty_inputs_are_safe():
    assert rank_chapter([]) == []
    assert rank_group([]) == []
    assert interleave({}) == []
    assert build_feed({"g": []}) == []

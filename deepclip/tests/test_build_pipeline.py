import json

import pytest

from services.worker.llm.client import FakeLLMClient
from services.worker.pipeline.build import BuildDeps, BuildFailed, build_page
from services.worker.pipeline.embed import HashingEmbedder
from services.worker.pipeline.reel_import import (
    SeedAnalysis,
    UnsupportedSource,
    analyse_seed,
    import_seed,
    instagram_embed_html,
    resolve_platform,
    share_card_text,
)
from services.worker.sources.base import Transcript, TranscriptCue, VideoMeta
from services.worker.sources.youtube import QuotaExceeded, QuotaLedger, YouTubeSource

# -- fakes --------------------------------------------------------------


class FakeYouTube(YouTubeSource):
    """Real YouTubeSource behaviour with the network replaced."""

    def __init__(self, video_ids=None, transcripts=None, metas=None, fail_after=None):
        self._ids = video_ids or ["v1", "v2", "v3"]
        self._transcripts = transcripts or {}
        self._metas = metas or {}
        self.quota = QuotaLedger()
        self._searches = 0
        self._fail_after = fail_after

    def search(self, hint, max_results=25):
        self._searches += 1
        if self._fail_after is not None and self._searches > self._fail_after:
            raise QuotaExceeded("simulated quota exhaustion")
        self.quota.charge(100)
        return list(self._ids)

    def search_with_shorts_variants(self, hint, max_results=25):
        return self.search(hint, max_results)

    def fetch_metadata(self, video_ids):
        return [self._metas[v] for v in video_ids if v in self._metas]

    def fetch_transcript(self, video_id):
        return self._transcripts.get(video_id)


def make_transcript(vid, sentences=24, mode="learn"):
    cues = []
    t = 0.0
    for i in range(sentences):
        if mode == "learn":
            text = (
                f"So gradient descent lowers the loss at step {i}."
                if i < sentences // 2
                else f"Now attention compares token pairs at step {i}."
            )
        else:
            text = "[laughter] WOW that was insane!!!" if i % 5 == 0 else f"just talking {i}."
        cues.append(TranscriptCue(t, t + 6.0, text))
        t += 6.0
    return Transcript(video_id=vid, kind="manual", lang="en", cues=cues)


def make_meta(vid, channel="UC1", duration=900):
    return VideoMeta(
        id=vid,
        source="youtube",
        title=f"Video {vid}",
        channel_id=channel,
        channel_name=f"Channel {channel}",
        duration_s=duration,
        view_count=10000,
    )


LEARN_OUTLINE = {
    "mode": "learn",
    "entity_type": "topic",
    "title": "Neural Networks",
    "chapters": [
        {"title": "Basics", "search_hints": ["neural network basics"], "coverage_goals": ["layers"]},
        {"title": "Training", "search_hints": ["gradient descent"], "coverage_goals": ["loss"]},
    ],
}

ENTERTAIN_OUTLINE = {
    "mode": "entertain",
    "subject": "Speed",
    "vibe": "funny",
    "title": "Funny Speed",
    "search_hints": ["speed funny"],
    "groupings": [
        {"label": "soccer", "search_hints": ["speed soccer"]},
        {"label": "streams", "search_hints": ["speed stream"]},
    ],
}


def learn_llm():
    """Fake that answers each stage by matching its prompt."""
    return FakeLLMClient(
        by_substring={
            "Decide the mode": json.dumps(LEARN_OUTLINE),
            "Score each segment": '{"scores":[]}',
            "Chapters and their selected clips": json.dumps(
                {
                    "title": "Neural Networks",
                    "chapters": [
                        {
                            "title": "Basics",
                            "intro_text": "An introduction.",
                            "clips": [{"video_id": "v1", "t_start": 0, "why": "clear"}],
                        }
                    ],
                }
            ),
        }
    )


def deps_for(mode="learn", **kw):
    vids = ["v1", "v2", "v3"]
    yt = FakeYouTube(
        video_ids=vids,
        transcripts={v: make_transcript(v, mode=mode) for v in vids},
        metas={v: make_meta(v, channel=f"UC{i}") for i, v in enumerate(vids)},
        **kw,
    )
    return BuildDeps(youtube=yt, llm=learn_llm(), embedder=HashingEmbedder())


# -- happy path ---------------------------------------------------------


def test_build_learn_page_end_to_end():
    result = build_page("neural networks", deps_for())
    assert result.mode == "learn"
    assert result.page["chapters"]
    assert result.slug == "neural networks"


def test_every_clip_gets_attribution():
    """Attribution is non-negotiable (C5) and must not depend on the model."""
    result = build_page("neural networks", deps_for())
    for chapter in result.page["chapters"]:
        for clip in chapter["clips"]:
            assert clip["channel"]
            assert clip["credit_url"].startswith("https://www.youtube.com/watch?v=")
            assert clip["thumbnail"]
            assert clip["channel_url"]


def test_credit_url_includes_timestamp():
    result = build_page("neural networks", deps_for())
    clip = result.page["chapters"][0]["clips"][0]
    assert f"t={int(clip['t_start'])}s" in clip["credit_url"]


def test_progress_reports_every_stage():
    seen = []
    build_page("nn", deps_for(), progress=lambda s, m, f, p: seen.append(s))
    for stage in ("outline", "retrieve", "transcripts", "segment", "score", "rank", "assemble"):
        assert stage in seen, f"missing progress stage: {stage}"


def test_quota_spent_is_reported():
    result = build_page("nn", deps_for())
    assert result.quota_spent > 0


# -- degradation --------------------------------------------------------


def test_quota_exhaustion_mid_build_still_ships_a_page():
    """Running out of quota is expected; it must not lose the whole page."""
    result = build_page("nn", deps_for(fail_after=1))
    assert result.page["chapters"]
    assert any("quota" in w.lower() for w in result.warnings)


def test_missing_transcripts_warn_but_do_not_fail():
    d = deps_for()
    d.youtube._transcripts = {"v1": make_transcript("v1")}  # 1 of 3
    result = build_page("nn", d)
    assert result.page["chapters"]
    assert any("transcript" in w.lower() for w in result.warnings)


def test_transcript_exception_does_not_lose_the_page():
    d = deps_for()
    original = d.youtube.fetch_transcript

    def flaky(vid):
        if vid == "v2":
            raise RuntimeError("network blip")
        return original(vid)

    d.youtube.fetch_transcript = flaky
    assert build_page("nn", d).page["chapters"]


def test_no_candidates_raises_build_failed():
    d = deps_for()
    d.youtube._ids = []
    with pytest.raises(BuildFailed):
        build_page("nn", d)


def test_no_transcripts_raises_build_failed():
    d = deps_for()
    d.youtube._transcripts = {}
    with pytest.raises(BuildFailed):
        build_page("nn", d)


# -- entertain ----------------------------------------------------------


def test_build_entertain_feed():
    d = deps_for(mode="entertain")
    d.llm = FakeLLMClient(
        by_substring={
            "Decide the mode": json.dumps(ENTERTAIN_OUTLINE),
            "Score each segment": '{"scores":[]}',
            "Clips grouped by theme": json.dumps(
                {
                    "title": "Funny Speed",
                    "groups": [
                        {
                            "label": "soccer",
                            "clips": [{"video_id": "v1", "t_start": 0, "why": "he falls"}],
                        }
                    ],
                    "end_card": "That is the feed.",
                }
            ),
        }
    )
    result = build_page("funny speed", d)
    assert result.mode == "entertain"
    assert result.page["groups"]
    assert result.page["end_card"]


def test_mode_hint_overrides_classification():
    d = deps_for(mode="entertain")
    d.llm = FakeLLMClient(
        by_substring={
            "Decide the mode": json.dumps(ENTERTAIN_OUTLINE),
            "Score each segment": '{"scores":[]}',
            "Clips grouped by theme": json.dumps(
                {"groups": [{"label": "soccer", "clips": [{"video_id": "v1", "t_start": 0, "why": "w"}]}],
                 "end_card": "end"}
            ),
        }
    )
    assert build_page("q", d, mode_hint="entertain").mode == "entertain"


# -- reel import --------------------------------------------------------


@pytest.mark.parametrize(
    "url,platform,vid",
    [
        ("https://www.youtube.com/watch?v=aircAruvnKk", "youtube", "aircAruvnKk"),
        ("https://youtu.be/aircAruvnKk", "youtube", "aircAruvnKk"),
        ("https://www.youtube.com/shorts/aircAruvnKk", "youtube", "aircAruvnKk"),
        ("https://www.instagram.com/reel/Cx1_ab-2/", "instagram", "Cx1_ab-2"),
        ("https://www.tiktok.com/@user/video/12345", "tiktok", "12345"),
    ],
)
def test_resolve_platform(url, platform, vid):
    assert resolve_platform(url) == (platform, vid)


def test_resolve_platform_rejects_unknown():
    with pytest.raises(UnsupportedSource):
        resolve_platform("https://example.com/video/1")


def test_instagram_import_requires_user_supplied_caption():
    """We never crawl Instagram; without user-supplied text there is no input."""
    d = deps_for()
    with pytest.raises(UnsupportedSource, match="caption text"):
        import_seed("https://www.instagram.com/reel/ABC/", d)


def test_instagram_embed_html_is_official_markup():
    html = instagram_embed_html("ABC123")
    assert "instagram-media" in html
    assert "ABC123" in html
    # Must be an embed, never a media file reference.
    assert ".mp4" not in html


def test_analyse_seed_parses_response():
    llm = FakeLLMClient(
        responses=[
            json.dumps(
                {
                    "mode": "learn",
                    "topic": "stoicism",
                    "subtopic": "marcus aurelius",
                    "depth_level": 2,
                    "next_query": "stoicism marcus aurelius meditations",
                    "confidence": 0.9,
                }
            )
        ]
    )
    a = analyse_seed("youtube", "abc", llm, content="text")
    assert a.mode == "learn"
    assert a.next_query == "stoicism marcus aurelius meditations"
    assert a.needs_confirmation is False


def test_low_confidence_requires_confirmation():
    llm = FakeLLMClient(responses=[json.dumps({"mode": "learn", "topic": "x", "confidence": 0.2})])
    assert analyse_seed("youtube", "abc", llm).needs_confirmation is True


def test_instagram_always_requires_confirmation():
    """Caption-only analysis is thin; the spec requires a user tap."""
    llm = FakeLLMClient(responses=[json.dumps({"mode": "learn", "topic": "x", "confidence": 1.0})])
    assert analyse_seed("instagram", "abc", llm).needs_confirmation is True


def test_analyse_seed_survives_garbage_response():
    a = analyse_seed("youtube", "abc", FakeLLMClient(responses=['{"nonsense":1}']))
    assert a.mode == "learn"
    assert a.depth_level == 1


def test_analyse_seed_clamps_depth():
    llm = FakeLLMClient(responses=[json.dumps({"mode": "learn", "topic": "x", "depth_level": 99})])
    assert analyse_seed("youtube", "abc", llm).depth_level == 5


def test_import_youtube_seed_builds_page():
    d = deps_for()
    d.llm = FakeLLMClient(
        by_substring={
            "Source: youtube": json.dumps(
                {"mode": "learn", "topic": "neural networks", "next_query": "neural networks",
                 "confidence": 0.9}
            ),
            "Decide the mode": json.dumps(LEARN_OUTLINE),
            "Score each segment": '{"scores":[]}',
            "Chapters and their selected clips": json.dumps(
                {"chapters": [{"title": "Basics", "intro_text": "",
                               "clips": [{"video_id": "v1", "t_start": 0, "why": "w"}]}]}
            ),
        }
    )
    d.youtube._metas["aircAruvnKk"] = make_meta("aircAruvnKk")
    d.youtube._transcripts["aircAruvnKk"] = make_transcript("aircAruvnKk")
    analysis, result = import_seed("https://youtu.be/aircAruvnKk", d)
    assert analysis["platform"] == "youtube"
    assert analysis["built_slug"] == "neural networks"
    assert result.page["chapters"]


def test_share_card_text():
    assert "full picture" in share_card_text({"mode": "learn", "topic": "Stoicism"})
    assert "best of" in share_card_text({"mode": "entertain", "topic": "Speed"})
    assert share_card_text({})


def test_seed_analysis_roundtrip():
    a = SeedAnalysis(platform="youtube", source_id="x", mode="learn", topic="t")
    assert a.to_dict()["platform"] == "youtube"

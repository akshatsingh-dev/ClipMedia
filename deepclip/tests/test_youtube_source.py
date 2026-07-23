from datetime import datetime, timedelta, timezone

import pytest

from services.worker.sources.base import SearchUnsupported
from services.worker.sources.instagram import InstagramSource, parse_shortcode
from services.worker.sources.youtube import (
    InMemoryHintCache,
    QuotaExceeded,
    QuotaLedger,
    TranscriptIpBlocked,
    YouTubeSource,
    YouTubeTranscriptFetcher,
    classify_source,
    parse_iso8601_duration,
)


class FakeClient:
    """Records calls so quota behaviour is assertable without network."""

    def __init__(self, search_results=None, videos=None):
        self._search_results = search_results or {}
        self._videos = videos or {}
        self.search_calls: list[str] = []
        self.videos_calls: list[list[str]] = []

    def search_list(self, q, max_results):
        self.search_calls.append(q)
        ids = self._search_results.get(q, [])[:max_results]
        return {"items": [{"id": {"videoId": v}} for v in ids]}

    def videos_list(self, ids):
        self.videos_calls.append(list(ids))
        return {"items": [self._videos[i] for i in ids if i in self._videos]}


def make_item(vid, duration="PT10M", views="1000", channel="UC1"):
    return {
        "id": vid,
        "snippet": {
            "title": f"title {vid}",
            "channelId": channel,
            "channelTitle": "Chan",
            "publishedAt": "2024-01-02T03:04:05Z",
        },
        "contentDetails": {"duration": duration},
        "statistics": {"viewCount": views, "likeCount": "10"},
    }


# -- duration parsing ---------------------------------------------------


@pytest.mark.parametrize(
    "iso,expected",
    [
        ("PT4M13S", 253),
        ("PT1H2M3S", 3723),
        ("PT45S", 45),
        ("P1DT2H", 93600),
        ("", 0),
        ("garbage", 0),
    ],
)
def test_parse_iso8601_duration(iso, expected):
    assert parse_iso8601_duration(iso) == expected


def test_classify_source_shorts_boundary():
    assert classify_source(180) == "youtube_shorts"
    assert classify_source(181) == "youtube"
    assert classify_source(None) == "youtube"
    # A zero/unknown duration must not be misfiled as a Short.
    assert classify_source(0) == "youtube"


# -- quota --------------------------------------------------------------


def test_search_charges_100_units():
    src = YouTubeSource(client=FakeClient({"gandhi": ["a"]}), quota=QuotaLedger())
    src.search("gandhi")
    assert src.quota.spent == 100


def test_hint_cache_hit_costs_zero_quota():
    client = FakeClient({"gandhi": ["a", "b"]})
    src = YouTubeSource(client=client, quota=QuotaLedger())
    first = src.search("gandhi")
    second = src.search("gandhi")
    assert first == second == ["a", "b"]
    assert src.quota.spent == 100, "second search must be free"
    assert len(client.search_calls) == 1


def test_expired_hint_cache_refetches():
    cache = InMemoryHintCache()
    cache._data["gandhi"] = (["stale"], datetime.now(timezone.utc) - timedelta(days=31))
    client = FakeClient({"gandhi": ["fresh"]})
    src = YouTubeSource(client=client, hint_cache=cache, quota=QuotaLedger())
    assert src.search("gandhi") == ["fresh"]


def test_quota_ledger_refuses_to_overspend():
    src = YouTubeSource(client=FakeClient({"q": ["a"]}), quota=QuotaLedger(daily_limit=150))
    src.search("q")
    with pytest.raises(QuotaExceeded):
        src.search("other")


def test_eight_chapter_page_stays_under_daily_quota():
    """Doc's own worst case: 16 hints ~= 1,600 units, must fit in 10k."""
    hints = [f"hint {i}" for i in range(16)]
    client = FakeClient({h: [f"v{i}"] for i, h in enumerate(hints)})
    src = YouTubeSource(client=client, quota=QuotaLedger())
    for h in hints:
        src.search(h)
    assert src.quota.spent == 1600
    assert src.quota.remaining == 8400


def test_metadata_batches_50_ids_per_call():
    ids = [f"v{i}" for i in range(120)]
    client = FakeClient(videos={i: make_item(i) for i in ids})
    src = YouTubeSource(client=client, quota=QuotaLedger())
    metas = src.fetch_metadata(ids)
    assert len(metas) == 120
    assert [len(c) for c in client.videos_calls] == [50, 50, 20]
    assert src.quota.spent == 3, "1 unit per batch, not per id"


def test_metadata_maps_fields_and_classifies_shorts():
    client = FakeClient(videos={"s": make_item("s", duration="PT58S")})
    src = YouTubeSource(client=client, quota=QuotaLedger())
    (meta,) = src.fetch_metadata(["s"])
    assert meta.source == "youtube_shorts"
    assert meta.duration_s == 58
    assert meta.view_count == 1000
    assert meta.published_at == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_shorts_variant_search_dedupes():
    client = FakeClient({"speed": ["a", "b"], "speed #shorts": ["b", "c"]})
    src = YouTubeSource(client=client, quota=QuotaLedger())
    assert src.search_with_shorts_variants("speed") == ["a", "b", "c"]


# -- embeds & attribution ----------------------------------------------


def test_embed_url_carries_start_end_and_jsapi():
    src = YouTubeSource(client=FakeClient(), quota=QuotaLedger())
    url = src.embed_url("abc", 312.7, 495.2)
    assert url == "https://www.youtube.com/embed/abc?enablejsapi=1&start=312&end=495"


def test_credit_url_points_at_original():
    assert YouTubeSource.credit_url("abc", 312) == (
        "https://www.youtube.com/watch?v=abc&t=312s"
    )


# -- Instagram inbound-only --------------------------------------------


def test_instagram_search_is_refused():
    with pytest.raises(SearchUnsupported):
        InstagramSource().search("anything")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.instagram.com/reel/Cx1_ab-2/", "Cx1_ab-2"),
        ("https://instagram.com/p/ABC123", "ABC123"),
        ("https://youtube.com/watch?v=x", None),
    ],
)
def test_parse_shortcode(url, expected):
    assert parse_shortcode(url) == expected


# -- transcript IP blocks ----------------------------------------------


class IpBlocked(Exception):
    """Stands in for youtube_transcript_api's exception, matched by class name."""


class FakeTrack:
    def __init__(self, exc=None, cues=None):
        self.language_code = "en"
        self._exc = exc
        self._cues = cues or [{"start": 0.0, "duration": 2.0, "text": "hello"}]

    def fetch(self):
        if self._exc:
            raise self._exc
        return self._cues


class FakeListing:
    def __init__(self, manual=None, generated=None):
        self._manual = manual
        self._generated = generated

    def find_manually_created_transcript(self, langs):
        if self._manual is None:
            raise Exception("no manual track")
        return self._manual

    def find_generated_transcript(self, langs):
        if self._generated is None:
            raise Exception("no generated track")
        return self._generated


def fetcher_with(listing_or_exc):
    f = YouTubeTranscriptFetcher()

    def _listing(video_id):
        if isinstance(listing_or_exc, Exception):
            raise listing_or_exc
        return listing_or_exc

    f._listing = _listing
    return f


def test_listing_level_ip_block_is_raised():
    with pytest.raises(TranscriptIpBlocked):
        fetcher_with(IpBlocked("YouTube is blocking requests from your IP")).fetch("v")


def test_content_level_ip_block_is_raised():
    """The listing can succeed while the caption *content* fetch is blocked.

    Swallowing that reports 'no captions' for a video whose captions exist —
    the misdiagnosis that hid a live block.
    """
    listing = FakeListing(manual=FakeTrack(exc=IpBlocked("blocking requests from your IP")))
    with pytest.raises(TranscriptIpBlocked):
        fetcher_with(listing).fetch("v")


def test_generated_track_block_is_also_raised():
    listing = FakeListing(generated=FakeTrack(exc=IpBlocked("blocking requests from your IP")))
    with pytest.raises(TranscriptIpBlocked):
        fetcher_with(listing).fetch("v")


def test_genuinely_missing_captions_return_none():
    """A video with no tracks is not a block and must not stop the build."""
    assert fetcher_with(FakeListing()).fetch("v") is None


def test_manual_track_wins_over_generated():
    listing = FakeListing(manual=FakeTrack(), generated=FakeTrack())
    t = fetcher_with(listing).fetch("v")
    assert t is not None and t.kind == "manual" and t.cues[0].text == "hello"

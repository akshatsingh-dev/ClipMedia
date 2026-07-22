"""YouTube SourceAdapter — discovery, metadata, transcript fallback chain.

Quota is the binding constraint (master doc stage 2):
  search.list  = 100 units   <- the expensive one
  videos.list  =   1 unit    <- batch 50 ids/call
Default allowance is 10k units/day, so an 8-chapter Learn page (~16 hints)
burns ~1,600 units on search alone. Mitigations implemented here:
  (b) hint_cache checked before any search, 30-day TTL
  (c) videos.list batched 50 ids/call
Mitigation (a), filing for a quota increase, is an ops task, not code.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .base import (
    SourceAdapter,
    Transcript,
    TranscriptCue,
    VideoMeta,
)

log = logging.getLogger(__name__)

SEARCH_COST_UNITS = 100
VIDEOS_LIST_COST_UNITS = 1
VIDEOS_LIST_BATCH = 50
HINT_CACHE_TTL = timedelta(days=30)

# Stage 3: no Shorts filter exists in the API, so detect post-hoc on duration.
SHORTS_MAX_DURATION_S = 180

_ISO8601_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def parse_iso8601_duration(value: str) -> int:
    """YouTube returns contentDetails.duration as ISO-8601 (e.g. 'PT4M13S')."""
    m = _ISO8601_DURATION.match(value or "")
    if not m:
        return 0
    parts = {k: int(v) for k, v in m.groupdict(default="0").items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def classify_source(duration_s: int | None) -> str:
    """Stage 3 Shorts detection. Vertical-aspect check is a post-MVP refinement."""
    if duration_s is not None and 0 < duration_s <= SHORTS_MAX_DURATION_S:
        return "youtube_shorts"
    return "youtube"


class HintCache(Protocol):
    def get(self, hint: str) -> tuple[list[str], datetime] | None: ...
    def put(self, hint: str, video_ids: list[str]) -> None: ...


class InMemoryHintCache:
    """Default cache. Postgres-backed `hint_cache` table is the production impl."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[list[str], datetime]] = {}

    def get(self, hint: str) -> tuple[list[str], datetime] | None:
        return self._data.get(hint)

    def put(self, hint: str, video_ids: list[str]) -> None:
        self._data[hint] = (video_ids, datetime.now(timezone.utc))


@dataclass
class QuotaLedger:
    """Tracks units spent so a run can be stopped before it blows the daily cap."""

    daily_limit: int = 10_000
    spent: int = 0

    def charge(self, units: int) -> None:
        if self.spent + units > self.daily_limit:
            raise QuotaExceeded(
                f"charging {units}u would exceed daily limit "
                f"({self.spent}/{self.daily_limit} spent)"
            )
        self.spent += units

    @property
    def remaining(self) -> int:
        return self.daily_limit - self.spent


class QuotaExceeded(RuntimeError):
    pass


class YouTubeClient(Protocol):
    """Thin seam over googleapiclient so tests can run without network or keys."""

    def search_list(self, q: str, max_results: int) -> dict: ...
    def videos_list(self, ids: list[str]) -> dict: ...


class GoogleYouTubeClient:
    """Real client. Requires YOUTUBE_API_KEY."""

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise RuntimeError("YOUTUBE_API_KEY is not set")
        from googleapiclient.discovery import build  # imported lazily

        self._yt = build("youtube", "v3", developerKey=key, cache_discovery=False)

    def search_list(self, q: str, max_results: int) -> dict:
        return (
            self._yt.search()
            .list(
                part="snippet",
                q=q,
                type="video",
                maxResults=max_results,
                videoEmbeddable="true",       # we only ever embed; unembeddable is useless
                relevanceLanguage="en",
            )
            .execute()
        )

    def videos_list(self, ids: list[str]) -> dict:
        return (
            self._yt.videos()
            .list(part="snippet,contentDetails,statistics", id=",".join(ids))
            .execute()
        )


class YouTubeSource(SourceAdapter):
    source = "youtube"

    def __init__(
        self,
        client: YouTubeClient | None = None,
        hint_cache: HintCache | None = None,
        quota: QuotaLedger | None = None,
        transcript_fetcher: "TranscriptFetcher | None" = None,
    ):
        self._client = client or GoogleYouTubeClient()
        self._cache = hint_cache if hint_cache is not None else InMemoryHintCache()
        self.quota = quota or QuotaLedger()
        self._transcripts = transcript_fetcher or YouTubeTranscriptFetcher()

    # -- discovery -------------------------------------------------------

    def search(self, hint: str, max_results: int = 25) -> list[str]:
        """Cache-first. A hit costs 0 quota units — that is the whole point."""
        cached = self._cache.get(hint)
        if cached is not None:
            ids, fetched_at = cached
            if datetime.now(timezone.utc) - fetched_at < HINT_CACHE_TTL:
                log.debug("hint_cache hit: %s (%d ids, 0u)", hint, len(ids))
                return ids

        self.quota.charge(SEARCH_COST_UNITS)
        resp = self._client.search_list(hint, max_results)
        ids = [
            item["id"]["videoId"]
            for item in resp.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        self._cache.put(hint, ids)
        log.debug("search '%s' -> %d ids (%du)", hint, len(ids), SEARCH_COST_UNITS)
        return ids

    def search_with_shorts_variants(self, hint: str, max_results: int = 25) -> list[str]:
        """Stage 3: also run the '#shorts' variant. Creators pre-clip the moment."""
        ids = list(self.search(hint, max_results))
        seen = set(ids)
        for vid in self.search(f"{hint} #shorts", max_results):
            if vid not in seen:
                seen.add(vid)
                ids.append(vid)
        return ids

    # -- metadata --------------------------------------------------------

    def fetch_metadata(self, video_ids: list[str]) -> list[VideoMeta]:
        """Batched 50/call at 1 unit each."""
        out: list[VideoMeta] = []
        for i in range(0, len(video_ids), VIDEOS_LIST_BATCH):
            batch = video_ids[i : i + VIDEOS_LIST_BATCH]
            self.quota.charge(VIDEOS_LIST_COST_UNITS)
            resp = self._client.videos_list(batch)
            for item in resp.get("items", []):
                out.append(self._to_meta(item))
        return out

    @staticmethod
    def _to_meta(item: dict) -> VideoMeta:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        details = item.get("contentDetails", {})
        duration_s = parse_iso8601_duration(details.get("duration", ""))
        published_at = None
        if raw := snippet.get("publishedAt"):
            published_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return VideoMeta(
            id=item["id"],
            source=classify_source(duration_s),
            title=snippet.get("title"),
            channel_id=snippet.get("channelId"),
            channel_name=snippet.get("channelTitle"),
            duration_s=duration_s,
            published_at=published_at,
            view_count=int(stats["viewCount"]) if "viewCount" in stats else None,
            like_count=int(stats["likeCount"]) if "likeCount" in stats else None,
            lang=snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage"),
        )

    # -- transcripts -----------------------------------------------------

    def fetch_transcript(self, video_id: str) -> Transcript | None:
        """Stage 4 chain: manual captions -> auto captions -> Whisper -> skip.

        When `DEEPCLIP_WHISPER=1`, an IP block or missing captions falls through
        to Whisper over yt-dlp audio (a different, unblocked host). Otherwise the
        caption fetcher's behaviour is unchanged and an IP block still raises so
        the build can report it.
        """
        from ..pipeline.transcripts_whisper import (
            fetch_with_whisper_fallback,
            whisper_enabled,
        )

        if whisper_enabled():
            return fetch_with_whisper_fallback(video_id, self._transcripts)
        return self._transcripts.fetch(video_id)

    # -- playback --------------------------------------------------------

    def embed_url(
        self, video_id: str, t_start: float | None = None, t_end: float | None = None
    ) -> str:
        params = ["enablejsapi=1"]
        if t_start is not None:
            params.append(f"start={int(t_start)}")
        if t_end is not None:
            params.append(f"end={int(t_end)}")
        return f"https://www.youtube.com/embed/{video_id}?{'&'.join(params)}"

    @staticmethod
    def credit_url(video_id: str, t_start: float | None = None) -> str:
        """Link to the original. Non-negotiable per C5."""
        base = f"https://www.youtube.com/watch?v={video_id}"
        return f"{base}&t={int(t_start)}s" if t_start else base


class TranscriptFetcher(Protocol):
    def fetch(self, video_id: str) -> Transcript | None: ...


class TranscriptIpBlocked(RuntimeError):
    """YouTube is blocking transcript requests from this IP.

    Distinct from "this video has no captions": the block is an infra condition
    affecting *every* video, is transient, and is fixed by a proxy or by waiting.
    Surfacing it as a distinct error stops a build from reporting "no captions
    anywhere" — a misleading message that hides the real cause. This is the B4
    fragility (transcript scraping) made concrete.
    """


class YouTubeTranscriptFetcher:
    """youtube-transcript-api, preferring manual tracks over auto-generated.

    `transcript_kind` is recorded because it is a ranking prior in stage 6 —
    auto-captions mangle proper nouns ('Jinnah' -> 'gina').

    Proxy support (env): YouTube IP-blocks the scraped caption endpoint under
    load, which is the single biggest reliability risk in the pipeline. Set
    `YTT_PROXY_HTTP` / `YTT_PROXY_HTTPS` (generic) or `WEBSHARE_PROXY_USER` /
    `WEBSHARE_PROXY_PASS` (Webshare residential) to route around it in production.
    """

    def __init__(self, languages: tuple[str, ...] = ("en",)):
        self.languages = languages
        self._proxy_config = self._build_proxy_config()

    @staticmethod
    def _build_proxy_config():
        """Construct a proxy config from env, if any. None means direct."""
        try:
            user = os.environ.get("WEBSHARE_PROXY_USER")
            pw = os.environ.get("WEBSHARE_PROXY_PASS")
            if user and pw:
                from youtube_transcript_api.proxies import WebshareProxyConfig

                return WebshareProxyConfig(proxy_username=user, proxy_password=pw)
            http = os.environ.get("YTT_PROXY_HTTP")
            https = os.environ.get("YTT_PROXY_HTTPS")
            if http or https:
                from youtube_transcript_api.proxies import GenericProxyConfig

                return GenericProxyConfig(http_url=http, https_url=https or http)
        except Exception as exc:  # noqa: BLE001 - proxy is optional
            log.warning("proxy config unavailable: %s", exc)
        return None

    def _listing(self, video_id: str):
        """Handle both library generations.

        >=1.0 exposes instance methods (`.list()`); older releases used the
        static `list_transcripts`. Getting this wrong fails silently — every
        video looks like it simply has no captions — so both are supported.
        """
        from youtube_transcript_api import YouTubeTranscriptApi

        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            return YouTubeTranscriptApi.list_transcripts(video_id)
        kwargs = {"proxy_config": self._proxy_config} if self._proxy_config else {}
        return YouTubeTranscriptApi(**kwargs).list(video_id)

    @staticmethod
    def _to_cues(raw) -> list[TranscriptCue]:
        """Snippet objects (>=1.0) and plain dicts (older) both appear here."""
        cues = []
        for c in raw:
            if isinstance(c, dict):
                start, dur, text = c["start"], c.get("duration", 0.0), c["text"]
            else:
                start, dur, text = c.start, getattr(c, "duration", 0.0), c.text
            cues.append(
                TranscriptCue(
                    t_start=float(start),
                    t_end=float(start) + float(dur),
                    text=text,
                )
            )
        return cues

    def fetch(self, video_id: str) -> Transcript | None:
        try:
            listing = self._listing(video_id)
        except ImportError:  # pragma: no cover
            log.warning("youtube-transcript-api not installed")
            return None
        except Exception as exc:
            # An IP block affects every request, so it must not be swallowed as
            # "this one video has no captions" — raise it so the build reports
            # the real cause and can stop early instead of failing on all videos.
            if type(exc).__name__ in {"IpBlocked", "RequestBlocked"} or "blocking requests from your IP" in str(exc):
                raise TranscriptIpBlocked(str(exc)[:200]) from exc
            log.info("no transcript listing for %s: %s", video_id, exc)
            return None

        langs = list(self.languages)
        for kind, attr in (
            ("manual", "find_manually_created_transcript"),
            ("auto", "find_generated_transcript"),
        ):
            finder = getattr(listing, attr, None)
            if finder is None:  # pragma: no cover
                continue
            try:
                track = finder(langs)
                raw = track.fetch()
            except Exception:
                continue
            return Transcript(
                video_id=video_id,
                kind=kind,
                lang=getattr(track, "language_code", None),
                cues=self._to_cues(raw),
            )
        return None

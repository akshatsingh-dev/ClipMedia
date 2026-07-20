"""SourceAdapter ABC.

Ingestion sits behind this interface so Vimeo / archive.org / podcast video can be
added later without touching the pipeline (master doc B4).

Legal posture, load-bearing:
  - Outbound discovery is YouTube-only, via the official Data API.
  - Instagram/TikTok are inbound-only (user-pasted links), oEmbed display only.
    Adapters for those MUST leave `search` unimplemented.
  - We never download or host video. Playback is always an official embed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class VideoMeta:
    id: str
    source: str  # 'youtube'|'youtube_shorts'|'instagram'|'tiktok'
    title: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    duration_s: int | None = None
    published_at: datetime | None = None
    view_count: int | None = None
    like_count: int | None = None
    lang: str | None = None


@dataclass
class TranscriptCue:
    """One caption cue. `t_end` is exclusive."""

    t_start: float
    t_end: float
    text: str


@dataclass
class Transcript:
    video_id: str
    kind: str  # 'manual'|'auto'|'whisper'
    lang: str | None
    cues: list[TranscriptCue] = field(default_factory=list)


class SearchUnsupported(NotImplementedError):
    """Raised by inbound-only adapters. Outbound discovery would violate ToS."""


class SourceAdapter(ABC):
    source: str

    @abstractmethod
    def search(self, hint: str, max_results: int = 25) -> list[str]:
        """Discovery. Returns video ids. Inbound-only sources raise SearchUnsupported."""

    @abstractmethod
    def fetch_metadata(self, video_ids: list[str]) -> list[VideoMeta]:
        """Batch metadata. Implementations should batch to minimise quota."""

    @abstractmethod
    def fetch_transcript(self, video_id: str) -> Transcript | None:
        """Transcript via the source's fallback chain. None = no transcript available."""

    @abstractmethod
    def embed_url(self, video_id: str, t_start: float | None, t_end: float | None) -> str:
        """Official embed URL, seeked. Never a media file URL."""

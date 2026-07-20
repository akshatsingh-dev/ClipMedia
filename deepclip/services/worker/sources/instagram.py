"""Instagram adapter — INBOUND ONLY.

Meta's Graph API returns data only for Business/Creator accounts you own; you
cannot fetch arbitrary public content. The oEmbed endpoint is restricted to
front-end display — using its metadata or content derivations for any other
purpose is explicitly prohibited (master doc B4).

Therefore:
  - `search` always raises. There is no compliant outbound discovery path.
  - We never download media. `embed_html` is rendered unmodified.
  - Analysis happens only on user-initiated links, from public caption text.
"""

from __future__ import annotations

import re

from .base import SearchUnsupported, SourceAdapter, Transcript, VideoMeta

_SHORTCODE = re.compile(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")


def parse_shortcode(url: str) -> str | None:
    m = _SHORTCODE.search(url or "")
    return m.group(1) if m else None


class InstagramSource(SourceAdapter):
    source = "instagram"

    def search(self, hint: str, max_results: int = 25) -> list[str]:
        raise SearchUnsupported(
            "Instagram discovery would violate Meta ToS. Inbound links only."
        )

    def fetch_metadata(self, video_ids: list[str]) -> list[VideoMeta]:
        # Only what oEmbed returns for display; no derived storage.
        return [VideoMeta(id=vid, source=self.source) for vid in video_ids]

    def fetch_transcript(self, video_id: str) -> Transcript | None:
        # No transcript access. Stage-4 equivalent is caption text the user supplied.
        return None

    def embed_url(
        self, video_id: str, t_start: float | None = None, t_end: float | None = None
    ) -> str:
        # Seeking is unsupported by the IG embed; t_start/t_end are ignored by design.
        return f"https://www.instagram.com/reel/{video_id}/embed"

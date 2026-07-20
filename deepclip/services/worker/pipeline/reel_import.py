"""Reel-import (master doc A4.3 / C3).

Paste a clip you liked, get a path that goes deeper (Learn) or serves more of the
same vibe (Entertain).

Platform rules are legal constraints, not preferences (B4):
  YouTube/Shorts  full pipeline access — transcript, analysis, retrieval.
  Instagram       oEmbed display only. We never download media and never crawl.
                  Analysis runs on the PUBLIC CAPTION TEXT the user hands us,
                  from a user-initiated action, and nothing else.
  TikTok          same as Instagram, post-MVP.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..llm.client import MODEL_SMART, LLMClient, extract_json
from .build import BuildDeps, BuildResult, build_page
from .outline import normalize_query

log = logging.getLogger(__name__)

YT_PATTERNS = (
    re.compile(r"youtube\.com/watch\?(?:.*&)?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"),
)
IG_PATTERN = re.compile(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")
TIKTOK_PATTERN = re.compile(r"tiktok\.com/(?:@[\w.]+/video/(\d+)|v/(\d+))")

ANALYSIS_SYSTEM = """You analyse a single short video and infer what a viewer who \
liked it would want next.

Return:
- mode: "learn" if the clip teaches or explains something; "entertain" if its \
appeal is reaction, spectacle, comedy, or skill.
- topic / subtopic: what it is actually about.
- depth_level: 1-5, how advanced the treatment is (learn only).
- vibe: the flavour of the appeal (entertain only).
- next_query: the query that would build the ideal follow-up page. For learn, aim \
one depth level HIGHER than the seed. For entertain, preserve the vibe.

Output JSON only."""

ANALYSIS_PROMPT = """Source: {platform}
Title: {title}
Channel: {channel}

Content:
{content}

Return JSON:
{{"mode":"learn|entertain","topic":"...","subtopic":"...","depth_level":1-5,
  "vibe":"...","next_query":"...","confidence":0.0-1.0}}"""


@dataclass
class SeedAnalysis:
    platform: str
    source_id: str
    mode: str
    topic: str
    subtopic: str = ""
    depth_level: int = 1
    vibe: str = ""
    next_query: str = ""
    confidence: float = 0.0
    needs_confirmation: bool = False

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "source_id": self.source_id,
            "mode": self.mode,
            "topic": self.topic,
            "subtopic": self.subtopic,
            "depth_level": self.depth_level,
            "vibe": self.vibe,
            "next_query": self.next_query,
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
        }


class UnsupportedSource(ValueError):
    pass


def resolve_platform(url: str) -> tuple[str, str]:
    """(platform, id). Raises UnsupportedSource for anything else."""
    text = (url or "").strip()
    for pattern in YT_PATTERNS:
        m = pattern.search(text)
        if m:
            return "youtube", m.group(1)
    m = IG_PATTERN.search(text)
    if m:
        return "instagram", m.group(1)
    m = TIKTOK_PATTERN.search(text)
    if m:
        return "tiktok", m.group(1) or m.group(2)
    raise UnsupportedSource(f"unrecognised or unsupported URL: {url!r}")


def instagram_embed_html(shortcode: str) -> str:
    """Official embed markup, rendered unmodified.

    Meta's oEmbed terms restrict this to front-end display, so it is never parsed
    for metadata or used to derive anything.
    """
    return (
        f'<blockquote class="instagram-media" '
        f'data-instgrm-permalink="https://www.instagram.com/reel/{shortcode}/" '
        f'data-instgrm-version="14"></blockquote>'
    )


def analyse_seed(
    platform: str,
    source_id: str,
    llm: LLMClient,
    title: str = "",
    channel: str = "",
    content: str = "",
) -> SeedAnalysis:
    resp = llm.complete(
        ANALYSIS_PROMPT.format(
            platform=platform,
            title=title or "(unknown)",
            channel=channel or "(unknown)",
            content=(content or "(no text available)")[:6000],
        ),
        system=ANALYSIS_SYSTEM,
        model=MODEL_SMART,
        max_tokens=1024,
    )
    data = extract_json(resp.text)
    if not isinstance(data, dict):
        data = {}

    mode = str(data.get("mode", "learn")).strip().lower()
    if mode not in {"learn", "entertain"}:
        mode = "learn"

    try:
        depth = int(data.get("depth_level") or 1)
    except (TypeError, ValueError):
        depth = 1
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    topic = str(data.get("topic") or "").strip()
    next_query = str(data.get("next_query") or topic).strip()

    return SeedAnalysis(
        platform=platform,
        source_id=source_id,
        mode=mode,
        topic=topic,
        subtopic=str(data.get("subtopic") or "").strip(),
        depth_level=max(1, min(5, depth)),
        vibe=str(data.get("vibe") or "").strip(),
        next_query=next_query,
        confidence=max(0.0, min(1.0, confidence)),
        # Instagram/TikTok analysis rests on caption text alone, which is thin.
        # The spec requires a one-tap user confirmation before building on it.
        needs_confirmation=platform in {"instagram", "tiktok"} or confidence < 0.5,
    )


def import_seed(
    url: str,
    deps: BuildDeps,
    caption_text: str = "",
    confirmed_query: str | None = None,
) -> tuple[dict, BuildResult]:
    """Analyse a pasted link and build the follow-on page.

    `caption_text` is required for Instagram/TikTok: we cannot fetch it, so the
    client must pass what the user supplied. `confirmed_query` carries the user's
    one-tap confirmation back in.
    """
    platform, source_id = resolve_platform(url)

    title = channel = ""
    content = caption_text

    if platform == "youtube":
        try:
            metas = deps.youtube.fetch_metadata([source_id])
            if metas:
                title = metas[0].title or ""
                channel = metas[0].channel_name or ""
        except Exception as exc:  # noqa: BLE001
            log.info("metadata unavailable for %s: %s", source_id, exc)
        transcript = deps.youtube.fetch_transcript(source_id)
        if transcript:
            # Head of the transcript is enough to classify; sending the whole
            # thing would cost tokens for no additional signal.
            content = " ".join(c.text for c in transcript.cues)[:6000]
    elif platform in {"instagram", "tiktok"} and not caption_text:
        raise UnsupportedSource(
            f"{platform} import requires user-supplied caption text; "
            "we do not crawl or fetch media from this platform"
        )

    analysis = analyse_seed(
        platform, source_id, deps.llm, title=title, channel=channel, content=content
    )

    query = confirmed_query or analysis.next_query
    if not query:
        raise UnsupportedSource("could not infer a follow-up query from this clip")

    result = build_page(query, deps, mode_hint=analysis.mode)

    payload = analysis.to_dict()
    payload["seed_url"] = url
    payload["built_query"] = query
    payload["built_slug"] = normalize_query(query)
    if platform == "instagram":
        payload["embed_html"] = instagram_embed_html(source_id)
    return payload, result


def share_card_text(analysis: dict) -> str:
    """OG share-card copy (C3): 'From 1 reel -> the full picture of {topic}.'"""
    topic = (analysis or {}).get("topic") or "this"
    if (analysis or {}).get("mode") == "entertain":
        return f"From 1 clip → the best of {topic}."
    return f"From 1 reel → the full picture of {topic}."

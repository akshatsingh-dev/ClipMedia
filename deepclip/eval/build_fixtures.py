"""Resolve golden page definitions into rendered page JSON.

Titles, channel names and thumbnails come from YouTube's public oEmbed endpoint,
which needs no API key. Any video id that fails to resolve is dropped with a
warning rather than shipped as a broken embed.

    python3 -m eval.build_fixtures

Writes apps/web/public/fixtures/<slug>.json plus index.json.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from eval.golden.pages import ALL_PAGES

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "apps" / "web" / "public" / "fixtures"
OEMBED = "https://www.youtube.com/oembed"
TIMEOUT_S = 10


def _ssl_context():
    """macOS system Python ships without a usable root store; certifi supplies one."""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


def resolve(video_id: str) -> dict | None:
    """Public oEmbed lookup. Returns None if the video is gone or private."""
    url = f"{OEMBED}?{urllib.parse.urlencode({'url': f'https://www.youtube.com/watch?v={video_id}', 'format': 'json'})}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S, context=_SSL) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
        print(f"  ! {video_id}: unresolvable ({exc})", file=sys.stderr)
        return None
    return {
        "video_title": data.get("title"),
        "channel": data.get("author_name"),
        "channel_url": data.get("author_url"),
        "thumbnail": data.get("thumbnail_url"),
    }


def build_clip(clip: dict, meta: dict) -> dict:
    vid = clip["video_id"]
    t_start = clip["t_start"]
    return {
        "video_id": vid,
        "t_start": t_start,
        "t_end": clip["t_end"],
        "why": clip.get("why", ""),
        # Attribution is non-negotiable (C5) — every clip links back to the original.
        "credit_url": f"https://www.youtube.com/watch?v={vid}&t={int(t_start)}s",
        **meta,
    }


def build_page(page: dict, cache: dict[str, dict | None]) -> dict:
    print(f"building {page['slug']} ({page['mode']})")
    out = {
        "slug": page["slug"],
        "query": page["query"],
        "title": page["title"],
        "subtitle": page.get("subtitle", ""),
        "mode": page["mode"],
        # See DECISIONS D3 — the UI surfaces this as a banner.
        "timestamps_verified": False,
        "source_note": (
            "Video metadata is real (resolved via YouTube oEmbed). Clip timestamps "
            "are unverified placeholders pending hand-curation."
        ),
    }

    sections = page.get("chapters") or page.get("groups") or []
    built_sections = []
    dropped = 0
    for section in sections:
        clips = []
        for clip in section["clips"]:
            vid = clip["video_id"]
            if vid not in cache:
                cache[vid] = resolve(vid)
            meta = cache[vid]
            if meta is None:
                dropped += 1
                continue
            clips.append(build_clip(clip, meta))
        if not clips:
            continue
        built = {"clips": clips}
        if page["mode"] == "learn":
            built["title"] = section["title"]
            built["intro_text"] = section.get("intro_text", "")
        else:
            built["label"] = section["label"]
        built_sections.append(built)

    key = "chapters" if page["mode"] == "learn" else "groups"
    out[key] = built_sections
    total = sum(len(s["clips"]) for s in built_sections)
    print(f"  {len(built_sections)} sections, {total} clips" + (f", {dropped} dropped" if dropped else ""))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict | None] = {}
    index = []
    for page in ALL_PAGES:
        built = build_page(page, cache)
        sections = built.get("chapters", built.get("groups", []))
        if not sections:
            # An empty fixture renders as a blank page that looks like a UI bug.
            # Better to fail here than to ship one.
            print(f"FATAL: {built['slug']} resolved to zero clips", file=sys.stderr)
            return 1
        (OUT_DIR / f"{built['slug']}.json").write_text(json.dumps(built, indent=2))
        index.append(
            {
                "slug": built["slug"],
                "title": built["title"],
                "subtitle": built["subtitle"],
                "mode": built["mode"],
                "query": built["query"],
                "clip_count": sum(
                    len(s["clips"]) for s in built.get("chapters", built.get("groups", []))
                ),
            }
        )
    (OUT_DIR / "index.json").write_text(json.dumps(index, indent=2))
    print(f"\nwrote {len(index)} pages -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

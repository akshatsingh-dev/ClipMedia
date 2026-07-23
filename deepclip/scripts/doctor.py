"""Preflight: which external dependency is broken right now, and what fixes it.

Every stall in this project so far has been an external condition — YouTube's
daily quota, the caption endpoint IP-block, the audio endpoint 403, the Gemini
free-tier ceiling — and each one surfaces deep inside a build as a different
error. This checks all of them in one shot, cheaply (a probe costs 1 YouTube
unit, not the 100 a search costs), and says what is buildable *today*.

    python3 -m scripts.doctor          # all checks
    python3 -m scripts.doctor --quick  # skip the slow audio probe

Exit code 0 if a real build is possible right now, 1 if it is not.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

# A long-lived video that reliably carries English captions (3Blue1Brown, "But
# what is a neural network?"). The caption check is meaningless against a video
# that simply has none — "no captions" then reads as a block that isn't there.
PROBE_VIDEO = os.environ.get("DEEPCLIP_PROBE_VIDEO", "aircAruvnKk")

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == FAIL


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() or None if v else None


# -- individual checks ---------------------------------------------------


def check_keys() -> list[Check]:
    out = []
    for name, why in (
        ("YOUTUBE_API_KEY", "retrieval (stage 2) cannot run without it"),
        ("GEMINI_API_KEY", "outline/assembly (stages 1, 7) cannot run without it"),
    ):
        if _env(name):
            out.append(Check(name, OK, "set"))
        elif name == "GEMINI_API_KEY" and _env("ANTHROPIC_API_KEY"):
            out.append(Check(name, OK, "unset, but ANTHROPIC_API_KEY is set"))
        else:
            out.append(
                Check(name, FAIL, f"missing — {why}", f"add {name} to deepclip/.env")
            )
    return out


def check_postgres() -> Check:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return Check("postgres", FAIL, "DATABASE_URL unset", "see STATUS.md 'Restarting the stack'")

    async def probe():
        import asyncpg

        conn = await asyncpg.connect(url, timeout=5)
        try:
            has_vec = await conn.fetchval(
                "select exists(select 1 from pg_extension where extname='vector')"
            )
            pages = await conn.fetchval("select count(*) from deep_pages")
            return has_vec, pages
        finally:
            await conn.close()

    try:
        has_vec, pages = asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001
        return Check(
            "postgres", FAIL, f"unreachable: {type(exc).__name__}: {exc}",
            "docker compose up -d postgres redis",
        )
    if not has_vec:
        return Check("postgres", FAIL, "pgvector extension missing", "apply packages/db/schema.sql")
    return Check("postgres", OK, f"up, pgvector present, {pages} built page(s)")


def check_redis() -> Check:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    async def probe():
        from redis.asyncio import from_url

        r = from_url(url)
        try:
            await r.ping()
        finally:
            await r.aclose()

    try:
        asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001
        return Check(
            "redis", FAIL, f"unreachable: {type(exc).__name__}: {exc}",
            "docker compose up -d redis  (no redis = no worker = no builds)",
        )
    return Check("redis", OK, "up")


def check_youtube_quota() -> Check:
    """One videos.list call: 1 unit of the 10k/day, vs. 100 for a search."""
    if not _env("YOUTUBE_API_KEY"):
        return Check("youtube api", FAIL, "skipped — no API key", "add YOUTUBE_API_KEY")
    from services.worker.sources.youtube import GoogleYouTubeClient, _is_quota_error

    try:
        resp = GoogleYouTubeClient().videos_list([PROBE_VIDEO])
    except Exception as exc:  # noqa: BLE001
        if _is_quota_error(exc):
            return Check(
                "youtube api", FAIL, "daily quota exhausted (429)",
                "wait for midnight Pacific, or file for a quota increase "
                "(console.cloud.google.com -> YouTube Data API -> Quotas)",
            )
        return Check("youtube api", FAIL, f"{type(exc).__name__}: {exc}", "check the key and that the API is enabled")
    n = len(resp.get("items", []))
    return Check("youtube api", OK if n else WARN, f"reachable, quota available ({n} item)")


def check_captions() -> Check:
    from services.worker.sources.youtube import TranscriptIpBlocked, YouTubeTranscriptFetcher

    proxied = bool(
        _env("WEBSHARE_PROXY_USER") or _env("YTT_PROXY_HTTP") or _env("YTT_PROXY_HTTPS")
    )
    try:
        t = YouTubeTranscriptFetcher().fetch(PROBE_VIDEO)
    except TranscriptIpBlocked as exc:
        return Check(
            "captions (fast path)", FAIL, f"IP-blocked: {exc}",
            "set WEBSHARE_PROXY_USER/PASS (residential proxy, a few $/mo) "
            "or wait out the block; Whisper is the fallback meanwhile",
        )
    except Exception as exc:  # noqa: BLE001
        return Check("captions (fast path)", WARN, f"{type(exc).__name__}: {exc}", "")
    where = " via proxy" if proxied else ""
    if t is None:
        return Check("captions (fast path)", WARN, f"probe video has no captions{where}", "")
    return Check("captions (fast path)", OK, f"working{where} ({len(t.cues)} cues)")


def check_audio() -> Check:
    """Metadata-only probe of the audio host — no download, no bytes stored."""
    from services.worker.pipeline.transcripts_whisper import (
        PLAYER_CLIENT_CHAIN,
        _is_refusal,
        audio_proxy_url,
    )

    try:
        import yt_dlp
    except ImportError:
        return Check("audio (whisper path)", FAIL, "yt-dlp not installed", "pip install -r requirements.txt")

    proxy = audio_proxy_url()
    base = {"quiet": True, "no_warnings": True, "noplaylist": True, "retries": 1, "skip_download": True}
    if proxy:
        base["proxy"] = proxy
    if _env("YTDLP_COOKIES_FILE"):
        base["cookiefile"] = os.environ["YTDLP_COOKIES_FILE"]

    refusals = []
    for client in PLAYER_CLIENT_CHAIN:
        opts = dict(base, extractor_args={"youtube": {"player_client": [client]}})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={PROBE_VIDEO}", download=False)
            return Check(
                "audio (whisper path)", OK,
                f"reachable via {client} client{' + proxy' if proxy else ''}",
            )
        except Exception as exc:  # noqa: BLE001
            if not _is_refusal(exc):
                return Check("audio (whisper path)", WARN, f"{type(exc).__name__}: {exc}", "")
            refusals.append(client)
    return Check(
        "audio (whisper path)", FAIL,
        f"every player client refused ({', '.join(refusals)})",
        "set DEEPCLIP_YTDLP_PROXY or WEBSHARE_PROXY_USER/PASS, or YTDLP_COOKIES_FILE",
    )


def check_whisper_deps() -> Check:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return Check("whisper runtime", WARN, "faster-whisper not installed", "pip install -r requirements.txt")
    on = os.environ.get("DEEPCLIP_WHISPER", "").lower() in {"1", "true", "yes"}
    return Check(
        "whisper runtime", OK if on else WARN,
        "installed and enabled" if on else "installed but OFF",
        "" if on else "export DEEPCLIP_WHISPER=1 to enable the fallback",
    )


def check_llm() -> Check:
    if not (_env("GEMINI_API_KEY") or _env("ANTHROPIC_API_KEY")):
        return Check("llm", FAIL, "no provider key", "add GEMINI_API_KEY to .env")
    from services.worker.llm.client import MODEL_FAST, build_client

    try:
        client = build_client()
        resp = client.complete(
            "ping",
            system="Reply with the single word: ok",
            model=MODEL_FAST,
            max_tokens=8,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "429" in msg or "quota" in msg.lower() or "exhaust" in msg.lower():
            return Check(
                "llm", FAIL, "free-tier quota exhausted (429)",
                "wait for the daily reset, or enable billing on the Gemini key",
            )
        return Check("llm", FAIL, f"{type(exc).__name__}: {msg[:160]}", "check the key/model names")
    return Check("llm", OK, f"reachable ({resp.text.strip()[:20]!r})")


def check_services() -> list[Check]:
    import urllib.request

    out = []
    for name, url in (("api", "http://localhost:8000/healthz"), ("web", "http://localhost:3000")):
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                code = r.status
            out.append(Check(name, OK if code < 400 else WARN, f"HTTP {code}"))
        except Exception as exc:  # noqa: BLE001
            out.append(
                Check(name, WARN, f"down ({type(exc).__name__})", "see STATUS.md 'Restarting the stack'")
            )
    return out


# -- report --------------------------------------------------------------


def verdict(checks: list[Check]) -> tuple[bool, str]:
    """What can actually be built right now, given what failed."""
    by = {c.name: c.status for c in checks}
    quota_ok = by.get("youtube api") == OK
    audio = by.get("audio (whisper path)")  # absent under --quick
    # Either path yields a transcript, so one working path is enough. Under
    # --quick the audio path is unchecked, not known-broken — reporting it as
    # blocked would be the same false negative the caption check used to give.
    transcripts_ok = by.get("captions (fast path)") == OK or audio in (OK, None)
    llm_ok = by.get("llm") == OK
    db_ok = by.get("postgres") == OK

    if quota_ok and transcripts_ok and llm_ok and db_ok:
        return True, "Live builds work. Run one."
    reasons = []
    if not quota_ok:
        reasons.append("YouTube search quota")
    if not transcripts_ok:
        reasons.append("both transcript paths (captions AND audio)")
    if not llm_ok:
        reasons.append("the LLM")
    if not db_ok:
        reasons.append("Postgres")
    blocked = "Live builds are blocked by: " + "; ".join(reasons) + "."
    if db_ok:
        blocked += (
            "\nStill possible with no quota and no LLM: perspective streams "
            "(create/edit/share), saved pages, the tutor on already-built pages, "
            "frontend work, and the full offline test suite."
        )
    return False, blocked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="skip the slow audio probe")
    args = ap.parse_args(argv)

    checks: list[Check] = []
    checks += check_keys()
    checks.append(check_postgres())
    checks.append(check_redis())
    checks += check_services()
    checks.append(check_youtube_quota())
    checks.append(check_captions())
    if not args.quick:
        checks.append(check_audio())
    checks.append(check_whisper_deps())
    checks.append(check_llm())

    width = max(len(c.name) for c in checks)
    print()
    for c in checks:
        # One line per check: a wrapped provider message buries the verdict.
        detail = " ".join(c.detail.split())[:110]
        print(f"  {MARK[c.status]:4}  {c.name:<{width}}  {detail}")
        if c.fix and c.status != OK:
            print(f"        {'':<{width}}  -> {c.fix}")
    ok, message = verdict(checks)
    print("\n" + message + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

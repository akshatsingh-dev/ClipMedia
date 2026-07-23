"""FastAPI gateway.

Routes (C1):
  GET  /api/pages/{slug}      cached page or 404
  POST /api/build             enqueue a build, returns job id
  GET  /api/build/{id}/stream SSE progress for a live build
  POST /api/import            reel-import
  GET  /api/feed/{slug}       entertain feed
  GET  /healthz

Cache-first: a hit serves from Postgres for ~$0. A miss enqueues onto arq and the
client follows the SSE stream, so the outline renders in ~5s even when the full
build takes 60s (C5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from packages.db.repo import EventRow, Repo
from services.worker.pipeline.outline import normalize_query

from .progress import ProgressBus, ProgressEvent
from .ratelimit import (
    BUILD_LIMIT,
    IMPORT_LIMIT,
    InMemoryRateLimiter,
    Limit,
    RedisRateLimiter,
    client_key,
)

log = logging.getLogger(__name__)

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

STARTUP_TIMEOUT_S = float(os.environ.get("STARTUP_TIMEOUT_S", "3"))
# Configurable so tests can bound the stream: a client that never signals
# disconnect would otherwise hold the generator open for the full timeout.
SSE_KEEPALIVE_S = float(os.environ.get("SSE_KEEPALIVE_S", "15"))
SSE_TIMEOUT_S = float(os.environ.get("SSE_TIMEOUT_S", "300"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.repo = None
    app.state.queue = None
    app.state.bus = ProgressBus()
    # In-memory limiter always exists as a floor; upgraded to Redis-backed below
    # once the queue connects, so limiting is correct across API processes.
    app.state.limiter = InMemoryRateLimiter()
    app.state.redis_limiter = None
    app.state.llm = None  # built lazily by the tutor
    # Startup must not block on unreachable infrastructure: the API still serves
    # /healthz and 503s without a DB, which is what makes local frontend work
    # possible with nothing else running. arq in particular retries for ~5s.
    try:
        app.state.repo = await asyncio.wait_for(Repo.connect(), timeout=STARTUP_TIMEOUT_S)
        log.info("connected to postgres")
    except Exception as exc:  # noqa: BLE001
        log.warning("no database connection: %s", exc)
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        app.state.queue = await asyncio.wait_for(
            create_pool(
                RedisSettings.from_dsn(
                    os.environ.get("REDIS_URL", "redis://localhost:6379")
                )
            ),
            timeout=STARTUP_TIMEOUT_S,
        )
        log.info("connected to redis")
    except Exception as exc:  # noqa: BLE001
        log.warning("no queue connection: %s", exc)

    # Reuse the arq redis connection for cross-process rate limiting when present.
    try:
        if app.state.queue is not None:
            from redis.asyncio import Redis

            app.state.redis_limiter = RedisRateLimiter(
                Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("no redis rate limiter: %s", exc)

    yield

    if app.state.repo:
        await app.state.repo.close()
    if app.state.queue:
        await app.state.queue.close()


app = FastAPI(title="Deep Clip Search", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class BuildRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    mode: str | None = Field(default=None, pattern="^(learn|entertain)$")


class ImportRequest(BaseModel):
    url: str = Field(min_length=5, max_length=500)
    # Required for Instagram/TikTok: we cannot fetch their content, so the user
    # supplies the caption. Dropping it here would make those imports fail with
    # a confusing error rather than working.
    caption_text: str | None = Field(default=None, max_length=5000)
    confirmed_query: str | None = Field(default=None, max_length=300)


class EventIn(BaseModel):
    anon_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    slug: str | None = Field(default=None, max_length=300)
    mode: str | None = Field(default=None, max_length=16)
    video_id: str | None = Field(default=None, max_length=32)
    position: int | None = None
    value: float | None = None
    meta: dict | None = None


class EventBatch(BaseModel):
    # A batch, because the client buffers and flushes with sendBeacon rather than
    # firing one request per interaction.
    events: list[EventIn] = Field(min_length=1, max_length=100)


def _repo(request: Request) -> Repo:
    repo = request.app.state.repo
    if repo is None:
        raise HTTPException(503, "database unavailable")
    return repo


async def _enforce_limit(request: Request, limit: Limit, bucket: str) -> None:
    """429 if the caller exceeded `limit`. Prefers the cross-process limiter."""
    key = f"{bucket}:{client_key(request)}"
    redis_limiter = request.app.state.redis_limiter
    if redis_limiter is not None:
        try:
            allowed = await redis_limiter.check(key, limit)
        except Exception as exc:  # noqa: BLE001 - never fail open silently
            log.warning("redis rate limit check failed, falling back: %s", exc)
            allowed = request.app.state.limiter.check(key, limit)
    else:
        allowed = request.app.state.limiter.check(key, limit)

    if not allowed:
        raise HTTPException(
            429,
            detail=(
                f"Rate limit: at most {limit.max_requests} {bucket} requests per "
                f"{int(limit.window_s)}s. Each build is expensive — try again shortly."
            ),
        )


@app.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "database": request.app.state.repo is not None,
        "queue": request.app.state.queue is not None,
    }


@app.get("/api/pages/{slug}")
async def get_page(slug: str, request: Request):
    """Cached page. Slug is the normalised query, so it is also the cache key."""
    page = await _repo(request).get_page(normalize_query(slug))
    if not page or page.get("status") != "ready":
        raise HTTPException(404, "page not built")
    return {
        "query": page["query_norm"],
        "mode": page["mode"],
        "status": page["status"],
        "page": page["page"],
        "built_at": page["built_at"].isoformat() if page.get("built_at") else None,
    }


@app.get("/api/feed/{slug}")
async def get_feed(slug: str, request: Request):
    page = await get_page(slug, request)
    if page["mode"] != "entertain":
        raise HTTPException(404, "not a feed")
    return page


@app.get("/api/pages")
async def list_pages(request: Request, limit: int = 50):
    rows = await _repo(request).list_pages(limit=min(limit, 200))
    return {
        "pages": [
            {
                "slug": r["query_norm"],
                "mode": r["mode"],
                "title": r["title"],
                "built_at": r["built_at"].isoformat() if r.get("built_at") else None,
            }
            for r in rows
        ]
    }


@app.post("/api/build")
async def build(req: BuildRequest, request: Request):
    """Enqueue a build, or return the cached page immediately.

    Returns 200 with `cached: true` on a hit so the client can skip the stream.
    """
    repo = _repo(request)
    slug = normalize_query(req.query)

    # Limit only when it would actually enqueue paid work — a cache hit is free,
    # so check after the cache lookup below rather than rejecting cached reads.
    existing = await repo.get_page(slug)
    if existing and existing.get("status") == "ready":
        return {"cached": True, "slug": slug, "mode": existing["mode"], "page": existing["page"]}
    if existing and existing.get("status") == "building":
        # Another request already owns this build; join its stream rather than
        # paying to build the same page twice.
        return {"cached": False, "slug": slug, "status": "building", "joined": True}

    queue = request.app.state.queue
    if queue is None:
        raise HTTPException(503, "build queue unavailable")

    # Paid path reached: enforce the limit now, not on cached hits above.
    await _enforce_limit(request, BUILD_LIMIT, "build")

    await repo.claim_page_build(slug, req.mode or "learn")
    job = await queue.enqueue_job("build_page", req.query, req.mode)
    return {"cached": False, "slug": slug, "status": "building", "job_id": job.job_id}


@app.post("/api/import")
async def import_reel(req: ImportRequest, request: Request):
    queue = request.app.state.queue
    if queue is None:
        raise HTTPException(503, "build queue unavailable")
    await _enforce_limit(request, IMPORT_LIMIT, "import")
    job = await queue.enqueue_job(
        "import_seed", req.url, req.caption_text, req.confirmed_query
    )
    return {"status": "processing", "job_id": job.job_id}


@app.get("/api/paths/{path_id}")
async def get_path(path_id: str, request: Request):
    path = await _repo(request).get_learning_path(path_id)
    if not path:
        raise HTTPException(404, "path not found")
    return {
        "id": str(path["id"]),
        "seed_url": path["seed_url"],
        "seed_analysis": path["seed_analysis"],
        "page": path["page"],
    }


@app.post("/api/events", status_code=202)
async def ingest_events(batch: EventBatch, request: Request):
    """Analytics ingestion. Fire-and-forget: always 202, never blocks the client.

    Invalid events are dropped rather than 4xx'd — a beacon cannot read a
    response and retrying analytics is pointless, so a bad event should vanish,
    not error. Returns how many were accepted for observability only.
    """
    repo = request.app.state.repo
    if repo is None:
        # No DB: accept and discard. Losing analytics must never surface to a user.
        return {"accepted": 0}

    rows = [
        EventRow(
            anon_id=e.anon_id, session_id=e.session_id, kind=e.kind, slug=e.slug,
            mode=e.mode, video_id=e.video_id, position=e.position, value=e.value,
            meta=e.meta,
        )
        for e in batch.events
    ]
    valid = [r for r in rows if r.valid()]
    try:
        written = await repo.insert_events(valid)
    except Exception as exc:  # noqa: BLE001 - analytics never breaks the app
        log.warning("event insert failed: %s", exc)
        return {"accepted": 0}
    return {"accepted": written}


@app.get("/api/metrics/{slug}")
async def get_metrics(slug: str, request: Request):
    """Read-only dashboard data for one page — the go/no-go numbers (D4/D8)."""
    repo = _repo(request)
    normalized = normalize_query(slug)
    completion = await repo.page_completion_rate(normalized)
    watch_depth = await repo.clip_watch_depth(normalized)
    sat = await repo.satisfaction(normalized)
    return {
        "slug": normalized,
        "completion": completion,
        "clip_watch_depth": watch_depth,
        "satisfaction": sat,
    }


@app.get("/api/metrics")
async def get_global_metrics(request: Request, within_days: int = 7):
    """Global return rate — the metric that separates a company from a feature."""
    repo = _repo(request)
    return await repo.return_rate(within_days=min(max(within_days, 1), 90))


@app.get("/api/reports")
async def get_reports(request: Request, limit: int = 100):
    """Review queue for reported clips (D6). Read-only; most-reported first."""
    repo = _repo(request)
    return {"reports": await repo.recent_reports(limit=min(max(limit, 1), 500))}


class SaveRequest(BaseModel):
    anon_id: str = Field(min_length=1, max_length=64)
    slug: str = Field(min_length=1, max_length=300)
    mode: str | None = Field(default=None, max_length=16)
    title: str | None = Field(default=None, max_length=300)


@app.post("/api/saved", status_code=201)
async def save_page(req: SaveRequest, request: Request):
    """Save a page for a user (D3). Keyed by anon_id, so no login required."""
    await _repo(request).save_page_for_user(req.anon_id, req.slug, req.mode, req.title)
    return {"saved": True, "slug": req.slug}


@app.delete("/api/saved")
async def unsave_page(request: Request, anon_id: str, slug: str):
    removed = await _repo(request).unsave_page_for_user(anon_id, slug)
    return {"removed": removed, "slug": slug}


@app.get("/api/saved")
async def list_saved(request: Request, anon_id: str, limit: int = 100):
    rows = await _repo(request).list_saved_pages(anon_id, limit=min(max(limit, 1), 200))
    return {"saved": rows}


class TutorRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=300)
    video_id: str = Field(min_length=1, max_length=32)
    t_start: float
    question: str = Field(min_length=1, max_length=500)


@app.post("/api/tutor")
async def ask_tutor(req: TutorRequest, request: Request):
    """'Ask about this clip' (B1). Answers grounded in the stored transcript.

    The transcript is read from the persisted page rather than trusted from the
    client, so the answer is grounded in the exact moment we curated.
    """
    from services.worker.pipeline.tutor import answer_question

    repo = _repo(request)
    page = await repo.get_page(normalize_query(req.slug))
    if not page or not page.get("page"):
        raise HTTPException(404, "page not found")

    transcript = _find_clip_transcript(page["page"], req.video_id, req.t_start)
    if transcript is None:
        raise HTTPException(404, "clip not found on this page")

    try:
        llm = request.app.state.llm or _get_llm(request)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "tutor unavailable: no LLM configured") from exc

    return answer_question(transcript, req.question, llm)


def _find_clip_transcript(page: dict, video_id: str, t_start: float) -> str | None:
    """Locate a clip's stored transcript by video and (approximate) start time."""
    for section in page.get("chapters") or page.get("groups") or []:
        for clip in section.get("clips", []):
            if clip.get("video_id") == video_id and abs(
                float(clip.get("t_start", -1)) - t_start
            ) < 2.0:
                return clip.get("transcript")
    return None


def _get_llm(request: Request):
    """Lazily build and cache an LLM client on the app for the tutor."""
    from services.worker.llm.client import build_client

    llm = build_client()
    request.app.state.llm = llm
    return llm


@app.get("/api/build/{slug}/stream")
async def stream_build(slug: str, request: Request):
    """SSE progress. Outline arrives first, sections fill as they rank (C5)."""
    normalized = normalize_query(slug)
    bus: ProgressBus = request.app.state.bus
    queue = bus.subscribe(normalized)

    async def gen():
        try:
            yield _sse(ProgressEvent(stage="connected", message="listening"))
            elapsed = 0.0
            while elapsed < SSE_TIMEOUT_S:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_S)
                except asyncio.TimeoutError:
                    elapsed += SSE_KEEPALIVE_S
                    # Comment frame keeps proxies from closing an idle stream.
                    yield ": keepalive\n\n"
                    continue
                elapsed = 0.0
                yield _sse(event)
                if event.stage in {"done", "failed"}:
                    break
        finally:
            bus.unsubscribe(normalized, queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx would otherwise buffer the stream
        },
    )


def _sse(event: ProgressEvent) -> str:
    return f"event: {event.stage}\ndata: {json.dumps(event.to_dict())}\n\n"

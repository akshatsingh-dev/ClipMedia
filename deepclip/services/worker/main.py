"""arq worker.

Thin wrapper over pipeline.build. Owns process-level concerns only: dependency
construction, progress publishing to Redis, and persisting the result.

Run:  arq services.worker.main.WorkerSettings
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import Any

from packages.db.repo import Repo
from services.api.progress import ProgressEvent, RedisProgressBus, overall_progress
from services.worker.llm.client import build_client
from services.worker.pipeline.build import BuildDeps, BuildFailed, build_page
from services.worker.pipeline.embed import build_embedder
from services.worker.pipeline.outline import normalize_query
from services.worker.sources.youtube import YouTubeSource

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger(__name__)

# A page build is LLM- and network-bound; 10 minutes is generous but a stuck
# build must not hold a worker slot forever.
JOB_TIMEOUT_S = 600


class PostgresHintCache:
    """Repo-backed hint cache, so quota protection survives restarts.

    The in-memory cache in youtube.py is per-process; a worker restart would
    otherwise re-spend 100 units per hint. This bridges sync adapter calls to the
    async repo via the running loop.
    """

    def __init__(self, repo: Repo, loop: asyncio.AbstractEventLoop):
        self._repo = repo
        self._loop = loop

    def get(self, hint: str):
        fut = asyncio.run_coroutine_threadsafe(self._repo.get_hint(hint), self._loop)
        ids = fut.result(timeout=10)
        if ids is None:
            return None
        from datetime import datetime, timezone

        # Repo already applied the TTL, so anything returned is fresh.
        return ids, datetime.now(timezone.utc)

    def put(self, hint: str, video_ids) -> None:
        asyncio.run_coroutine_threadsafe(
            self._repo.put_hint(hint, video_ids), self._loop
        ).result(timeout=10)


async def build_page_job(ctx: dict, query: str, mode: str | None = None) -> dict:
    """Build one page and persist it."""
    repo: Repo = ctx["repo"]
    bus: RedisProgressBus = ctx["bus"]
    slug = normalize_query(query)
    loop = asyncio.get_running_loop()

    async def publish(stage: str, message: str, fraction: float, payload: dict) -> None:
        await bus.publish(
            slug,
            ProgressEvent(
                stage=stage,
                message=message,
                progress=overall_progress(stage, fraction),
                payload=payload,
            ),
        )

    def progress(stage: str, message: str, fraction: float, payload: dict) -> None:
        # build_page is sync; hop back onto the loop to publish.
        asyncio.run_coroutine_threadsafe(publish(stage, message, fraction, payload), loop)

    deps = BuildDeps(
        youtube=YouTubeSource(hint_cache=PostgresHintCache(repo, loop)),
        llm=build_client(),
        embedder=build_embedder(),
        repo=repo,
    )

    try:
        result = await asyncio.to_thread(
            functools.partial(build_page, query, deps, mode_hint=mode, progress=progress)
        )
    except (BuildFailed, Exception) as exc:  # noqa: BLE001
        log.exception("build failed for %r", query)
        await repo.save_page(slug, mode or "learn", None, None, "failed")
        await bus.publish(
            slug, ProgressEvent(stage="failed", message=str(exc)[:300])
        )
        raise

    await repo.save_page(
        slug, result.mode, result.outline, result.page, "ready", result.cost_usd
    )
    await bus.publish(
        slug,
        ProgressEvent(
            stage="done",
            message="page ready",
            progress=1.0,
            payload={
                "slug": result.slug,
                "mode": result.mode,
                "cost_usd": round(result.cost_usd, 4),
                "quota_spent": result.quota_spent,
                "warnings": result.warnings,
            },
        ),
    )
    log.info(
        "built %r: mode=%s cost=$%.3f quota=%d warnings=%d",
        query, result.mode, result.cost_usd, result.quota_spent, len(result.warnings),
    )
    return {"slug": result.slug, "mode": result.mode, "cost_usd": result.cost_usd}


async def import_seed_job(ctx: dict, url: str) -> dict:
    """Reel-import (A4.3). Analyse a pasted link, then build a path from it."""
    from services.worker.pipeline.reel_import import import_seed

    repo: Repo = ctx["repo"]
    deps = BuildDeps(
        youtube=YouTubeSource(),
        llm=build_client(),
        embedder=build_embedder(),
        repo=repo,
    )
    analysis, result = await asyncio.to_thread(functools.partial(import_seed, url, deps))
    path_id = await repo.save_learning_path(url, analysis, result.page)
    return {"path_id": path_id, "mode": result.mode}


async def startup(ctx: dict) -> None:
    ctx["repo"] = await Repo.connect()
    from redis.asyncio import Redis

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    ctx["redis"] = redis
    ctx["bus"] = RedisProgressBus(redis)
    log.info("worker ready")


async def shutdown(ctx: dict) -> None:
    if ctx.get("repo"):
        await ctx["repo"].close()
    if ctx.get("redis"):
        await ctx["redis"].aclose()


def _redis_settings():
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379"))


# arq resolves jobs by function __name__, and the API enqueues "build_page" /
# "import_seed". Renaming here keeps the job names stable regardless of what the
# Python functions are called.
build_page_job.__name__ = "build_page"
import_seed_job.__name__ = "import_seed"


class WorkerSettings:
    functions = [build_page_job, import_seed_job]
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = JOB_TIMEOUT_S
    max_tries = 2
    keep_result = 3600
    redis_settings = _redis_settings()

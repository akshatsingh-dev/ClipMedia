"""Database access layer (asyncpg + pgvector).

One module owns all SQL. Everything above it works in dataclasses/dicts, so the
pipeline never builds a query string and swapping storage stays contained.

Vectors are passed as pgvector's text literal form ('[0.1,0.2,...]') and cast in
SQL, which avoids a hard dependency on a pgvector Python codec.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

log = logging.getLogger(__name__)

HINT_CACHE_TTL_DAYS = 30
DEFAULT_DSN = "postgresql://deepclip:deepclip@localhost:5432/deepclip"


def dsn() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DSN


def to_pgvector(vec: Sequence[float] | None) -> str | None:
    """pgvector text literal. None stays None so the column can be NULL."""
    if vec is None:
        return None
    return "[" + ",".join(f"{float(v):.6g}" for v in vec) + "]"


def from_pgvector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    text = str(value).strip()
    if not text.startswith("["):
        return None
    inner = text.strip("[]")
    return [float(p) for p in inner.split(",") if p.strip()] if inner else []


@dataclass
class VideoRow:
    id: str
    source: str
    title: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    duration_s: int | None = None
    published_at: datetime | None = None
    view_count: int | None = None
    like_count: int | None = None
    transcript_kind: str | None = None
    lang: str | None = None
    # None, not 0.5: the upsert COALESCEs this so a cheap metadata refresh does
    # not overwrite an expensive LLM-computed score. A concrete 0.5 default here
    # would defeat that and silently reset credibility on every refresh.
    credibility: float | None = None


@dataclass
class SegmentRow:
    video_id: str
    t_start: float
    t_end: float
    text: str
    embedding: list[float] | None = None
    quality: float | None = None
    intensity: float | None = None
    vis_tags: dict | None = None
    id: int | None = None


# The closed set of event kinds. Kept here (not free-form) so a typo in the
# client becomes a rejected event rather than a silent hole in the metric.
EVENT_KINDS = frozenset(
    {
        "page_view",       # a page/feed opened
        "clip_view",       # a clip scrolled into view / mounted
        "clip_complete",   # a clip reached its t_end; value = fraction watched
        "page_complete",   # a Learn page reached its end section
        "end_card",        # a feed reached its end-card (the anti-infinite signal)
        "satisfaction",    # one-tap "got what I came for"; value = rating
        "import",          # a reel-import was started
        "report",          # a clip was reported
    }
)


@dataclass
class EventRow:
    anon_id: str
    session_id: str
    kind: str
    slug: str | None = None
    mode: str | None = None
    video_id: str | None = None
    position: int | None = None
    value: float | None = None
    meta: dict | None = None

    def valid(self) -> bool:
        return bool(self.anon_id and self.session_id and self.kind in EVENT_KINDS)


class Repo:
    """Async repository over an asyncpg pool."""

    def __init__(self, pool):
        self.pool = pool

    @classmethod
    async def connect(cls, url: str | None = None, min_size: int = 2, max_size: int = 10):
        import asyncpg

        pool = await asyncpg.create_pool(
            url or dsn(), min_size=min_size, max_size=max_size
        )
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def init_schema(self, schema_path: str | None = None) -> None:
        """Apply schema.sql. Idempotent — every statement is IF NOT EXISTS."""
        path = schema_path or os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(path, "r", encoding="utf-8") as fh:
            sql = fh.read()
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    # -- videos ---------------------------------------------------------

    async def upsert_video(self, v: VideoRow) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO videos (id, source, title, channel_id, channel_name,
                                    duration_s, published_at, view_count, like_count,
                                    transcript_kind, lang, credibility)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (id) DO UPDATE SET
                  source          = EXCLUDED.source,
                  title           = EXCLUDED.title,
                  channel_id      = EXCLUDED.channel_id,
                  channel_name    = EXCLUDED.channel_name,
                  duration_s      = EXCLUDED.duration_s,
                  published_at    = EXCLUDED.published_at,
                  view_count      = EXCLUDED.view_count,
                  like_count      = EXCLUDED.like_count,
                  -- transcript_kind and credibility are expensive to recompute,
                  -- so a cheap metadata refresh must not clear them.
                  transcript_kind = COALESCE(EXCLUDED.transcript_kind, videos.transcript_kind),
                  lang            = COALESCE(EXCLUDED.lang, videos.lang),
                  credibility     = COALESCE(EXCLUDED.credibility, videos.credibility)
                """,
                v.id, v.source, v.title, v.channel_id, v.channel_name,
                v.duration_s, v.published_at, v.view_count, v.like_count,
                v.transcript_kind, v.lang, v.credibility,
            )

    async def get_video(self, video_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM videos WHERE id = $1", video_id)
        return dict(row) if row else None

    async def existing_video_ids(self, video_ids: Sequence[str]) -> set[str]:
        """Which ids we already have — skips re-fetching metadata and quota."""
        if not video_ids:
            return set()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM videos WHERE id = ANY($1::text[])", list(video_ids)
            )
        return {r["id"] for r in rows}

    async def set_channel_credibility(self, channel_id: str, score: float) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE videos SET credibility = $2 WHERE channel_id = $1",
                channel_id, score,
            )

    async def channel_credibility(self, channel_id: str) -> float | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT credibility FROM videos WHERE channel_id = $1 LIMIT 1",
                channel_id,
            )
        return float(row["credibility"]) if row else None

    # -- segments -------------------------------------------------------

    async def insert_segments(self, segments: Sequence[SegmentRow]) -> list[int]:
        """Bulk insert. Returns new ids in input order."""
        if not segments:
            return []
        ids: list[int] = []
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for s in segments:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO segments
                          (video_id, t_start, t_end, text, embedding, quality,
                           intensity, vis_tags)
                        VALUES ($1,$2,$3,$4,$5::vector,$6,$7,$8::jsonb)
                        RETURNING id
                        """,
                        s.video_id, s.t_start, s.t_end, s.text,
                        to_pgvector(s.embedding), s.quality, s.intensity,
                        json.dumps(s.vis_tags) if s.vis_tags is not None else None,
                    )
                    ids.append(row["id"])
        return ids

    async def delete_segments_for_video(self, video_id: str) -> int:
        """Used before re-segmenting so a re-ingest cannot duplicate segments."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM segments WHERE video_id = $1", video_id
            )
        return int(result.split()[-1]) if result else 0

    async def has_segments(self, video_id: str) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM segments WHERE video_id = $1 LIMIT 1", video_id
            )
        return row is not None

    async def search_segments(
        self,
        embedding: Sequence[float],
        limit: int = 50,
        video_ids: Sequence[str] | None = None,
        min_quality: float | None = None,
        source: str | None = None,
    ) -> list[dict]:
        """Vector top-k with metadata joined, cosine distance -> similarity.

        Restricting to `video_ids` matters: retrieval for a chapter should search
        that chapter's candidates, not the entire global index, or every chapter
        converges on the same handful of popular videos.
        """
        clauses = ["s.embedding IS NOT NULL"]
        params: list[Any] = [to_pgvector(list(embedding))]

        if video_ids:
            params.append(list(video_ids))
            clauses.append(f"s.video_id = ANY(${len(params)}::text[])")
        if min_quality is not None:
            params.append(min_quality)
            clauses.append(f"s.quality >= ${len(params)}")
        if source:
            params.append(source)
            clauses.append(f"v.source = ${len(params)}")

        params.append(limit)
        sql = f"""
            SELECT s.id, s.video_id, s.t_start, s.t_end, s.text, s.quality,
                   s.intensity, s.embedding,
                   v.title, v.channel_id, v.channel_name, v.duration_s,
                   v.published_at, v.view_count, v.source, v.credibility,
                   v.transcript_kind,
                   1 - (s.embedding <=> $1::vector) AS cosine
            FROM segments s
            JOIN videos v ON v.id = s.video_id
            WHERE {' AND '.join(clauses)}
            ORDER BY s.embedding <=> $1::vector
            LIMIT ${len(params)}
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        out = []
        for r in rows:
            d = dict(r)
            d["embedding"] = from_pgvector(d.get("embedding"))
            out.append(d)
        return out

    # -- hint cache (quota protection) -----------------------------------

    async def get_hint(self, hint: str, ttl_days: int = HINT_CACHE_TTL_DAYS):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT video_ids, fetched_at FROM hint_cache WHERE hint = $1", hint
            )
        if not row:
            return None
        fetched = row["fetched_at"]
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > timedelta(days=ttl_days):
            return None
        return list(row["video_ids"] or [])

    async def put_hint(self, hint: str, video_ids: Sequence[str]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO hint_cache (hint, video_ids, fetched_at)
                VALUES ($1, $2, now())
                ON CONFLICT (hint) DO UPDATE
                  SET video_ids = EXCLUDED.video_ids, fetched_at = now()
                """,
                hint, list(video_ids),
            )

    # -- pages ----------------------------------------------------------

    async def get_page(self, query_norm: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM deep_pages WHERE query_norm = $1", query_norm
            )
        if not row:
            return None
        d = dict(row)
        for key in ("outline", "page"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key])
        return d

    async def claim_page_build(self, query_norm: str, mode: str) -> bool:
        """Atomically mark a page as building.

        Returns True if this caller owns the build. Two users requesting the same
        uncached query simultaneously must not both pay ~$1 to build it, so the
        insert doubles as a lock.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO deep_pages (query_norm, mode, status)
                VALUES ($1, $2, 'building')
                ON CONFLICT (query_norm) DO UPDATE
                  SET status = 'building', mode = EXCLUDED.mode
                  WHERE deep_pages.status = 'failed'
                RETURNING id
                """,
                query_norm, mode,
            )
        return row is not None

    async def save_page(
        self,
        query_norm: str,
        mode: str,
        outline: dict | None,
        page: dict | None,
        status: str,
        cost_usd: float | None = None,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO deep_pages
                  (query_norm, mode, outline, page, status, built_at, build_cost_usd)
                VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,now(),$6)
                ON CONFLICT (query_norm) DO UPDATE SET
                  mode = EXCLUDED.mode,
                  outline = EXCLUDED.outline,
                  page = EXCLUDED.page,
                  status = EXCLUDED.status,
                  built_at = now(),
                  build_cost_usd = EXCLUDED.build_cost_usd
                """,
                query_norm, mode,
                json.dumps(outline) if outline is not None else None,
                json.dumps(page) if page is not None else None,
                status, cost_usd,
            )

    async def list_pages(self, limit: int = 50, status: str = "ready") -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT query_norm, mode, page->>'title' AS title, built_at
                FROM deep_pages
                WHERE status = $1
                ORDER BY built_at DESC NULLS LAST
                LIMIT $2
                """,
                status, limit,
            )
        return [dict(r) for r in rows]

    # -- learning paths (reel import) ------------------------------------

    async def save_learning_path(
        self, seed_url: str, seed_analysis: dict, page: dict
    ) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO learning_paths (seed_url, seed_analysis, page)
                VALUES ($1, $2::jsonb, $3::jsonb)
                RETURNING id
                """,
                seed_url, json.dumps(seed_analysis), json.dumps(page),
            )
        return str(row["id"])

    async def get_learning_path(self, path_id: str) -> dict | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM learning_paths WHERE id = $1::uuid", path_id
            )
        if not row:
            return None
        d = dict(row)
        for key in ("seed_analysis", "page"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key])
        return d

    # -- analytics (D4/D8: the go/no-go metric) --------------------------

    async def insert_events(self, events: Sequence["EventRow"]) -> int:
        """Append events. Batched, since the client sends them in bursts.

        Returns the count written. Analytics is fire-and-forget from the caller's
        side — a failure here must never break page delivery, so the API wraps
        this, not the reverse.
        """
        if not events:
            return 0
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO events
                  (anon_id, session_id, kind, slug, mode, video_id, position,
                   value, meta)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                """,
                [
                    (
                        e.anon_id, e.session_id, e.kind, e.slug, e.mode,
                        e.video_id, e.position, e.value,
                        json.dumps(e.meta) if e.meta is not None else None,
                    )
                    for e in events
                ],
            )
        return len(events)

    async def page_completion_rate(self, slug: str) -> dict:
        """Completion = distinct sessions that reached the end / that started.

        The doc's north star (D4): a page that people finish. A 'page_view' opens
        a session on a page; a 'page_complete' or 'end_card' closes it having
        reached the bottom. Rate is over distinct sessions, not events, so a
        session cannot inflate its own completion by reloading.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH started AS (
                  SELECT DISTINCT session_id FROM events
                  WHERE slug = $1 AND kind = 'page_view'
                ),
                finished AS (
                  SELECT DISTINCT session_id FROM events
                  WHERE slug = $1 AND kind IN ('page_complete', 'end_card')
                )
                SELECT
                  (SELECT count(*) FROM started)  AS started,
                  (SELECT count(*) FROM finished) AS finished
                """,
                slug,
            )
        started = row["started"] or 0
        finished = row["finished"] or 0
        return {
            "slug": slug,
            "started": started,
            "finished": finished,
            "completion_rate": (finished / started) if started else 0.0,
        }

    async def return_rate(self, within_days: int = 7) -> dict:
        """Share of users who came back on a later day within the window.

        The second half of the go/no-go (D8): completion is necessary, return is
        what separates a company from a feature. A user 'returns' if they have
        events on two or more distinct calendar days.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                WITH per_user AS (
                  SELECT anon_id,
                         count(DISTINCT date_trunc('day', created_at)) AS active_days
                  FROM events
                  WHERE created_at > now() - ($1 || ' days')::interval
                  GROUP BY anon_id
                )
                SELECT
                  count(*)                                   AS users,
                  count(*) FILTER (WHERE active_days >= 2)    AS returned
                FROM per_user
                """,
                str(within_days),
            )
        users = row["users"] or 0
        returned = row["returned"] or 0
        return {
            "window_days": within_days,
            "users": users,
            "returned": returned,
            "return_rate": (returned / users) if users else 0.0,
        }

    async def clip_watch_depth(self, slug: str) -> list[dict]:
        """Mean fraction watched per clip position — where attention drops off.

        A page can be 'completed' by scrolling past clips without watching them;
        this is the sharper signal of whether the curation actually held.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT position,
                       avg(value)  AS mean_watched,
                       count(*)    AS views
                FROM events
                WHERE slug = $1 AND kind = 'clip_complete' AND position IS NOT NULL
                GROUP BY position
                ORDER BY position
                """,
                slug,
            )
        return [
            {
                "position": r["position"],
                "mean_watched": float(r["mean_watched"] or 0.0),
                "views": r["views"],
            }
            for r in rows
        ]

    async def satisfaction(self, slug: str) -> dict:
        """The one-tap 'got what I came for' signal (D4)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT count(*) AS responses, avg(value) AS mean_rating
                FROM events
                WHERE slug = $1 AND kind = 'satisfaction'
                """,
                slug,
            )
        return {
            "slug": slug,
            "responses": row["responses"] or 0,
            "mean_rating": float(row["mean_rating"]) if row["mean_rating"] is not None else None,
        }

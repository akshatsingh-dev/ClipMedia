"""Integration tests for the DB layer against a real Postgres + pgvector.

NOT RUN IN THIS ENVIRONMENT. Docker Hub is unreachable here (even a 13KB image
fails to pull), so every line of SQL in packages/db/repo.py is currently
unexecuted. These tests exist so that gap closes with one command the moment a
database is available:

    docker compose up -d postgres
    DEEPCLIP_DB=1 python3 -m pytest tests/test_db_integration.py -q

They cover the things unit tests structurally cannot: whether the SQL parses,
whether pgvector casts work, whether ON CONFLICT clauses behave as intended, and
whether the build-claim lock actually prevents duplicate builds.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from packages.db.repo import Repo, SegmentRow, VideoRow

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("DEEPCLIP_DB") != "1",
        reason="needs a live Postgres; set DEEPCLIP_DB=1",
    ),
    pytest.mark.asyncio,
]

DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://deepclip:deepclip@localhost:5432/deepclip"
)


@pytest.fixture
async def repo():
    r = await Repo.connect(DSN)
    await r.init_schema()
    async with r.pool.acquire() as conn:
        await conn.execute("TRUNCATE segments, videos, deep_pages, learning_paths, hint_cache CASCADE")
    yield r
    await r.close()


def vec(seed: float = 0.1, dim: int = 1024) -> list[float]:
    return [seed] * dim


async def test_schema_applies_cleanly(repo):
    async with repo.pool.acquire() as conn:
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    names = {t["tablename"] for t in tables}
    assert {"videos", "segments", "deep_pages", "learning_paths", "hint_cache"} <= names


async def test_hnsw_index_exists(repo):
    """The vector index is the whole reason for pgvector; verify it was created."""
    async with repo.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'segments'"
        )
    assert any("hnsw" in r["indexdef"].lower() for r in rows)


async def test_video_upsert_and_fetch(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube", title="T", channel_id="UC1"))
    row = await repo.get_video("v1")
    assert row["title"] == "T"


async def test_upsert_preserves_expensive_fields(repo):
    """A cheap metadata refresh must not clear transcript_kind or credibility."""
    await repo.upsert_video(
        VideoRow(id="v1", source="youtube", title="T", transcript_kind="manual", credibility=0.95)
    )
    await repo.upsert_video(VideoRow(id="v1", source="youtube", title="T updated"))
    row = await repo.get_video("v1")
    assert row["title"] == "T updated"
    assert row["transcript_kind"] == "manual", "transcript_kind was cleared"
    assert row["credibility"] == pytest.approx(0.95), "credibility was cleared"


async def test_existing_video_ids(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    assert await repo.existing_video_ids(["v1", "v2"]) == {"v1"}
    assert await repo.existing_video_ids([]) == set()


async def test_insert_segments_and_vector_roundtrip(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    ids = await repo.insert_segments(
        [SegmentRow(video_id="v1", t_start=0, t_end=60, text="hello", embedding=vec(0.1))]
    )
    assert len(ids) == 1
    results = await repo.search_segments(vec(0.1), limit=5)
    assert results[0]["text"] == "hello"
    assert len(results[0]["embedding"]) == 1024


async def test_search_orders_by_similarity(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    near = vec(0.1)
    far = [(-0.1)] * 1024
    await repo.insert_segments([
        SegmentRow(video_id="v1", t_start=0, t_end=60, text="near", embedding=near),
        SegmentRow(video_id="v1", t_start=60, t_end=120, text="far", embedding=far),
    ])
    results = await repo.search_segments(near, limit=2)
    assert results[0]["text"] == "near"
    assert results[0]["cosine"] > results[1]["cosine"]


async def test_search_filters_by_video_ids(repo):
    """Chapter retrieval must search its own candidates, not the global index."""
    for vid in ("v1", "v2"):
        await repo.upsert_video(VideoRow(id=vid, source="youtube"))
        await repo.insert_segments(
            [SegmentRow(video_id=vid, t_start=0, t_end=60, text=vid, embedding=vec(0.1))]
        )
    results = await repo.search_segments(vec(0.1), video_ids=["v1"])
    assert {r["video_id"] for r in results} == {"v1"}


async def test_search_filters_by_min_quality(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    await repo.insert_segments([
        SegmentRow(video_id="v1", t_start=0, t_end=60, text="good", embedding=vec(0.1), quality=0.9),
        SegmentRow(video_id="v1", t_start=60, t_end=120, text="bad", embedding=vec(0.1), quality=0.1),
    ])
    results = await repo.search_segments(vec(0.1), min_quality=0.5)
    assert {r["text"] for r in results} == {"good"}


async def test_null_embeddings_excluded_from_search(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    await repo.insert_segments(
        [SegmentRow(video_id="v1", t_start=0, t_end=60, text="no vector")]
    )
    assert await repo.search_segments(vec(0.1)) == []


async def test_delete_segments_for_video(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    await repo.insert_segments(
        [SegmentRow(video_id="v1", t_start=0, t_end=60, text="x", embedding=vec())]
    )
    assert await repo.has_segments("v1") is True
    assert await repo.delete_segments_for_video("v1") == 1
    assert await repo.has_segments("v1") is False


async def test_segments_cascade_on_video_delete(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube"))
    await repo.insert_segments(
        [SegmentRow(video_id="v1", t_start=0, t_end=60, text="x", embedding=vec())]
    )
    async with repo.pool.acquire() as conn:
        await conn.execute("DELETE FROM videos WHERE id = 'v1'")
    assert await repo.has_segments("v1") is False


async def test_hint_cache_roundtrip_and_ttl(repo):
    await repo.put_hint("gandhi", ["a", "b"])
    assert await repo.get_hint("gandhi") == ["a", "b"]
    # Age it past the TTL.
    async with repo.pool.acquire() as conn:
        await conn.execute(
            "UPDATE hint_cache SET fetched_at = $1 WHERE hint = 'gandhi'",
            datetime.now(timezone.utc) - timedelta(days=31),
        )
    assert await repo.get_hint("gandhi") is None


async def test_hint_cache_upsert_refreshes(repo):
    await repo.put_hint("h", ["a"])
    await repo.put_hint("h", ["b", "c"])
    assert await repo.get_hint("h") == ["b", "c"]


async def test_save_and_get_page(repo):
    await repo.save_page("gandhi", "learn", {"o": 1}, {"title": "G"}, "ready", 0.85)
    page = await repo.get_page("gandhi")
    assert page["page"]["title"] == "G"
    assert page["outline"]["o"] == 1
    assert page["build_cost_usd"] == pytest.approx(0.85)


async def test_claim_page_build_prevents_duplicate(repo):
    """The lock that stops two users each paying to build the same page."""
    assert await repo.claim_page_build("gandhi", "learn") is True
    assert await repo.claim_page_build("gandhi", "learn") is False


async def test_failed_page_can_be_reclaimed(repo):
    await repo.save_page("gandhi", "learn", None, None, "failed")
    assert await repo.claim_page_build("gandhi", "learn") is True


async def test_ready_page_not_reclaimed(repo):
    await repo.save_page("gandhi", "learn", None, {"title": "G"}, "ready")
    assert await repo.claim_page_build("gandhi", "learn") is False


async def test_list_pages_only_ready(repo):
    await repo.save_page("a", "learn", None, {"title": "A"}, "ready")
    await repo.save_page("b", "learn", None, None, "building")
    assert [p["query_norm"] for p in await repo.list_pages()] == ["a"]


async def test_learning_path_roundtrip(repo):
    path_id = await repo.save_learning_path("https://x", {"topic": "t"}, {"title": "P"})
    path = await repo.get_learning_path(path_id)
    assert path["page"]["title"] == "P"
    assert path["seed_analysis"]["topic"] == "t"


async def test_channel_credibility_roundtrip(repo):
    await repo.upsert_video(VideoRow(id="v1", source="youtube", channel_id="UC1"))
    await repo.set_channel_credibility("UC1", 0.87)
    assert await repo.channel_credibility("UC1") == pytest.approx(0.87)

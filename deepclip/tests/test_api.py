import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from services.api.main import app
from services.api.progress import (
    ProgressBus,
    ProgressEvent,
    overall_progress,
)

# -- progress bus -------------------------------------------------------


def test_progress_event_roundtrip():
    e = ProgressEvent(stage="rank", message="ranking", progress=0.5, payload={"n": 3})
    back = ProgressEvent.from_dict(e.to_dict())
    assert back.stage == "rank"
    assert back.progress == 0.5
    assert back.payload == {"n": 3}


def test_progress_event_from_partial_dict():
    e = ProgressEvent.from_dict({"stage": "x"})
    assert e.stage == "x"
    assert e.payload == {}


@pytest.mark.asyncio
async def test_bus_delivers_to_subscribers():
    bus = ProgressBus()
    q1 = bus.subscribe("k")
    q2 = bus.subscribe("k")
    bus.publish("k", ProgressEvent(stage="outline"))
    assert (await q1.get()).stage == "outline"
    assert (await q2.get()).stage == "outline"


@pytest.mark.asyncio
async def test_bus_isolates_keys():
    bus = ProgressBus()
    q = bus.subscribe("a")
    bus.publish("b", ProgressEvent(stage="x"))
    assert q.empty()


def test_unsubscribe_cleans_up():
    bus = ProgressBus()
    q = bus.subscribe("k")
    assert bus.subscriber_count("k") == 1
    bus.unsubscribe("k", q)
    assert bus.subscriber_count("k") == 0


def test_unsubscribe_unknown_is_safe():
    bus = ProgressBus()
    bus.unsubscribe("nope", asyncio.Queue())


def test_publish_with_no_subscribers_is_safe():
    ProgressBus().publish("k", ProgressEvent(stage="x"))


@pytest.mark.asyncio
async def test_full_queue_drops_rather_than_blocking():
    """A stalled SSE client must not be able to stall the build."""
    bus = ProgressBus()
    q = bus.subscribe("k")
    for i in range(200):  # exceeds QUEUE_MAXSIZE
        bus.publish("k", ProgressEvent(stage=f"s{i}"))
    assert q.qsize() <= 100


# -- weighted progress --------------------------------------------------


def test_overall_progress_monotonic_across_stages():
    stages = ["outline", "retrieve", "transcripts", "segment", "score", "rank", "assemble"]
    values = [overall_progress(s, 1.0) for s in stages]
    assert values == sorted(values)
    assert values[-1] == pytest.approx(1.0)


def test_overall_progress_partial_within_stage():
    assert overall_progress("outline", 0.0) == 0.0
    assert 0.0 < overall_progress("outline", 0.5) < overall_progress("outline", 1.0)


def test_overall_progress_unknown_stage():
    assert overall_progress("nonsense") == 0.0


def test_overall_progress_clamps_fraction():
    assert overall_progress("assemble", 5.0) == pytest.approx(1.0)
    assert overall_progress("outline", -1.0) >= 0.0


# -- API routes ---------------------------------------------------------


class FakeRepo:
    def __init__(self, pages=None, paths=None):
        self._pages = pages or {}
        self._paths = paths or {}
        self.claimed = []

    async def get_page(self, query_norm):
        return self._pages.get(query_norm)

    async def list_pages(self, limit=50, status="ready"):
        return [
            {
                "query_norm": k,
                "mode": v["mode"],
                "title": (v.get("page") or {}).get("title"),
                "built_at": v.get("built_at"),
            }
            for k, v in self._pages.items()
            if v.get("status") == status
        ][:limit]

    async def claim_page_build(self, query_norm, mode):
        self.claimed.append((query_norm, mode))
        return True

    async def get_learning_path(self, path_id):
        return self._paths.get(path_id)

    async def close(self):
        pass


class FakeJob:
    job_id = "job-123"


class FakeQueue:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, *args):
        self.enqueued.append((name, args))
        return FakeJob()

    async def close(self):
        pass


READY_PAGE = {
    "query_norm": "gandhi",
    "mode": "learn",
    "status": "ready",
    "page": {"title": "Mahatma Gandhi", "chapters": []},
    "built_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_healthz_reports_dependencies(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "database" in body and "queue" in body


def test_page_404_when_missing(client):
    client.app.state.repo = FakeRepo()
    assert client.get("/api/pages/unknown").status_code == 404


def test_page_returns_cached(client):
    client.app.state.repo = FakeRepo({"gandhi": READY_PAGE})
    body = client.get("/api/pages/Gandhi").json()
    assert body["page"]["title"] == "Mahatma Gandhi"


def test_page_slug_is_normalised(client):
    """'Gandhi's Salt March' and 'gandhis salt march' must hit the same row."""
    page = dict(READY_PAGE, query_norm="gandhis salt march")
    client.app.state.repo = FakeRepo({"gandhis salt march": page})
    assert client.get("/api/pages/Gandhi's Salt March").status_code == 200


def test_building_page_is_not_served_as_ready(client):
    client.app.state.repo = FakeRepo({"x": dict(READY_PAGE, query_norm="x", status="building")})
    assert client.get("/api/pages/x").status_code == 404


def test_503_without_database(client):
    client.app.state.repo = None
    assert client.get("/api/pages/anything").status_code == 503


def test_feed_rejects_learn_page(client):
    client.app.state.repo = FakeRepo({"gandhi": READY_PAGE})
    assert client.get("/api/feed/gandhi").status_code == 404


def test_feed_serves_entertain_page(client):
    feed = dict(READY_PAGE, query_norm="speed", mode="entertain")
    client.app.state.repo = FakeRepo({"speed": feed})
    assert client.get("/api/feed/speed").json()["mode"] == "entertain"


def test_list_pages(client):
    client.app.state.repo = FakeRepo({"gandhi": READY_PAGE})
    pages = client.get("/api/pages").json()["pages"]
    assert pages[0]["slug"] == "gandhi"


def test_build_returns_cached_without_enqueueing(client):
    """A cache hit must not cost a build."""
    repo = FakeRepo({"gandhi": READY_PAGE})
    queue = FakeQueue()
    client.app.state.repo, client.app.state.queue = repo, queue
    body = client.post("/api/build", json={"query": "Gandhi"}).json()
    assert body["cached"] is True
    assert queue.enqueued == []


def test_build_enqueues_on_miss(client):
    repo, queue = FakeRepo(), FakeQueue()
    client.app.state.repo, client.app.state.queue = repo, queue
    body = client.post("/api/build", json={"query": "MLK"}).json()
    assert body["cached"] is False
    assert body["job_id"] == "job-123"
    assert queue.enqueued[0][0] == "build_page"
    assert repo.claimed == [("mlk", "learn")]


def test_concurrent_build_joins_instead_of_duplicating(client):
    """Two users on the same uncached query must not both pay to build it."""
    building = dict(READY_PAGE, query_norm="mlk", status="building")
    repo, queue = FakeRepo({"mlk": building}), FakeQueue()
    client.app.state.repo, client.app.state.queue = repo, queue
    body = client.post("/api/build", json={"query": "MLK"}).json()
    assert body["joined"] is True
    assert queue.enqueued == [], "must not enqueue a duplicate build"


def test_build_validates_mode(client):
    client.app.state.repo, client.app.state.queue = FakeRepo(), FakeQueue()
    assert client.post("/api/build", json={"query": "x", "mode": "bogus"}).status_code == 422


def test_build_rejects_empty_query(client):
    client.app.state.repo, client.app.state.queue = FakeRepo(), FakeQueue()
    assert client.post("/api/build", json={"query": ""}).status_code == 422


def test_build_503_without_queue(client):
    client.app.state.repo, client.app.state.queue = FakeRepo(), None
    assert client.post("/api/build", json={"query": "x"}).status_code == 503


def test_import_enqueues(client):
    queue = FakeQueue()
    client.app.state.repo, client.app.state.queue = FakeRepo(), queue
    body = client.post("/api/import", json={"url": "https://youtube.com/shorts/abc"}).json()
    assert body["job_id"] == "job-123"
    assert queue.enqueued[0][0] == "import_seed"


def test_get_path(client):
    client.app.state.repo = FakeRepo(
        paths={"p1": {"id": "p1", "seed_url": "u", "seed_analysis": {}, "page": {"title": "T"}}}
    )
    assert client.get("/api/paths/p1").json()["page"]["title"] == "T"


def test_get_path_404(client):
    client.app.state.repo = FakeRepo()
    assert client.get("/api/paths/nope").status_code == 404


# -- SSE ----------------------------------------------------------------


def test_sse_stream_opens_with_connected_frame(client):
    """SSE headers and the initial frame.

    Event *delivery* is covered by the ProgressBus unit tests above rather than
    here: TestClient runs the app in a separate event loop, and publishing to an
    asyncio.Queue across threads does not wake the waiting coroutine. That is a
    property of the test harness, not of the bus — in production the worker
    publishes over Redis (RedisProgressBus), a different process entirely.
    """
    client.app.state.repo = FakeRepo()
    with client.stream("GET", "/api/build/gandhi/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        # nginx buffers event streams unless told not to.
        assert resp.headers["x-accel-buffering"] == "no"

        frame = _read_event(resp.iter_lines())
        assert "event: connected" in frame
        assert "listening" in frame


def _read_event(lines) -> str:
    """Collect lines until a blank line ends the SSE frame."""
    out = []
    for line in lines:
        if line == "":
            if out:
                break
            continue
        out.append(line)
    return "\n".join(out)


def test_sse_unsubscribes_on_disconnect(client):
    bus = client.app.state.bus
    client.app.state.repo = FakeRepo()
    with client.stream("GET", "/api/build/x/stream") as resp:
        _read_event(resp.iter_lines())
    # The generator's finally block must release the subscriber.
    assert bus.subscriber_count("x") == 0


# -- analytics endpoints ------------------------------------------------


class EventFakeRepo(FakeRepo):
    def __init__(self, *a, fail_insert=False, **kw):
        super().__init__(*a, **kw)
        self.inserted = []
        self._fail_insert = fail_insert
        self._metrics = {}

    async def insert_events(self, events):
        if self._fail_insert:
            raise RuntimeError("db down")
        self.inserted.extend(events)
        return len(events)

    async def page_completion_rate(self, slug):
        return {"slug": slug, "started": 4, "finished": 3, "completion_rate": 0.75}

    async def clip_watch_depth(self, slug):
        return [{"position": 0, "mean_watched": 0.9, "views": 10}]

    async def satisfaction(self, slug):
        return {"slug": slug, "responses": 5, "mean_rating": 0.8}

    async def return_rate(self, within_days=7):
        return {"window_days": within_days, "users": 100, "returned": 28, "return_rate": 0.28}

    async def recent_reports(self, limit=100):
        return [{"slug": "g", "video_id": "A", "position": 0, "reports": 3, "last_reported": None, "reasons": ["wrong"]}]


def ev(**kw):
    base = {"anon_id": "a", "session_id": "s", "kind": "page_view"}
    base.update(kw)
    return base


def test_events_accepted(client):
    repo = EventFakeRepo()
    client.app.state.repo = repo
    r = client.post("/api/events", json={"events": [ev(), ev(kind="clip_view", position=0)]})
    assert r.status_code == 202
    assert r.json()["accepted"] == 2
    assert len(repo.inserted) == 2


def test_events_drops_invalid_kind_but_keeps_valid(client):
    """A typo'd kind is dropped, not 4xx'd — a beacon cannot read a response."""
    repo = EventFakeRepo()
    client.app.state.repo = repo
    r = client.post("/api/events", json={"events": [ev(), ev(kind="not_a_real_kind")]})
    assert r.status_code == 202
    assert r.json()["accepted"] == 1


def test_events_survive_db_failure(client):
    """Analytics must never surface an error to the user."""
    client.app.state.repo = EventFakeRepo(fail_insert=True)
    r = client.post("/api/events", json={"events": [ev()]})
    assert r.status_code == 202
    assert r.json()["accepted"] == 0


def test_events_accepted_without_database(client):
    """No DB: accept and discard rather than erroring."""
    client.app.state.repo = None
    r = client.post("/api/events", json={"events": [ev()]})
    assert r.status_code == 202
    assert r.json()["accepted"] == 0


def test_events_rejects_empty_batch(client):
    client.app.state.repo = EventFakeRepo()
    assert client.post("/api/events", json={"events": []}).status_code == 422


def test_events_rejects_oversized_batch(client):
    client.app.state.repo = EventFakeRepo()
    big = {"events": [ev() for _ in range(101)]}
    assert client.post("/api/events", json=big).status_code == 422


def test_metrics_for_page(client):
    client.app.state.repo = EventFakeRepo()
    body = client.get("/api/metrics/Gandhi").json()
    assert body["completion"]["completion_rate"] == 0.75
    assert body["satisfaction"]["mean_rating"] == 0.8
    assert body["clip_watch_depth"][0]["mean_watched"] == 0.9


def test_global_return_rate(client):
    client.app.state.repo = EventFakeRepo()
    body = client.get("/api/metrics").json()
    assert body["return_rate"] == 0.28


def test_metrics_503_without_db(client):
    client.app.state.repo = None
    assert client.get("/api/metrics/x").status_code == 503


# -- rate limiting ------------------------------------------------------


def test_build_is_rate_limited(client):
    """The 6th uncached build in the window is rejected, not enqueued."""
    from services.api.ratelimit import InMemoryRateLimiter
    repo, queue = FakeRepo(), FakeQueue()
    client.app.state.repo, client.app.state.queue = repo, queue
    client.app.state.limiter = InMemoryRateLimiter()
    client.app.state.redis_limiter = None

    codes = [client.post("/api/build", json={"query": f"q{i}"}).status_code for i in range(6)]
    assert codes[:5] == [200, 200, 200, 200, 200]
    assert codes[5] == 429
    assert len(queue.enqueued) == 5, "the rejected build must not enqueue"


def test_cached_build_not_rate_limited(client):
    """A cache hit is free, so it must not consume the build budget."""
    from services.api.ratelimit import InMemoryRateLimiter
    repo = FakeRepo({"gandhi": READY_PAGE})
    client.app.state.repo, client.app.state.queue = repo, FakeQueue()
    client.app.state.limiter = InMemoryRateLimiter()
    client.app.state.redis_limiter = None
    codes = [client.post("/api/build", json={"query": "Gandhi"}).status_code for _ in range(10)]
    assert all(c == 200 for c in codes)


def test_import_is_rate_limited(client):
    from services.api.ratelimit import InMemoryRateLimiter
    client.app.state.repo, client.app.state.queue = FakeRepo(), FakeQueue()
    client.app.state.limiter = InMemoryRateLimiter()
    client.app.state.redis_limiter = None
    codes = [
        client.post("/api/import", json={"url": f"https://youtu.be/aircAruvnKk{i}"}).status_code
        for i in range(6)
    ]
    assert codes[5] == 429


def test_reports_endpoint(client):
    client.app.state.repo = EventFakeRepo()
    body = client.get("/api/reports").json()
    assert body["reports"][0]["video_id"] == "A"
    assert body["reports"][0]["reports"] == 3


def test_reports_503_without_db(client):
    client.app.state.repo = None
    assert client.get("/api/reports").status_code == 503


# -- tutor --------------------------------------------------------------


class TutorFakeRepo(FakeRepo):
    def __init__(self, page=None):
        super().__init__()
        self._page = page

    async def get_page(self, slug):
        return self._page


TUTOR_PAGE = {
    "query_norm": "g", "mode": "learn", "status": "ready",
    "page": {"chapters": [{"title": "C", "clips": [
        {"video_id": "v1", "t_start": 100, "transcript": "the march covered 240 miles"}
    ]}]},
}


def test_tutor_answers(client):
    from services.worker.llm.client import FakeLLMClient
    client.app.state.repo = TutorFakeRepo(TUTOR_PAGE)
    client.app.state.llm = FakeLLMClient(responses=["240 miles."])
    r = client.post("/api/tutor", json={"slug": "g", "video_id": "v1", "t_start": 100, "question": "how far?"})
    assert r.status_code == 200
    assert "240" in r.json()["answer"]


def test_tutor_404_when_page_missing(client):
    client.app.state.repo = TutorFakeRepo(None)
    r = client.post("/api/tutor", json={"slug": "g", "video_id": "v1", "t_start": 100, "question": "q"})
    assert r.status_code == 404


def test_tutor_404_when_clip_not_on_page(client):
    from services.worker.llm.client import FakeLLMClient
    client.app.state.repo = TutorFakeRepo(TUTOR_PAGE)
    client.app.state.llm = FakeLLMClient(responses=["x"])
    r = client.post("/api/tutor", json={"slug": "g", "video_id": "OTHER", "t_start": 100, "question": "q"})
    assert r.status_code == 404


def test_tutor_validates_question(client):
    client.app.state.repo = TutorFakeRepo(TUTOR_PAGE)
    r = client.post("/api/tutor", json={"slug": "g", "video_id": "v1", "t_start": 100, "question": ""})
    assert r.status_code == 422

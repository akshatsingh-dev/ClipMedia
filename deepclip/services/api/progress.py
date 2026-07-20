"""Build progress pub/sub for the SSE stream.

Two transports:
  ProgressBus       in-process fan-out, used by the API for local subscribers.
  RedisProgressBus  cross-process, used when the worker runs separately from the
                    API — which is the deployed topology, since the worker is a
                    different container.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

CHANNEL_PREFIX = "deepclip:progress:"
QUEUE_MAXSIZE = 100


@dataclass
class ProgressEvent:
    """One step of a build.

    `stage` doubles as the SSE event name so the client can attach handlers per
    stage rather than parsing every payload.
    """

    stage: str
    message: str = ""
    progress: float | None = None  # 0-1
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "message": self.message,
            "progress": self.progress,
            "payload": self.payload,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProgressEvent":
        return cls(
            stage=str(data.get("stage", "")),
            message=str(data.get("message", "")),
            progress=data.get("progress"),
            payload=data.get("payload") or {},
            ts=float(data.get("ts") or time.time()),
        )


class ProgressBus:
    """In-process fan-out. One queue per subscriber."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, key: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subs.setdefault(key, []).append(q)
        return q

    def unsubscribe(self, key: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(key)
        if not subs:
            return
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subs.pop(key, None)

    def publish(self, key: str, event: ProgressEvent) -> None:
        """Never blocks. A slow subscriber drops events rather than stalling the
        build — progress is advisory, the page is the real output."""
        for q in list(self._subs.get(key, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.debug("progress queue full for %s; dropping event", key)

    def subscriber_count(self, key: str) -> int:
        return len(self._subs.get(key, []))


class RedisProgressBus:
    """Cross-process progress over Redis pub/sub."""

    def __init__(self, redis):
        self._redis = redis

    @staticmethod
    def channel(key: str) -> str:
        return f"{CHANNEL_PREFIX}{key}"

    async def publish(self, key: str, event: ProgressEvent) -> None:
        try:
            await self._redis.publish(self.channel(key), json.dumps(event.to_dict()))
        except Exception as exc:  # noqa: BLE001
            # A failed progress publish must never fail the build.
            log.warning("progress publish failed for %s: %s", key, exc)

    async def listen(self, key: str):
        """Async-iterate events for a key."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self.channel(key))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    yield ProgressEvent.from_dict(json.loads(data))
                except (json.JSONDecodeError, TypeError):
                    continue
        finally:
            await pubsub.unsubscribe(self.channel(key))
            await pubsub.close()


# Stage weights for the overall progress bar. Retrieval and transcripts dominate
# wall-clock, so a naive per-stage split would sit at "20%" for most of a build.
STAGE_WEIGHTS = {
    "outline": 0.10,
    "retrieve": 0.20,
    "transcripts": 0.30,
    "segment": 0.10,
    "score": 0.10,
    "rank": 0.10,
    "assemble": 0.10,
}
_STAGE_ORDER = list(STAGE_WEIGHTS)


def overall_progress(stage: str, stage_fraction: float = 1.0) -> float:
    """Weighted progress across the whole build, 0-1."""
    if stage not in STAGE_WEIGHTS:
        return 0.0
    done = sum(STAGE_WEIGHTS[s] for s in _STAGE_ORDER[: _STAGE_ORDER.index(stage)])
    return min(done + STAGE_WEIGHTS[stage] * max(0.0, min(1.0, stage_fraction)), 1.0)

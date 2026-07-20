"""Stage 8 — vision pass. POST-MVP, FEATURE-FLAGGED, OFF BY DEFAULT.

The spec marks this post-MVP and bounds it hard: final-round candidates only
(<=200 segments per page), storyboard frames rather than video, batched. It fills
`segments.vis_tags` and the `visual_richness` ranking term, which is weighted 0.10
and currently always 0.

Why it stays off: it is the only stage whose cost scales with clips rather than
with pages, so an unbounded version would quietly dominate the C8 budget. The
`DEEPCLIP_VISION` flag and the candidate cap are the guardrails.

Frames come from YouTube's public storyboard/thumbnail endpoints — still images
only. We never download video, which is the same constraint that governs the
whole architecture (B4).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from ..llm.client import MODEL_FAST, LLMClient, extract_json

log = logging.getLogger(__name__)

MAX_SEGMENTS_PER_PAGE = 200
BATCH_SIZE = 10

LEARN_TAGS = ("archival", "map", "reenactment", "talking_head", "diagram", "text_slide")
ENTERTAIN_TAGS = ("face_reaction", "action", "crowd", "gameplay", "irl")

SYSTEM = """You label video frames for a curation pipeline.

For each frame, give a 0.0-1.0 score per tag. Scores are independent, not a
distribution — a frame can be both archival and a talking head.

Judge only what is visible. Do not infer from context you were not given.
Output JSON only."""

PROMPT = """Tags: {tags}

Frames (one per clip, in order):
{frames}

Return JSON: {{"frames":[{{"id":<id>,"tags":{{"<tag>":0.0-1.0}}}}]}}"""


def vision_enabled() -> bool:
    """Off unless explicitly enabled. Post-MVP by spec."""
    return os.environ.get("DEEPCLIP_VISION", "").lower() in {"1", "true", "yes"}


def storyboard_url(video_id: str, t_start: float) -> str:
    """A representative still for a clip.

    YouTube exposes fixed thumbnails (hq1/hq2/hq3) at roughly 25/50/75% of the
    video. Without knowing duration we cannot pick by timestamp, so this picks a
    stable frame and lets the caller refine. Still images only, never video.
    """
    index = 1 + (int(t_start) // 300) % 3  # vary a little across long videos
    return f"https://i.ytimg.com/vi/{video_id}/hq{index}.jpg"


@dataclass
class VisionResult:
    segment_index: int
    tags: dict[str, float] = field(default_factory=dict)

    def richness(self, mode: str = "learn") -> float:
        """Collapse tags into the 0-1 `visual_richness` ranking term.

        Talking heads are the baseline of educational video, so they score low;
        archival footage and maps are what make a history page feel like a
        documentary rather than a lecture recording.
        """
        if not self.tags:
            return 0.0
        if mode == "learn":
            weights = {
                "archival": 1.0, "map": 0.8, "reenactment": 0.6,
                "diagram": 0.7, "text_slide": 0.2, "talking_head": 0.1,
            }
        else:
            weights = {
                "face_reaction": 1.0, "action": 0.9, "crowd": 0.6,
                "gameplay": 0.5, "irl": 0.5,
            }
        score = sum(self.tags.get(tag, 0.0) * w for tag, w in weights.items())
        return max(0.0, min(1.0, score / max(sum(weights.values()) * 0.4, 1e-6)))


def tag_segments(
    candidates,
    llm: LLMClient,
    mode: str = "learn",
    max_segments: int = MAX_SEGMENTS_PER_PAGE,
    batch_size: int = BATCH_SIZE,
) -> list[VisionResult]:
    """Tag final-round candidates. Returns one result per input, in order.

    Degrades to empty tags on any failure — `visual_richness` is 0.10 of the
    ranking score, so losing it should cost a little quality, never a page.
    """
    if not vision_enabled():
        log.debug("vision pass disabled (DEEPCLIP_VISION unset)")
        return [VisionResult(i) for i in range(len(candidates))]

    if len(candidates) > max_segments:
        # The cap is the cost guardrail, so truncate loudly rather than silently.
        log.warning(
            "vision pass capped at %d segments (%d requested)",
            max_segments, len(candidates),
        )
        candidates = list(candidates)[:max_segments]

    tags = LEARN_TAGS if mode == "learn" else ENTERTAIN_TAGS
    results = [VisionResult(i) for i in range(len(candidates))]

    for start in range(0, len(candidates), batch_size):
        batch = list(candidates)[start : start + batch_size]
        frames = "\n".join(
            f"[{i}] {storyboard_url(c.video_id, c.t_start)}"
            for i, c in enumerate(batch)
        )
        try:
            resp = llm.complete(
                PROMPT.format(tags=", ".join(tags), frames=frames),
                system=SYSTEM,
                model=MODEL_FAST,
                max_tokens=1536,
            )
            data = extract_json(resp.text)
        except Exception as exc:  # noqa: BLE001
            log.warning("vision batch at %d failed: %s", start, exc)
            continue

        rows = data.get("frames") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                idx = int(row["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= idx < len(batch):
                continue
            raw = row.get("tags")
            if not isinstance(raw, dict):
                continue
            results[start + idx].tags = {
                str(k): max(0.0, min(1.0, float(v)))
                for k, v in raw.items()
                if k in tags and isinstance(v, (int, float))
            }

    return results


def apply_vision(candidates, llm: LLMClient, mode: str = "learn") -> None:
    """Attach `visual_richness` and `vis_tags` to candidates in place."""
    for cand, result in zip(candidates, tag_segments(candidates, llm, mode=mode)):
        cand.visual_richness = result.richness(mode)
        cand.vis_tags = result.tags

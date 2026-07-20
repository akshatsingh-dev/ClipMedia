"""The orchestrator — stages 1 through 7, end to end.

This is where the pipeline actually becomes a page. Kept free of arq/Redis
specifics so it can be called directly (tests, CLI, pre-building scripts) and
wrapped thinly by the worker.

Design rules:
  - Every stage reports progress; the SSE stream is the product's perceived
    latency story (C5), not an afterthought.
  - Quota exhaustion is expected, not exceptional. A build that runs out of
    YouTube quota mid-way should ship the page it managed to assemble.
  - Nothing here raises for a single bad video. One unavailable transcript must
    not lose a page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..llm.client import LLMClient
from ..sources.youtube import QuotaExceeded, YouTubeSource
from .assemble import assemble_entertain, assemble_learn
from .credibility import (
    DEFAULT_CREDIBILITY,
    enforce_contested_selection,
    score_channel,
    seed_credibility,
)
from .embed import Embedder, embed_texts
from .moments import detect_moments
from .outline import Outline, build_outline
from .rank_entertain import build_feed
from .rank_learn import Candidate, rank_chapter
from .score import looks_like_junk, repair_names, score_segments
from .segment import Segment
from .vision import apply_vision, vision_enabled

log = logging.getLogger(__name__)

MAX_VIDEOS_PER_SECTION = 12
MAX_CANDIDATES_PER_SECTION = 60
TOP_K = 50
# Below this share of candidates having transcripts, the page is built on a
# thin slice of what was retrieved and the result should say so.
MIN_TRANSCRIPT_COVERAGE = 0.5

ProgressFn = Callable[[str, str, float, dict], None]


def _noop_progress(stage: str, message: str, fraction: float, payload: dict) -> None:
    pass


@dataclass
class BuildResult:
    slug: str
    mode: str
    page: dict
    outline: dict
    cost_usd: float = 0.0
    quota_spent: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class BuildDeps:
    """Everything the build needs from outside. Injected so tests can fake it."""

    youtube: YouTubeSource
    llm: LLMClient
    embedder: Embedder
    repo: Any | None = None  # packages.db.repo.Repo, optional for dry runs


def build_page(
    query: str,
    deps: BuildDeps,
    mode_hint: str | None = None,
    progress: ProgressFn = _noop_progress,
) -> BuildResult:
    """Run the full pipeline for one query."""
    warnings: list[str] = []

    # -- stage 1: outline ------------------------------------------------
    progress("outline", "planning the page", 0.0, {})
    outline = build_outline(query, deps.llm)
    if mode_hint and mode_hint != outline.mode:
        log.info("overriding classified mode %s with hint %s", outline.mode, mode_hint)
        outline.mode = mode_hint
    progress(
        "outline",
        f"planned {outline.title}",
        1.0,
        {"title": outline.title, "mode": outline.mode, "sections": _section_labels(outline)},
    )

    sections = _sections(outline)

    # -- stage 2/3: retrieval --------------------------------------------
    progress("retrieve", "searching YouTube", 0.0, {})
    section_videos: dict[str, list[str]] = {}
    quota_hit = False
    for i, (label, hints) in enumerate(sections.items()):
        if quota_hit:
            section_videos[label] = []
            continue
        ids: list[str] = []
        for hint in hints:
            try:
                # Shorts are first-class in Entertain; creators pre-clipped the
                # moment, which is exactly what we are looking for (stage 3).
                found = (
                    deps.youtube.search_with_shorts_variants(hint)
                    if outline.mode == "entertain"
                    else deps.youtube.search(hint)
                )
            except QuotaExceeded as exc:
                warnings.append(f"YouTube quota exhausted during retrieval: {exc}")
                log.warning("quota exhausted at section %r", label)
                quota_hit = True
                break
            for vid in found:
                if vid not in ids:
                    ids.append(vid)
        section_videos[label] = ids[:MAX_VIDEOS_PER_SECTION]
        progress(
            "retrieve",
            f"found candidates for {label}",
            (i + 1) / max(len(sections), 1),
            {"section": label, "videos": len(section_videos[label])},
        )

    all_ids = _dedupe(v for ids in section_videos.values() for v in ids)
    if not all_ids:
        raise BuildFailed("retrieval produced no candidate videos")

    try:
        metas = {m.id: m for m in deps.youtube.fetch_metadata(all_ids)}
    except QuotaExceeded as exc:
        warnings.append(f"quota exhausted before metadata: {exc}")
        metas = {}

    # -- stage 4: transcripts --------------------------------------------
    progress("transcripts", "fetching transcripts", 0.0, {})
    transcripts = {}
    names = outline.entity_names()
    for i, vid in enumerate(all_ids):
        try:
            t = deps.youtube.fetch_transcript(vid)
        except Exception as exc:  # noqa: BLE001 - one video must not lose a page
            log.info("transcript failed for %s: %s", vid, exc)
            t = None
        if t is not None:
            transcripts[vid] = t
        progress(
            "transcripts",
            f"{len(transcripts)}/{i + 1} transcripts",
            (i + 1) / len(all_ids),
            {},
        )

    if not transcripts:
        raise BuildFailed("no transcripts available for any candidate video")
    coverage = len(transcripts) / len(all_ids)
    if coverage < MIN_TRANSCRIPT_COVERAGE:
        warnings.append(
            f"only {len(transcripts)}/{len(all_ids)} videos had transcripts "
            f"({coverage:.0%} coverage)"
        )

    # -- stage 5: moments, embed, score ----------------------------------
    progress("segment", "finding moments", 0.0, {})
    candidates_by_video: dict[str, list[Candidate]] = {}
    for i, (vid, transcript) in enumerate(transcripts.items()):
        meta = metas.get(vid)
        moments = detect_moments(transcript, outline.mode)
        rows: list[Candidate] = []
        for m in moments:
            if looks_like_junk(m.text):
                continue
            text = m.text
            # Auto-captions mangle proper nouns; repairing before embedding is
            # the only point at which it can still help retrieval.
            if transcript.kind in {"auto", "whisper"} and names:
                text = repair_names(text, names, deps.llm)
            rows.append(
                Candidate(
                    segment_id=0,
                    video_id=vid,
                    channel_id=(meta.channel_id if meta else "") or "",
                    t_start=m.t_start,
                    t_end=m.t_end,
                    text=text,
                    cosine=0.0,
                    transcript_kind=transcript.kind,
                    published_at=meta.published_at if meta else None,
                    view_count=(meta.view_count or 0) if meta else 0,
                    duration_s=(meta.duration_s or 0) if meta else 0,
                    title=(meta.title or "") if meta else "",
                    is_short=bool(meta and meta.source == "youtube_shorts"),
                )
            )
        candidates_by_video[vid] = rows
        progress("segment", f"moments from {i + 1} videos", (i + 1) / len(transcripts), {})

    all_candidates = [c for rows in candidates_by_video.values() for c in rows]
    if not all_candidates:
        raise BuildFailed("no usable moments found in any transcript")

    progress("segment", "embedding", 1.0, {"moments": len(all_candidates)})
    vectors = embed_texts([c.text for c in all_candidates], deps.embedder)
    for cand, vec in zip(all_candidates, vectors):
        cand.embedding = vec

    progress("score", "scoring moments", 0.0, {})
    kind = "quality" if outline.mode == "learn" else "intensity"
    segs = [
        Segment(video_id=c.video_id, t_start=c.t_start, t_end=c.t_end, text=c.text)
        for c in all_candidates
    ]
    scores = score_segments(segs, deps.llm, kind=kind)
    for cand, score in zip(all_candidates, scores):
        if kind == "quality":
            cand.quality = score
        else:
            cand.intensity = score
    progress("score", "scored", 1.0, {})

    # -- C4: channel credibility (Learn only) -----------------------------
    # Scored once per channel, not per video: credibility is a channel property
    # and re-scoring per candidate would be pure waste.
    if outline.mode == "learn":
        cred_by_channel: dict[str, float] = {}
        samples_by_channel: dict[str, list[str]] = {}
        for c in all_candidates:
            if c.channel_id:
                samples_by_channel.setdefault(c.channel_id, []).append(c.text)
        for channel_id, samples in samples_by_channel.items():
            pinned = seed_credibility(channel_id)
            if pinned is not None:
                cred_by_channel[channel_id] = pinned
                continue
            name = next(
                (m.channel_name for m in metas.values() if m.channel_id == channel_id),
                channel_id,
            )
            try:
                score, _ = score_channel(channel_id, name or channel_id, samples, deps.llm)
            except Exception as exc:  # noqa: BLE001
                log.warning("credibility scoring failed for %s: %s", channel_id, exc)
                score = DEFAULT_CREDIBILITY
            cred_by_channel[channel_id] = score
        for c in all_candidates:
            c.credibility = cred_by_channel.get(c.channel_id, DEFAULT_CREDIBILITY)

    # -- stage 6: ranking -------------------------------------------------
    progress("rank", "ranking", 0.0, {})
    by_video = {vid: rows for vid, rows in candidates_by_video.items() if rows}
    section_candidates: dict[str, list[Candidate]] = {}
    for label, vids in section_videos.items():
        pool: list[Candidate] = []
        for vid in vids:
            pool.extend(by_video.get(vid, []))
        if not pool:
            continue
        query_text = f"{outline.title} {label}"
        qvec = embed_texts([query_text], deps.embedder)[0]
        for c in pool:
            c.cosine = _cosine(qvec, c.embedding)
        section_candidates[label] = sorted(
            pool, key=lambda c: c.cosine, reverse=True
        )[:MAX_CANDIDATES_PER_SECTION]

    if not section_candidates:
        raise BuildFailed("no section retained any candidates after ranking")

    if outline.mode == "learn":
        ranked = {}
        used: set[tuple[str, float]] = set()
        contested_labels = {c.title: c.contested for c in outline.chapters}
        for label, pool in section_candidates.items():
            fresh = [c for c in pool if (c.video_id, c.t_start) not in used]
            picked = rank_chapter(fresh)
            if picked and contested_labels.get(label):
                # Contested history through one voice is the failure mode the
                # spec calls out; require two credible, differently-framed sources.
                picked = enforce_contested_selection(picked)
            if picked:
                ranked[label] = picked
                used.update((c.video_id, c.t_start) for c in picked)
    else:
        feed = build_feed(section_candidates)
        ranked = {}
        for label, cand in feed:
            ranked.setdefault(label, []).append(cand)
    progress("rank", "ranked", 1.0, {"sections": len(ranked)})

    if not ranked:
        raise BuildFailed("ranking selected no clips")

    # -- stage 8: vision (post-MVP, off unless DEEPCLIP_VISION is set) -----
    # Runs on final-round candidates only: this is the one stage whose cost
    # scales with clips rather than pages.
    if vision_enabled():
        final = [c for clips in ranked.values() for c in clips]
        progress("assemble", "looking at frames", 0.0, {"segments": len(final)})
        try:
            apply_vision(final, deps.llm, mode=outline.mode)
        except Exception as exc:  # noqa: BLE001
            log.warning("vision pass failed: %s", exc)
            warnings.append(f"vision pass failed: {exc}")

    # -- stage 7: assembly ------------------------------------------------
    progress("assemble", "writing the page", 0.0, {})
    if outline.mode == "learn":
        page = assemble_learn(outline, ranked, deps.llm)
    else:
        page = assemble_entertain(outline, ranked, deps.llm)

    page = _attach_metadata(page, metas)
    progress("assemble", "done", 1.0, {})

    cost = getattr(getattr(deps.llm, "usage", None), "cost_usd", 0.0) or 0.0
    return BuildResult(
        slug=outline.query_norm,
        mode=outline.mode,
        page=page,
        outline=_outline_dict(outline),
        cost_usd=cost,
        quota_spent=deps.youtube.quota.spent,
        warnings=warnings,
    )


class BuildFailed(RuntimeError):
    """The build cannot produce a page. Distinct from a partial/degraded build."""


def _attach_metadata(page: dict, metas: dict) -> dict:
    """Add channel/title/credit to every clip.

    Attribution is non-negotiable (C5), so it is attached here rather than
    trusted to the assembly model, which would be free to omit or invent it.
    """
    sections = page.get("chapters") or page.get("groups") or []
    for section in sections:
        for clip in section.get("clips", []):
            meta = metas.get(clip["video_id"])
            clip["channel"] = (meta.channel_name if meta else None) or "Unknown channel"
            clip["video_title"] = (meta.title if meta else None) or ""
            clip["channel_url"] = (
                f"https://www.youtube.com/channel/{meta.channel_id}"
                if meta and meta.channel_id
                else f"https://www.youtube.com/watch?v={clip['video_id']}"
            )
            clip["credit_url"] = (
                f"https://www.youtube.com/watch?v={clip['video_id']}"
                f"&t={int(clip['t_start'])}s"
            )
            clip["thumbnail"] = (
                f"https://i.ytimg.com/vi/{clip['video_id']}/hqdefault.jpg"
            )
    return page


def _sections(outline: Outline) -> dict[str, list[str]]:
    if outline.mode == "learn":
        return {c.title: (c.search_hints or [c.title]) for c in outline.chapters}
    return {
        g.label: (g.search_hints or [f"{outline.subject} {g.label}"])
        for g in outline.groupings
    }


def _section_labels(outline: Outline) -> list[str]:
    return list(_sections(outline))


def _outline_dict(outline: Outline) -> dict:
    return {
        "mode": outline.mode,
        "title": outline.title,
        "query": outline.query,
        "entity_type": outline.entity_type,
        "subject": outline.subject,
        "vibe": outline.vibe,
        "chapters": [
            {
                "title": c.title,
                "search_hints": c.search_hints,
                "coverage_goals": c.coverage_goals,
                "contested": c.contested,
            }
            for c in outline.chapters
        ],
        "groupings": [{"label": g.label, "search_hints": g.search_hints} for g in outline.groupings],
    }


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # both sides are L2-normalised on write

"""Run the pipeline against REAL YouTube captions, with no API keys.

Captions need no key, so this exercises the largest slice of the pipeline that
can be verified without spending anything:

    real transcripts -> sentences -> moment detection -> embedding
    -> (optional) Postgres persistence -> vector search

The LLM stages (outline, scoring, assembly) are stubbed with fixed plans, and
embeddings use the offline HashingEmbedder. What this proves is that the
non-LLM machinery works on messy real input rather than on tidy fixtures.

    python3 -m scripts.dry_run                       # in-memory only
    python3 -m scripts.dry_run --db                  # also persist + vector search
    python3 -m scripts.dry_run --video aircAruvnKk   # specific videos

Exit code is non-zero if any stage produced nothing, so this is usable in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

# macOS system Python has no usable root store; certifi supplies one.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

from services.worker.pipeline.embed import HashingEmbedder, embed_texts
from services.worker.pipeline.moments import cues_to_sentences, detect_moments
from services.worker.pipeline.rank_entertain import build_feed
from services.worker.pipeline.rank_learn import Candidate, rank_chapter
from services.worker.pipeline.score import looks_like_junk
from services.worker.sources.youtube import YouTubeTranscriptFetcher

# Real, verified video ids across several channels — enough to exercise the
# >=2-distinct-channels constraint honestly.
DEFAULT_VIDEOS = [
    ("aircAruvnKk", "3Blue1Brown"),
    ("IHZwWFHWa-w", "3Blue1Brown"),
    ("VMj-3S1tku0", "Andrej Karpathy"),
    ("UZDiGooFs54", "Welch Labs"),
    ("R9OHn5ZF4Uo", "CGP Grey"),
]


@dataclass
class StageReport:
    name: str
    ok: bool
    detail: str


def fmt(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def run(video_ids: list[tuple[str, str]], mode: str, use_db: bool) -> int:
    reports: list[StageReport] = []
    fetcher = YouTubeTranscriptFetcher()

    # -- stage 4: real transcripts ---------------------------------------
    transcripts = {}
    for vid, channel in video_ids:
        try:
            t = fetcher.fetch(vid)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {vid}: {exc}")
            continue
        if t is None:
            print(f"  ! {vid}: no transcript")
            continue
        transcripts[vid] = (t, channel)
        print(f"  {vid} ({channel}): {len(t.cues)} cues, kind={t.kind}")

    reports.append(
        StageReport(
            "transcripts",
            bool(transcripts),
            f"{len(transcripts)}/{len(video_ids)} fetched",
        )
    )
    if not transcripts:
        return summarise(reports)

    # -- sentence reconstruction -----------------------------------------
    total_sentences = sum(len(cues_to_sentences(t.cues)) for t, _ in transcripts.values())
    reports.append(
        StageReport("sentences", total_sentences > 0, f"{total_sentences} sentences")
    )

    # -- stage 5a: moment detection --------------------------------------
    candidates: list[Candidate] = []
    junk_dropped = 0
    for vid, (transcript, channel) in transcripts.items():
        moments = detect_moments(transcript, mode)
        print(f"\n  {vid}: {len(moments)} moments")
        for m in moments[:3]:
            print(f"    [{fmt(m.t_start)}-{fmt(m.t_end)}] score={m.score:.2f}")
            print(f"      {m.text[:100]}...")
        for m in moments:
            if looks_like_junk(m.text):
                junk_dropped += 1
                continue
            candidates.append(
                Candidate(
                    segment_id=0,
                    video_id=vid,
                    channel_id=channel,
                    t_start=m.t_start,
                    t_end=m.t_end,
                    text=m.text,
                    cosine=0.0,
                    transcript_kind=transcript.kind,
                    title=f"{channel} video",
                )
            )
    reports.append(
        StageReport(
            "moments",
            bool(candidates),
            f"{len(candidates)} candidates, {junk_dropped} junk dropped",
        )
    )
    if not candidates:
        return summarise(reports)

    # -- stage 5b: embedding ----------------------------------------------
    embedder = HashingEmbedder()
    vectors = embed_texts([c.text for c in candidates], embedder)
    for cand, vec in zip(candidates, vectors):
        cand.embedding = vec
    dims_ok = all(len(v) == embedder.dim for v in vectors)
    reports.append(
        StageReport("embed", dims_ok, f"{len(vectors)} vectors of dim {embedder.dim}")
    )

    # -- stage 6: ranking --------------------------------------------------
    query_vec = embed_texts(["how neural networks learn"], embedder)[0]
    for c in candidates:
        c.cosine = sum(a * b for a, b in zip(query_vec, c.embedding))

    if mode == "learn":
        picked = rank_chapter(candidates)
        channels = {c.channel_id for c in picked}
        ok = len(picked) > 0
        detail = f"{len(picked)} clips from {len(channels)} channels"
        if len(picked) >= 2 and len(channels) < 2:
            ok = False
            detail += "  <-- VIOLATES >=2-channel rule"
    else:
        feed = build_feed({"all": candidates})
        picked = [c for _, c in feed]
        ok = bool(picked)
        detail = f"{len(picked)} clips in feed"

    print("\n  ranked selection:")
    for c in picked:
        print(f"    [{fmt(c.t_start)}-{fmt(c.t_end)}] {c.channel_id}  cosine={c.cosine:.3f}")
    reports.append(StageReport("rank", ok, detail))

    # -- persistence + vector search --------------------------------------
    if use_db:
        reports.append(asyncio.run(_db_roundtrip(candidates, query_vec)))

    return summarise(reports)


async def _db_roundtrip(candidates: list[Candidate], query_vec: list[float]) -> StageReport:
    """Persist real segments and search them back.

    This is the only path that exercises repo.py against a real database with
    realistic data rather than hand-built rows.
    """
    try:
        from packages.db.repo import Repo, SegmentRow, VideoRow
    except ImportError as exc:
        return StageReport("db", False, f"import failed: {exc}")

    try:
        repo = await Repo.connect()
    except Exception as exc:  # noqa: BLE001
        return StageReport("db", False, f"no database: {exc}")

    try:
        await repo.init_schema()
        seen: set[str] = set()
        for c in candidates:
            if c.video_id in seen:
                continue
            seen.add(c.video_id)
            await repo.upsert_video(
                VideoRow(
                    id=c.video_id,
                    source="youtube",
                    title=c.title,
                    channel_id=c.channel_id,
                    channel_name=c.channel_id,
                    transcript_kind=c.transcript_kind,
                )
            )
            await repo.delete_segments_for_video(c.video_id)

        rows = [
            SegmentRow(
                video_id=c.video_id,
                t_start=c.t_start,
                t_end=c.t_end,
                text=c.text,
                embedding=c.embedding,
                quality=0.5,
            )
            for c in candidates
        ]
        ids = await repo.insert_segments(rows)
        results = await repo.search_segments(query_vec, limit=5)

        if not results:
            return StageReport("db", False, f"inserted {len(ids)} but search returned 0")
        top = results[0]
        detail = (
            f"inserted {len(ids)}, top hit {top['video_id']} "
            f"@{fmt(top['t_start'])} cosine={top['cosine']:.3f}"
        )
        return StageReport("db", True, detail)
    except Exception as exc:  # noqa: BLE001
        return StageReport("db", False, f"{type(exc).__name__}: {exc}")
    finally:
        await repo.close()


def summarise(reports: list[StageReport]) -> int:
    print("\n" + "=" * 60)
    for r in reports:
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.name:<12} {r.detail}")
    failed = [r for r in reports if not r.ok]
    print("=" * 60)
    if failed:
        print(f"{len(failed)} stage(s) failed")
        return 1
    print("all stages produced output")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the pipeline on real captions")
    parser.add_argument("--video", action="append", help="video id (repeatable)")
    parser.add_argument("--mode", default="learn", choices=["learn", "entertain"])
    parser.add_argument("--db", action="store_true", help="also persist and vector-search")
    args = parser.parse_args()

    videos = [(v, "unknown") for v in args.video] if args.video else DEFAULT_VIDEOS
    print(f"dry run: {len(videos)} videos, mode={args.mode}, db={args.db}\n")
    return run(videos, args.mode, args.db)


if __name__ == "__main__":
    raise SystemExit(main())

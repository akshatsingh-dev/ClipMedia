"""Build golden clip picks — the missing input that makes the eval real.

C7 says the golden pages are hand-curated with human-picked timestamps, and the
eval harness currently reports itself untrustworthy because they do not exist:
`overlap@k` compares generated clips against nothing and reads 0.000.

I cannot watch video, so I cannot create these. What this does instead is make it
a short job for a human: run the real moment detector over real transcripts,
print each candidate with its text and a jump link, and record accept/reject into
`eval/golden/picks/<slug>.json`.

    python3 -m scripts.pick_golden --slug how-neural-networks-work
    python3 -m scripts.pick_golden --slug x --video aircAruvnKk --auto-top 3

`--auto-top N` pre-accepts the N highest-scoring moments per video as a starting
point. Those are marked `"reviewed": false` so they are never mistaken for human
judgement — a machine-picked "golden" set would make the eval circular, scoring
the ranker against its own output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass

from services.worker.pipeline.moments import detect_moments
from services.worker.sources.youtube import YouTubeTranscriptFetcher

PICKS_DIR = Path(__file__).resolve().parent.parent / "eval" / "golden" / "picks"
FIXTURES = Path(__file__).resolve().parent.parent / "apps" / "web" / "public" / "fixtures"


def fmt(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def jump_url(video_id: str, t_start: float) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(t_start)}s"


def videos_from_fixture(slug: str) -> list[str]:
    """Reuse the videos already in a fixture page so picks line up with it."""
    path = FIXTURES / f"{slug}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    ids: list[str] = []
    for section in data.get("chapters") or data.get("groups") or []:
        for clip in section.get("clips", []):
            if clip["video_id"] not in ids:
                ids.append(clip["video_id"])
    return ids


def review(
    slug: str,
    video_ids: list[str],
    mode: str,
    auto_top: int,
    interactive: bool,
) -> dict:
    fetcher = YouTubeTranscriptFetcher()
    picks: list[dict] = []
    reviewed_any = False

    for vid in video_ids:
        transcript = fetcher.fetch(vid)
        if transcript is None:
            print(f"  ! {vid}: no transcript, skipping", file=sys.stderr)
            continue

        moments = detect_moments(transcript, mode)
        print(f"\n=== {vid} — {len(moments)} candidate moments ===")

        for i, m in enumerate(moments):
            preview = " ".join(m.text.split())[:220]
            print(f"\n[{i + 1}/{len(moments)}] {fmt(m.t_start)}–{fmt(m.t_end)} "
                  f"({m.duration_s:.0f}s, score={m.score:.2f})")
            print(f"  {jump_url(vid, m.t_start)}")
            print(f"  {preview}...")

            accepted = False
            note = ""
            if interactive:
                try:
                    answer = input("  keep? [y/N/q] ").strip().lower()
                except EOFError:
                    answer = "q"
                if answer == "q":
                    interactive = False
                elif answer == "y":
                    accepted = True
                    reviewed_any = True
                    note = input("  why (optional): ").strip()
            elif i < auto_top:
                accepted = True

            if accepted:
                picks.append(
                    {
                        "video_id": vid,
                        "t_start": round(m.t_start, 2),
                        "t_end": round(m.t_end, 2),
                        "note": note,
                        # False for auto-picks: a machine-picked golden set would
                        # score the ranker against its own output.
                        "reviewed": bool(interactive or note),
                    }
                )

    return {
        "slug": slug,
        "mode": mode,
        "clips": picks,
        "coverage_goals": [],
        "human_reviewed": reviewed_any,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build golden clip picks")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--video", action="append", help="video id (repeatable)")
    parser.add_argument("--mode", default="learn", choices=["learn", "entertain"])
    parser.add_argument("--auto-top", type=int, default=0,
                        help="pre-accept the top N per video (marked unreviewed)")
    parser.add_argument("--no-interactive", action="store_true")
    args = parser.parse_args()

    video_ids = args.video or videos_from_fixture(args.slug)
    if not video_ids:
        print(f"no videos for slug {args.slug!r}; pass --video", file=sys.stderr)
        return 1

    interactive = not args.no_interactive and sys.stdin.isatty()
    if not interactive and not args.auto_top:
        print("not a TTY and no --auto-top: nothing would be picked", file=sys.stderr)
        return 1

    result = review(args.slug, video_ids, args.mode, args.auto_top, interactive)

    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    out = PICKS_DIR / f"{args.slug}.json"
    out.write_text(json.dumps(result, indent=2))

    print(f"\nwrote {len(result['clips'])} picks -> {out}")
    if not result["human_reviewed"]:
        # Loud, because a silently-machine-made golden set is worse than none:
        # the eval would look validated while measuring nothing.
        print(
            "\nWARNING: no human review recorded. These picks came from the same\n"
            "  detector the eval scores, so overlap@k against them is circular and\n"
            "  proves nothing. Re-run interactively before trusting any result."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Eval runner — score built pages against the golden standard.

    python3 -m eval.run                    # score fixture pages, metrics only
    python3 -m eval.run --judge            # add the LLM judge (needs a key)
    python3 -m eval.run --page gandhi      # one page

Writes timestamped results to eval/results/ and reports the delta against the
previous run, which is the number that matters when tuning ranking: local prompt
tweaks routinely help one page and quietly break another.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.judge import judge_page, regression_delta, save_result
from eval.metrics import ClipRef, passes_ship_gate, score_page

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "apps" / "web" / "public" / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden" / "picks"


def load_pages(only: str | None = None) -> list[dict]:
    if not FIXTURES.exists():
        return []
    pages = []
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text())
        if only and data.get("slug") != only:
            continue
        pages.append(data)
    return pages


def load_golden(slug: str) -> tuple[list[ClipRef], list[str]]:
    """Hand-picked clips and coverage goals for a page, if recorded.

    Absent for now — see DECISIONS D3: nobody has watched these videos and
    picked real timestamps yet. Without it, overlap_at_k is not meaningful and
    the run says so rather than reporting a confident zero.
    """
    path = GOLDEN_DIR / f"{slug}.json"
    if not path.exists():
        return [], []
    data = json.loads(path.read_text())
    clips = [
        ClipRef(
            video_id=c["video_id"],
            t_start=float(c["t_start"]),
            t_end=float(c["t_end"]),
            channel=c.get("channel", ""),
            text=c.get("note", ""),
        )
        for c in data.get("clips", [])
    ]
    return clips, data.get("coverage_goals", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Score pages against the golden standard")
    parser.add_argument("--page", help="only this slug")
    parser.add_argument("--judge", action="store_true", help="run the LLM judge (needs a key)")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    pages = load_pages(args.page)
    if not pages:
        print("no pages found; run `python3 -m eval.build_fixtures` first", file=sys.stderr)
        return 1

    llm = None
    if args.judge:
        try:
            from services.worker.llm.client import build_client

            llm = build_client()
        except Exception as exc:
            print(f"cannot run judge: {exc}", file=sys.stderr)
            return 1

    scores = []
    ungraded = []
    for page in pages:
        slug = page.get("slug", "?")
        golden, goals = load_golden(slug)
        score = score_page(page, golden=golden, coverage_goals=goals, k=args.k)

        if llm is not None:
            try:
                result = judge_page(page, llm)
                score.judge_score = round(result.overall, 2)
                for section in result.sections:
                    for issue in section.issues:
                        score.notes.append(f"{section.label}: {issue}")
            except Exception as exc:  # noqa: BLE001
                score.notes.append(f"judge failed: {exc}")

        if not golden:
            ungraded.append(slug)

        delta = regression_delta(slug, score.composite)
        payload = score.to_dict()
        payload["delta"] = round(delta, 4) if delta is not None else None
        save_result(slug, payload)
        scores.append(score)

        arrow = ""
        if delta is not None:
            arrow = f"  ({'+' if delta >= 0 else ''}{delta:.3f} vs last run)"
        print(f"\n{slug}  composite={score.composite:.3f}{arrow}")
        print(f"  coverage_recall   {score.coverage_recall:.3f}")
        print(f"  overlap@{args.k:<9} {score.overlap_at_k:.3f}")
        print(f"  redundancy        {score.redundancy_rate:.3f}")
        print(f"  junk              {score.junk_rate:.3f}")
        print(f"  channel_diversity {score.channel_diversity:.3f}")
        if score.judge_score is not None:
            print(f"  judge             {score.judge_score}/5")
        for note in score.notes:
            print(f"  ! {note}")

    print()
    if ungraded:
        # Loud, because a green composite here would otherwise look like evidence
        # the ranking is good when nothing has been compared to a human pick.
        print(
            "WARNING: no golden picks for: " + ", ".join(ungraded) + "\n"
            "  overlap@k is meaningless for these pages and the composite is\n"
            "  NOT evidence that ranking works. Hand-pick timestamps into\n"
            "  eval/golden/picks/<slug>.json to make this a real eval."
        )

    gate = passes_ship_gate(scores)
    print(f"\nship gate ({len(scores)} pages): {'PASS' if gate else 'FAIL'}")
    if ungraded:
        print("  (gate is not trustworthy without golden picks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

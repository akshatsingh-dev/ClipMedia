"""Batch page pre-builder (C8).

The cost model's central bet: "Pre-building the top 5k pages ≈ $4-5k — that spend
IS the seed of the moat." This is the driver for that spend.

Three properties matter more than speed:
  - **Resumable.** A 5k-page run will be interrupted. Progress lives in Postgres
    (`deep_pages.status`), so a restart skips what is already built rather than
    paying twice.
  - **Budgeted.** Stops on a dollar ceiling and on the YouTube daily quota,
    because both are hard limits and overrunning either is expensive or blocking.
  - **Loud about failures.** A page that fails silently is worse than one that
    never ran — it looks built.

    python3 -m scripts.prebuild --queries queries.txt --budget 50
    python3 -m scripts.prebuild --queries queries.txt --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from packages.db.repo import Repo
from services.worker.pipeline.build import BuildDeps, BuildFailed, build_page
from services.worker.pipeline.embed import build_embedder
from services.worker.pipeline.outline import normalize_query
from services.worker.sources.youtube import QuotaExceeded, QuotaLedger, YouTubeSource

# YouTube's default daily allowance. Stop before the API starts refusing, so the
# run ends cleanly rather than mid-page.
DAILY_QUOTA = 10_000
QUOTA_SAFETY_MARGIN = 500


@dataclass
class RunStats:
    built: int = 0
    skipped: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    quota_spent: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        elapsed = time.time() - self.started_at
        return (
            f"built={self.built} skipped={self.skipped} failed={self.failed} "
            f"cost=${self.cost_usd:.2f} quota={self.quota_spent}u "
            f"elapsed={elapsed / 60:.1f}min"
        )


def load_queries(path: str) -> list[str]:
    """One query per line. Blank lines and # comments ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        q = line.strip()
        if not q or q.startswith("#"):
            continue
        # Dedupe on the normalised form — that is the cache key, so two queries
        # normalising the same would be one page built twice.
        norm = normalize_query(q)
        if norm in seen:
            continue
        seen.add(norm)
        out.append(q)
    return out


async def prebuild(
    queries: list[str],
    budget_usd: float,
    quota_limit: int,
    dry_run: bool,
    force: bool,
) -> RunStats:
    stats = RunStats()
    repo = await Repo.connect()
    quota = QuotaLedger(daily_limit=quota_limit)

    try:
        for i, query in enumerate(queries, 1):
            slug = normalize_query(query)

            if not force:
                existing = await repo.get_page(slug)
                if existing and existing.get("status") == "ready":
                    stats.skipped += 1
                    print(f"[{i}/{len(queries)}] skip (cached): {query}")
                    continue

            if stats.cost_usd >= budget_usd:
                print(f"\nSTOPPING: budget ${budget_usd:.2f} reached")
                break
            if quota.remaining < QUOTA_SAFETY_MARGIN:
                print(f"\nSTOPPING: quota nearly exhausted ({quota.remaining}u left)")
                break

            if dry_run:
                print(f"[{i}/{len(queries)}] would build: {query}")
                stats.skipped += 1
                continue

            print(f"[{i}/{len(queries)}] building: {query}")
            deps = BuildDeps(
                youtube=YouTubeSource(quota=quota),
                llm=_llm(),
                embedder=_embedder(),
                repo=repo,
            )
            try:
                result = await asyncio.to_thread(build_page, query, deps)
            except (BuildFailed, QuotaExceeded) as exc:
                stats.failed += 1
                stats.failures.append((query, str(exc)))
                await repo.save_page(slug, "learn", None, None, "failed")
                print(f"    FAILED: {exc}")
                if isinstance(exc, QuotaExceeded):
                    print("\nSTOPPING: quota exhausted mid-build")
                    break
                continue
            except Exception as exc:  # noqa: BLE001
                stats.failed += 1
                stats.failures.append((query, f"{type(exc).__name__}: {exc}"))
                await repo.save_page(slug, "learn", None, None, "failed")
                print(f"    ERROR: {type(exc).__name__}: {exc}")
                continue

            await repo.save_page(
                slug, result.mode, result.outline, result.page, "ready", result.cost_usd
            )
            stats.built += 1
            stats.cost_usd += result.cost_usd
            stats.quota_spent = quota.spent
            clips = sum(
                len(s.get("clips", []))
                for s in (result.page.get("chapters") or result.page.get("groups") or [])
            )
            print(
                f"    ok: {result.mode}, {clips} clips, "
                f"${result.cost_usd:.3f}, {quota.spent}u total"
            )
            for w in result.warnings:
                print(f"    ! {w}")
    finally:
        await repo.close()

    return stats


# Constructed lazily so --dry-run works with no API keys present.
def _llm():
    from services.worker.llm.client import build_client

    return build_client()


def _embedder():
    return build_embedder()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-build pages in batch")
    parser.add_argument("--queries", required=True, help="file with one query per line")
    parser.add_argument("--budget", type=float, default=25.0, help="USD ceiling")
    parser.add_argument("--quota", type=int, default=DAILY_QUOTA)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="rebuild cached pages")
    parser.add_argument("--report", help="write a JSON report here")
    args = parser.parse_args()

    try:
        queries = load_queries(args.queries)
    except OSError as exc:
        print(f"cannot read {args.queries}: {exc}", file=sys.stderr)
        return 1
    if not queries:
        print("no queries found", file=sys.stderr)
        return 1

    print(f"{len(queries)} unique queries, budget ${args.budget:.2f}, quota {args.quota}u\n")
    stats = asyncio.run(
        prebuild(queries, args.budget, args.quota, args.dry_run, args.force)
    )

    print("\n" + "=" * 60)
    print(stats.summary())
    if stats.failures:
        print(f"\n{len(stats.failures)} failures:")
        for query, reason in stats.failures[:20]:
            print(f"  {query}: {reason}")

    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {
                    "built": stats.built,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                    "cost_usd": round(stats.cost_usd, 4),
                    "quota_spent": stats.quota_spent,
                    "failures": stats.failures,
                },
                indent=2,
            )
        )
    return 1 if stats.failed and not stats.built else 0


if __name__ == "__main__":
    raise SystemExit(main())

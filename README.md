# Deep Clip Search

Implementation of Part C of `deep-clip-search-master-doc.md`.

## See the product (no API keys, no Docker)

```bash
cd deepclip/apps/web
npm install
npm run dev
# open http://localhost:3000
```

Two pages are built:

- `/q/how-neural-networks-work` — **Learn Mode** Deep Page. Chapters, timestamped
  clips, per-clip "why this clip", creator credit on every clip, ends at the bottom.
- `/e/legendary-internet-moments` — **Entertain Mode** feed. Full-viewport snap
  scroll, autoplay on scroll-into-view, arrow-key/`j`/`k` nav, progress rail.
  **The feed ends** with an end-card — no loop, per the doc's inviolable rule.

### What is real and what is not

| | Status |
|---|---|
| Channel names, video titles, thumbnails | **Real** — resolved via YouTube's public oEmbed endpoint |
| Video IDs | **Real** — every one verified to resolve |
| Clip timestamps (`t_start`/`t_end`) | **Not verified** — plausible placeholders; nothing watched these videos |
| Ranking applied to these pages | **No** — the fixtures are hand-defined; the ranker is tested but not yet wired to real retrieval |

The UI shows a "Demo data" banner saying so. Replacing the timestamps with
hand-picked ones is the doc's next-action #1 and is what turns these into a real
eval standard.

### Known unverified

YouTube embeds did not render inside the automated browser used during
development (a bare `<iframe>` with no application code was equally blank, so it
is environmental, not a component bug). **Playback has therefore not been
visually confirmed.** It should work in a normal browser; that is the first thing
to check.

## Run the tests

```bash
cd deepclip
python3 -m pytest -q                                    # 266 offline
DEEPCLIP_LIVE=1 python3 -m pytest tests/test_integration_live.py -q   # real captions
DEEPCLIP_DB=1  python3 -m pytest tests/test_db_integration.py  -q     # needs Postgres
```

## Regenerate fixtures

```bash
cd deepclip
python3 -m eval.build_fixtures
```

Edit `eval/golden/pages.py` to change the pages. The builder fails loudly rather
than writing an empty page if video IDs stop resolving.

## What has never been executed

Three surfaces are written and unit-tested but have never touched reality. This
is the main risk in the project, so it is stated plainly rather than buried:

| Surface | Why | How to close it |
|---|---|---|
| **All SQL** (`packages/db/repo.py`) | `docker pull` hangs — Docker Desktop is set to proxy through `http.docker.internal:3128`, which is not responding (the network itself is fine) | Settings → Resources → Proxies → "No proxy", restart Docker, then `docker compose up -d postgres && DEEPCLIP_DB=1 python3 -m pytest tests/test_db_integration.py -q` (21 tests ready) |
| **Every LLM stage** (1, 5, 7, credibility, judge) | No `ANTHROPIC_API_KEY` | Set the key, then `python3 -m eval.run --judge` |
| **Video playback** | YouTube embeds do not render in the automated browser used here | Open the app in a normal browser |

Tests against fakes agreed with the code in all three cases. That is worth
distrusting: of the bugs found while building this, the two most expensive
(a transcript-library API mismatch that would have silently skipped every video,
and a cache-key bug that would have paid to rebuild pages that already existed)
surfaced only when something ran against reality.

## Pipeline status vs. the spec

| Stage | State |
|---|---|
| 1 — Intent + outline | Built, fakes only |
| 2 — Candidate retrieval | Built; quota mitigations enforced in code. Never hit the live API |
| 3 — Shorts handling | Built (duration classify + `#shorts` variants) |
| 4 — Transcript ingestion | Built + **verified against real captions**. Whisper fallback not wired |
| 5 — Moments / segment / embed / score | Moment detection **verified on a real transcript**; LLM scoring fakes only |
| 6 — Ranking | Built + tested, both modes |
| 7 — Assembly | Built, fakes only. No-new-facts rule enforced in code |
| 8 — Vision pass | Not built (post-MVP by spec) |
| C4 credibility | Built + wired, fakes only |
| C7 eval harness | Built; **no golden picks yet, so it reports itself untrustworthy** |
| API + SSE | Built + tested |
| Worker (arq) | Built, never run |
| Frontend | Built — both renderers, search, live build stream |
| Reel-import | Built (YouTube seed; IG/TikTok inbound-only) |

Still no call has ever been made to the YouTube Data API or the Anthropic API.

## Going live

Set `YOUTUBE_API_KEY` and `ANTHROPIC_API_KEY`, then `docker compose up`. The
external seams are `YouTubeClient` (`services/worker/sources/youtube.py`) and the
not-yet-written LLM client; both have fakes used by the tests.

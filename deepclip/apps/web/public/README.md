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
python3 -m pytest -q
```

## Regenerate fixtures

```bash
cd deepclip
python3 -m eval.build_fixtures
```

Edit `eval/golden/pages.py` to change the pages. The builder fails loudly rather
than writing an empty page if video IDs stop resolving.

## Pipeline status vs. the spec

| Stage | State |
|---|---|
| 1 — Intent + outline | **Not built** (needs Anthropic API key) |
| 2 — Candidate retrieval | **Built**, untested against the live API. Quota mitigations enforced in code |
| 3 — Shorts handling | **Built** (post-hoc duration classify + `#shorts` hint variants) |
| 4 — Transcript ingestion | **Partial** — manual→auto caption chain built; Whisper fallback not wired |
| 5 — Segmentation | **Built + tested.** Embedding and LLM scoring **not built** |
| 6 — Ranking | **Built + tested**, both modes |
| 7 — Assembly | **Not built** (needs Anthropic API key) |
| 8 — Vision pass | Not built (post-MVP by spec) |
| API + SSE | **Not built** |
| Frontend | **Built** — both renderers, lazy-mount iframes |
| Reel-import | **Not built** |
| Eval harness | **Partial** — golden pages defined; no metrics or LLM judge yet |

Nothing here has made a single call to the YouTube Data API or the Anthropic API.

## Going live

Set `YOUTUBE_API_KEY` and `ANTHROPIC_API_KEY`, then `docker compose up`. The
external seams are `YouTubeClient` (`services/worker/sources/youtube.py`) and the
not-yet-written LLM client; both have fakes used by the tests.

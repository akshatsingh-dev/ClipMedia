# DECISIONS

Choices made autonomously while building Part C. Each records what was decided,
why, and what would reverse it.

## D1 — No API keys present; build for key-injection, demo on fixtures
`YOUTUBE_API_KEY` and `ANTHROPIC_API_KEY` are unset in this environment. Stages
that call YouTube Data API or Claude (1, 2, 4-partial, 5-scoring, 7) cannot run
or be verified end-to-end.

Decision: every external call sits behind a narrow seam (`YouTubeClient`,
`LLMClient`) with a fake implementation for tests. Adding keys is the only step
needed to go live. Demo/UI runs on fixture pages instead.

## D2 — Golden pages double as demo fixtures
The doc's own next-actions (lines 408-409) call for hand-built Gandhi and
"funny Speed clips" pages as the eval standard. Rather than build throwaway mock
data, the demo is backed by those same fixtures, so demo work is eval work.

## D3 — Real video IDs, verified via public oEmbed
YouTube's oEmbed endpoint needs no API key. Fixture video IDs are validated
through it, and title/channel come from the oEmbed response — so those fields
are real, not invented.

**Caveat, important:** clip *timestamps* (`t_start`/`t_end`) are NOT verified.
Nothing here watched the videos. They are plausible placeholders. The UI labels
fixture pages as unverified demo data so this is not mistaken for curation.
Reversing this requires a human (or the live pipeline) picking real timestamps.

## D4 — Frontend runs without Postgres/Docker
So the UI is testable with one command after a break, the Next.js app reads
fixture JSON directly when the API is unavailable. Docker/Postgres are needed
only for the real pipeline, not to look at the product.

## D5 — Scroll UX: copy the interaction pattern, not the assets
Per instruction to not reinvent feed UX, the feed uses the now-standard
short-form pattern: full-viewport snap scroll, one clip per pane, autoplay on
intersection, pause off-screen, right-rail actions. This is a widely-used
interaction convention, implemented from scratch here — no Meta/TikTok code,
markup, or design assets are copied.

Deliberate divergence from those apps, per the doc's inviolable rule (A4.4,
D6): the feed **ends** with an end-card. No infinite loop, no autoplay past the
last clip.

## D6 — Segmentation: greedy sentence-aligned packing
Spec says "semantic boundaries" but real semantic segmentation needs an LLM
call per video (cost) or a local model (dependency). v1 uses cue-timing +
sentence-boundary packing within the 30-90s target. Cheap, deterministic,
testable. Revisit if eval shows segment boundaries are a ranking-quality
bottleneck.

## D7 — Demo topic changed from Gandhi/Speed to neural networks/viral classics
The doc names Gandhi (Learn) and "funny Speed clips" (Entertain) as the golden
pages. Building those needs real video IDs for that footage, and I had no
compliant way to get them: outbound discovery requires the YouTube Data API key
(absent), and scraping search results would violate the ToS posture the whole
architecture rests on (B4). Inventing IDs would have produced dead embeds.

Decision: build the demo from videos whose IDs are verifiable — an ML-explainer
Learn page (3Blue1Brown, Karpathy, Welch Labs, CGP Grey, Umar Jamil, MITCBMM)
and a viral-classics Entertain feed. Every id was checked against oEmbed.

The Learn page satisfies the >=2-distinct-channels-per-chapter rule naturally,
so it exercises the real constraint. Swap in Gandhi/Speed once a key exists —
`eval/golden/pages.py` is the only file that changes.

## D8 — Embed playback is unverified
YouTube embeds render black in the automated browser used during development.
Ruled out as an application bug: a bare `<iframe>` in a static HTML file, with
no application code involved, is equally blank, while YouTube *thumbnails*
(i.ytimg.com) load fine on the same pages. So the embed frame specifically is
blocked in that browser.

Consequence: everything up to the iframe boundary is verified (correct mount
and unmount counts, sizing, src construction, facade, attribution), but no clip
has been watched playing. First thing to check in a normal browser.

## D9 — Moment detection: TextTiling for Learn, intensity peaks for Entertain
The spec says segments come from "semantic boundaries" but never says how to
pick the exact clip in/out points. That is the actual curation problem, so it
gets its own module (`pipeline/moments.py`) separate from retrieval
segmentation.

Two algorithms, because the modes define "moment" differently:

**Learn — TextTiling (Hearst 1997).** Slide a window over the token stream,
measure lexical cohesion across each gap, cut at the valleys. Chosen over an
LLM-per-video call because this runs over *every* candidate video; per-video
Sonnet calls would blow up the C8 cost model. It is unsupervised, deterministic,
and needs no model. Boundaries are then nudged to the nearest sentence with good
`opening_quality` — anaphoric openers ("it does that by...") are penalised hard,
since a clip that starts mid-thought is the clearest tell of a machine edit.

**Entertain — intensity peak detection.** Score each sentence on non-speech cues
(`[laughter]`), exclamation cadence, shouted caps, token repetition ("no no no"),
and delivery rate; find local maxima; expand outward while intensity stays above
35% of peak. Then add **4s pre-roll** — cutting exactly on the laugh loses the
setup and the clip is incomprehensible. That pre-roll is the single most
important parameter in the module.

Validated on the real 3Blue1Brown neural-network transcript (286 cues): 13 topic
boundaries at genuine subject shifts, top moments opening on "But if I told
you...", "So once you write down...". Manual captions are the easy case;
auto-caption performance is untested.

## D10 — Bug: transcript library API mismatch would have skipped every video
`youtube-transcript-api` >=1.0 replaced the static `list_transcripts` with
instance `.list()`. The adapter called the old one inside a broad `except`, so
every video would have logged "no transcript listing" and been silently skipped
— the pipeline would have looked like it worked and produced nothing. Now
supports both generations, and both snippet-object and dict cue formats.

Found only because a live test was run against a real video. Offline fakes would
never have caught it, which is why `tests/test_integration_live.py` exists
(network-gated behind `DEEPCLIP_LIVE=1`).

## D14 — Embedder is a seam, and the offline one is opt-in only
C1 defers the embedding choice to a benchmark (bge-m3 vs. a hosted model on 200
queries). Rather than pre-empt it, `Embedder` is a protocol with three
implementations: bge-m3 (default; local, free, no key), Voyage (hosted), and
`HashingEmbedder`.

HashingEmbedder is deterministic and needs no model, so the full
segment -> embed -> store -> vector-search path can be exercised offline. It is
NOT semantic and `build_embedder` will not select it unless explicitly asked —
if it were ever the fallback, retrieval quality would silently drop to zero,
which is the worst possible failure mode because everything would still appear
to work.

Dimension is pinned at 1024: `segments.embedding` is VECTOR(1024) with an HNSW
index on it, so changing dims is a migration, not a config flip.

## D15 — Page builds are claimed atomically
`claim_page_build` inserts the row as 'building' and `/api/build` returns
`joined: true` when a build is already in flight. Without this, two users hitting
the same uncached query would each pay a full ~$1 build for the same page.

## D16 — Progress never blocks the build
`ProgressBus.publish` uses `put_nowait` and drops on a full queue; the Redis
publisher swallows its own errors. A stalled or disconnected SSE client must not
be able to stall or fail a page build — progress is advisory, the page is the
product.

The in-process bus is only valid within the API's own event loop. Cross-process
progress (the deployed topology, where the worker is a separate container) goes
over `RedisProgressBus`.

## D17 — API startup and SSE timeouts are bounded and configurable
The API previously blocked on startup when Postgres/Redis were unreachable (arq
retries for ~5s), and the SSE generator held open for the full 300s timeout
because `is_disconnected()` never fires under TestClient. Both are now
`asyncio.wait_for`-bounded and env-configurable, and `tests/conftest.py` sets
short values plus unroutable DSNs so no test can reach a real service.

Suite went from hanging to 2.2s.

## D18 — Orchestrator is queue-agnostic; the worker is a thin wrapper
`pipeline/build.py` runs stages 1-7 with no arq/Redis imports, so it can be
called from tests, a CLI, or a pre-building script (the C8 plan to pre-build the
top 5k pages needs exactly that). `services/worker/main.py` only handles process
concerns: dependency construction, Redis progress, persistence.

## D19 — Degrade, never lose the page
Three failure classes are treated as expected rather than exceptional:
  - **Quota exhaustion mid-build** — remaining sections get no candidates, a
    warning is recorded, and the page ships with what was retrieved. Quota
    running out is the #1 stated MVP risk (D6); losing the whole build to it
    would be the worst possible response.
  - **A video with no transcript** — skipped. Below 50% coverage the result
    carries a warning so the caller knows the page rests on a thin slice.
  - **An exception fetching one transcript** — caught per video.

Only three conditions raise `BuildFailed`: zero candidate videos, zero
transcripts, zero usable moments. Each means there is genuinely no page to make.

## D20 — Attribution is attached by us, never by the model
`_attach_metadata` writes channel, title, credit URL (with timestamp) and
thumbnail onto every clip after assembly. Asking the assembly model to emit
attribution would leave it free to omit or invent it, and per-clip creator credit
is the ToS posture and the creator-goodwill argument the whole product rests on
(C5, B4).

## D21 — Reel-import enforces platform rules structurally
Instagram/TikTok import *raises* without user-supplied caption text rather than
attempting any fetch, so there is no code path that could crawl them even by
mistake. Instagram output is official oEmbed blockquote markup only. Both
platforms always set `needs_confirmation`, since caption-only analysis is thin
and the spec requires a one-tap user confirmation before building on it.

## D22 — Bug: transcript-coverage warning never fired at the boundary
The check was `len(transcripts) < len(all_ids) / 3`, so exactly one third
coverage (1 of 3) compared 1 < 1.0 and produced no warning. Replaced with a named
`MIN_TRANSCRIPT_COVERAGE = 0.5` ratio, which is both correct at the boundary and
a more useful threshold — a page built on under half the retrieved candidates is
worth flagging.

## D23 — Frontend degrades to fixtures when the API is down
`lib/api.ts` tries the FastAPI gateway with a 2.5s timeout and falls back to
fixture JSON. Live building genuinely cannot work without keys + Postgres +
Redis + a worker, so the app treats a missing API as a normal state rather than
an error: prebuilt pages stay browsable, and the /build route explains exactly
what is missing instead of surfacing a bare "Failed to fetch".

## D24 — Build stream renders the outline before any clip exists
Stage 1 emits chapter titles, and BuildStream renders them immediately. This is
the C5 perceived-latency claim made real: a 60s build shows the shape of the page
in ~5s. Progress is weighted per stage (retrieval and transcripts dominate wall
clock), so the bar does not sit at 20% for most of a build.

The effect guards against React StrictMode double-invocation — without it, dev
mode would enqueue every build twice, and each build costs about a dollar.

## D25 — Credibility is scored per channel, cached, and never punishes the unknown
C4 scoring runs once per channel per build, not per video. Allowlisted channels
skip the model entirely. Any failure — no samples, malformed response, exception
— returns the neutral 0.5 rather than a low score: an unscored channel must not
be treated as untrustworthy, which would silently bury new creators.

Contested chapters (flagged by stage 1) go through `enforce_contested_selection`,
requiring >=2 channels above 0.7 with differing framing. If the corpus genuinely
cannot satisfy it, the original selection stands — a thin chapter beats fabricated
balance.

## D26 — Eval harness reports its own untrustworthiness
The metrics run, but there are no hand-picked golden timestamps yet (D3), so
`overlap_at_k` compares against nothing and reads 0.000. Rather than let a green
composite imply the ranking is validated, `eval/run.py` prints a loud warning
naming every page without golden picks and marks the ship gate untrustworthy.

A metric that silently measures nothing is worse than no metric, because it
looks like evidence.

## D27 — The eval immediately caught a real defect in the golden page
First run reported `channel_diversity 0.857` on the Learn page: the "Building one
yourself" chapter had two Karpathy clips and no second voice, violating the
>=2-distinct-channels rule (C6) that the ranker is supposed to enforce. A third
channel was added and the composite moved +0.021.

Worth recording because the page was hand-written by me and looked fine. This is
the argument for building the harness before tuning ranking, exactly as C7 says.

## D28 — Docker Hub is unreachable in this environment; the SQL is unexecuted
Confirmed by attempting to pull `hello-world` (13KB): it times out, exactly like
`pgvector/pgvector:pg16` did over an hour of trying. This is a hard environmental
limit, not a slow network.

Consequence: **every line of SQL in `packages/db/repo.py` has never been
executed.** Unit tests cover the serialisation helpers around it, which is not
the same thing and would not catch a syntax error, a wrong ON CONFLICT clause, or
a bad pgvector cast.

Rather than leave that gap implicit, `tests/test_db_integration.py` contains 21
tests covering exactly what unit tests structurally cannot — schema application,
HNSW index creation, vector round-trips, similarity ordering, the COALESCE-on-
upsert behaviour, TTL expiry, and the build-claim lock. They run with one
command once a database exists:

    docker compose up -d postgres
    DEEPCLIP_DB=1 python3 -m pytest tests/test_db_integration.py -q

This is the highest-value unverified surface in the project.

## D29 — Repo hygiene: node_modules was committed, README was served as a web asset
Two mistakes of mine, found while fixing a path error:

1. `deepclip/apps/web/node_modules` was tracked — ~1,000 files of dependencies in
   git. Added `.gitignore` and untracked it (plus `.next/` and `.pytest_cache/`).
   Tracked files went from ~1,100 to 131.
2. `README.md` was written into `deepclip/apps/web/public/`, because the shell
   was still in that directory from an earlier debugging step. Next.js serves
   `public/` verbatim, so the project README was being published at `/README.md`.
   Moved to the repo root.

Recorded rather than quietly fixed: both came from not checking where a `cat >`
landed, and the second one shipped internal notes to a public path.

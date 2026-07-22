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

## D28 — Docker pulls hang behind a misconfigured proxy; the SQL is unexecuted
**Corrected.** I first concluded "Docker Hub is unreachable" after `hello-world`
(13KB) failed to pull. That claim was wrong, and the evidence was weak — the task
had been killed, not cleanly failed.

Direct check: `auth.docker.io` returns 200 and `registry-1.docker.io` returns 401
(the expected unauthenticated response), both under 250ms. The network is fine.

Actual cause: Docker Desktop is configured with
`HTTP/HTTPS Proxy: http.docker.internal:3128`, which is not responding. Every
`docker pull` hangs on it while plain HTTPS works. This is a Docker Desktop
setting on the user's machine — possibly deliberate — so it has been left alone
and reported rather than changed.

Fix (user's call): Docker Desktop → Settings → Resources → Proxies → set to
"No proxy" or "System", then restart Docker Desktop.

Consequence either way: **every line of SQL in `packages/db/repo.py` has never
been executed.** Unit tests cover the serialisation helpers around it, which
would not catch a syntax error, a wrong ON CONFLICT clause, or a bad pgvector
cast.

`tests/test_db_integration.py` holds 21 tests covering exactly what unit tests
structurally cannot — schema application, HNSW index creation, vector
round-trips, similarity ordering, COALESCE-on-upsert, TTL expiry, and the
build-claim lock:

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

## D30 — Stage 8 shipped off by default, with the cost cap as code
Vision is the only stage whose cost scales with *clips* rather than *pages*, so
an unbounded version would quietly dominate the C8 budget. Three guardrails:
`DEEPCLIP_VISION` defaults off (post-MVP per spec), a hard 200-segment cap that
truncates loudly, and it runs on final-round candidates only — after ranking, not
before.

Frames come from YouTube's public still-image endpoints. No video is downloaded,
consistent with the constraint governing the whole architecture (B4).

Failure degrades to empty tags: `visual_richness` is 0.10 of the ranking score,
so losing it should cost a little quality, never a page.

## D31 — Gap check against the spec's file layout
Compared the repo against the C6 structure. Five differences; four are deliberate
consolidation, one was a real gap:

- `services/api/sse.py` → SSE lives in `progress.py` + the route in `main.py`.
  Same functionality, split along a more useful seam (the bus is reusable by the
  worker over Redis).
- `pipeline/retrieve.py`, `pipeline/transcripts.py` → inline in `build.py` and
  `sources/youtube.py`. Both are thin orchestration over the source adapter;
  separate modules would have been indirection without a second caller.
- `sources/youtube_shorts.py` → Shorts are not a separate source, they are a
  post-hoc classification of a YouTube video (`classify_source` on duration).
  A second adapter would have duplicated the entire client for one boolean.
- **`apps/web/app/path/[id]/page.tsx` → genuinely missing.** Reel-import wrote to
  `learning_paths` and the API served `/api/paths/{id}`, but nothing rendered it,
  so the wedge feature's output was unreachable. Now built, server-rendered so the
  OG share card resolves — the share loop is the whole point of the feature and a
  client-only page gives crawlers nothing.

Worth recording that a file-by-file diff against the spec found this. It was
invisible from the test suite, which passed throughout: nothing tests that a
feature's output is reachable.

## D32 — Docker was a transient startup failure, not a proxy problem
Third and final correction on this. `http.docker.internal:3128` is Docker
Desktop's built-in transparent proxy — the default, not a misconfiguration, and
the settings store contains no proxy override at all. After Docker Desktop had
been running a while, `docker pull` simply worked. The earlier failures were the
daemon still coming up.

Lesson worth keeping: I asserted a cause twice on thin evidence before checking
the settings file. "Pull hangs" was the observation; "Docker Hub unreachable" and
then "misconfigured proxy" were both guesses stated as findings.

## D33 — All SQL now executed; one real data-loss bug found
With Postgres running, all 21 integration tests ran against real pgvector.
20 passed. One failed, and it was exactly the class of bug unit tests cannot see:

`VideoRow.credibility` defaulted to `0.5`, so a cheap metadata refresh sent a
concrete `0.5` rather than NULL. `COALESCE(EXCLUDED.credibility, ...)` therefore
saw a value and overwrote the stored score. **Every metadata refresh would have
silently reset an expensive LLM-computed credibility score back to neutral** —
invisible in production, and it would have quietly degraded Learn ranking over
time.

Fixed by defaulting the field to None so absence is real absence.

## D34 — Full pipeline verified on real captions end to end
`scripts/dry_run.py` runs real transcripts → sentences → moment detection →
embedding → Postgres → vector search, with the LLM stages stubbed and the offline
embedder. First run: 5/5 transcripts, 1854 sentences, 126 moments (4 junk
dropped), 126 vectors, ranking honouring the >=2-channel rule, 126 rows inserted
and a real vector-search hit.

This is the largest slice of the pipeline verifiable without API keys, and it
exercises repo.py under realistic data rather than hand-built rows.

## D35 — Whisper fallback: flagged off, audio deleted in a finally block
Stage 4's last resort. Two hard constraints, both from the doc:

1. **Audio is transient.** Downloaded to a temp dir, deleted in a `finally` so it
   goes away even on a crash mid-transcription. Only text and timestamps are
   stored. This is what keeps "embed, don't download" (B4) literally true — a
   transient decode is not hosting, but a leftover file on disk would be. Two
   tests assert the workdir is gone, including after an exception.
2. **Off unless `DEEPCLIP_WHISPER=1`.** ~15% of videos lack captions and it costs
   ~$0.006/min plus a GPU; paying for all of them implicitly would blow C8. There
   is also a duration cap, since a 3-hour stream is not worth transcribing.

The chain always tries free captions first and only reaches Whisper when they are
genuinely absent — asserted by a test that fails if Whisper is called when
captions exist.

## D36 — Pre-builder is resumable, budgeted, and loud about failures
C8's central bet is pre-building the top 5k pages. Three properties matter more
than speed:

- **Resumable** — progress lives in `deep_pages.status`, so a restart skips what
  is built rather than paying twice. A 5k-page run *will* be interrupted.
- **Budgeted** — stops on a dollar ceiling and on the YouTube quota, with a 500u
  safety margin so the run ends cleanly rather than mid-page.
- **Loud** — a page that fails silently is worse than one that never ran, because
  it looks built. Failures are recorded and reported.

Queries are deduped on their *normalised* form, since that is the cache key: two
queries normalising the same would otherwise build one page twice.

## D37 — Golden-pick tooling refuses to fake human judgement
`scripts/pick_golden.py` runs the real moment detector over real transcripts and
prints each candidate with text and a jump link, so building the golden set is a
short human job rather than a research project. It supports `--auto-top N` to
pre-populate.

Two guards, because the failure mode here is subtle and severe:

1. Auto-picks are written with `human_reviewed: false`.
2. **`eval/run.py` refuses to use unreviewed picks entirely.**

Without guard 2, auto-generated picks would score the ranker against its own
output — `overlap@k` would jump to something impressive and mean nothing. A
circular eval that reads as validated is strictly worse than no eval, because it
stops you looking. I generated a 29-pick file to test the tool, confirmed the
eval ignored it, and deleted it: a file named "golden picks" that is not golden
is a trap even with a flag on it.

Making these real still requires a human watching video. It is the single
highest-value thing standing between this project and knowing whether the
ranking is any good.

## D38 — Reel-import UI built, and the caption path was broken
Built `/import` — paste a clip, get a path. Per the demand research this is the
one part of the product that demonstrates in ten seconds, which is what a
short-form acquisition loop actually needs. The doc schedules it for "Months 4+";
the research argues that is backwards.

Building the UI immediately exposed a break in the existing backend: the API's
`ImportRequest` accepted only `url`, so `caption_text` was silently dropped.
Instagram and TikTok imports *require* that field — the backend raises without
it — so every non-YouTube import would have failed with a confusing error. Wired
`caption_text` and `confirmed_query` through UI → API → worker → `import_seed`.

## D39 — Platform-detection parity is enforced by test
Detection now exists in two languages: `ImportBox.tsx` decides whether to ask for
a caption, `reel_import.py` decides whether the import is legal without one. If
they drift, a user pastes a TikTok link, the UI never asks for a caption, and the
backend rejects it — a dead end with no visible cause.

`tests/test_platform_parity.py` parses the regexes out of the TSX and asserts
both sides classify the same URLs identically, and that the set of
caption-requiring platforms matches on both sides. Duplication across a language
boundary is sometimes right; unguarded duplication never is.

## D40 — Gemini support added; provider is now selectable
The user wants to run Gemini rather than Claude. The LLM seam already isolated
every model call behind one `complete()` method, so this touched only
`llm/client.py` and no pipeline stage.

- `GeminiClient` (google-genai) sits alongside `AnthropicClient`. Both satisfy
  the same `LLMClient` protocol.
- The pipeline still refers to two logical tiers, `MODEL_FAST`/`MODEL_SMART`.
  Each client maps those to its own model names, so the pipeline never hard-codes
  a provider's IDs. Gemini names are env-overridable (`GEMINI_MODEL_FAST/SMART`)
  because model names churn faster than code.
- `build_client()` selects by `LLM_PROVIDER`, else auto-detects from whichever
  key is present, **preferring Gemini** when both are — matching the user's
  choice.
- Gemini's `resp.text` raises on a safety block rather than returning None, so
  parsing wraps it and falls back to assembling candidate parts; a genuinely
  empty response raises `LLMError` into the existing retry/degradation paths.

Tested with an injected fake transport shaped like google-genai's response
objects — tier mapping, parsing, the blocked-response path, token accounting,
cost, retry, and provider selection. The only thing unexercised is the real
network call, which needs a key.

## D41 — Repo hygiene during first push
The first `git push` was rejected: a 109 MB Next.js binary was in early history
(committed before `.gitignore` existed, untracked later but still in history).
Scrubbed `node_modules`, `.next`, and `.pytest_cache` from all history with
git-filter-repo; `.git` went from 108 MB to 1.1 MB. Also untracked 46 committed
`.pyc` files. Backed up to a branch first, verified all tests still pass after the
rewrite, then pushed. All history preserved except the purged build artifacts.

## D42 — Analytics: the go/no-go metric is now measurable
The master doc's entire kill/scale decision (D4, D8) is "do users finish pages
and come back?" and nothing measured it. Built an append-only event log
end to end.

- `events` table + `EventRow` with a **closed** `EVENT_KINDS` set, so a client
  typo becomes a rejected event, not a silent hole in the metric.
- Repo aggregates compute the real numbers: `page_completion_rate` (over
  distinct sessions, so a reload cannot inflate it), `return_rate` (>=2 distinct
  active days — the company-vs-feature line), `clip_watch_depth` (where attention
  actually drops off, which "completion" alone hides), and `satisfaction`.
- `POST /api/events` is fire-and-forget: **always 202, never blocks or errors the
  client.** Invalid events are dropped, not 4xx'd, because a `sendBeacon` cannot
  read a response and retrying analytics is pointless. A DB failure returns
  `accepted: 0` rather than surfacing.
- Frontend `lib/analytics.ts` is anonymous (localStorage UUID, per-tab session),
  batched, and flushed with `sendBeacon` on `pagehide`/`visibilitychange` — the
  most important event (reaching the end) is the one most likely to be lost on
  unload, so it uses the one transport that survives it.
- Wired: `page_view`, `clip_view`, `clip_complete`, `page_complete` (Learn, via
  an intersection sentinel so it fires only on genuine arrival), `end_card`
  (Entertain — reaching the end is the anti-infinite-scroll signal), and a
  one-tap `satisfaction` control.

Every path degrades silently: analytics losing data is acceptable, analytics
breaking a page is not. 10 new DB aggregate tests, 9 API tests, verified against
real Postgres.

## D43 — Rate limiting on the paid endpoints
`/api/build` and `/api/import` both enqueue ~$1 of work, and were unthrottled —
one script could run up a bill or drain the YouTube quota for everyone. Both are
now capped (5 per 60s per client).

Two deliberate choices:
- **Limit only when work is actually paid.** A cache hit on `/api/build` is free,
  so the limit is checked *after* the cache lookup — a user reloading a built page
  is never rate-limited, only genuine new builds are.
- **Redis-backed when available, in-memory floor otherwise.** The in-memory
  limiter is per-process, so it is not correct across multiple API replicas; the
  Redis sorted-set limiter is. The API uses Redis when the queue connection
  exists and falls back to in-memory (never fails open silently). Client identity
  prefers `x-forwarded-for` for deployments behind a proxy.

## D44 — Report button (D6 day-one safety)
Per-clip report control on both renderers. On a "real footage, curated" product
the trust-killing failure is a wrong or misleading clip on contested history, so
a low-friction flag has to exist from day one — a reason picker, not a form.

A report writes a `report` event (the kind already existed) with the reason in
`meta`. `recent_reports` groups by (slug, video_id, position) and ranks by report
count, so a clip many people flag rises to the top of the review queue, exposed
at `GET /api/reports`. Reusing the event stream means reports are reviewable with
no separate table or pipeline.

## D45 — Real Gemini validation: model names were wrong, keys work
First real LLM calls, against the user's Gemini key. Findings:

- **The key authenticates and the stages work.** Stage 1 produced a strong
  6-chapter Gandhi Salt March outline and correctly classified "funny ishowspeed
  moments" as entertain with sensible groupings. Total cost $0.003 — much cheaper
  than the Claude-based C8 estimate.
- **My guessed model names were stale.** `gemini-2.5-flash`/`gemini-2.5-pro` were
  retired for new keys, and `gemini-pro-latest` is quota-blocked on the free tier
  (429). Switched defaults to `gemini-flash-latest` (smart) and
  `gemini-flash-lite-latest` (fast) — the `-latest` aliases are churn-proof, which
  is the whole reason the model names were made env-overridable.
- **Gemini 3 "thinking" can consume the whole output budget** on a small
  max_tokens, returning empty text. The pipeline's 2048–4096 budgets leave room,
  and `_gemini_text` already raises-then-retries on empty, so this degrades
  safely. flash-lite has negligible thinking overhead, which is why it is the
  bulk-scoring tier.

This is the fifth time this session that contact with reality corrected
something fakes had passed. The pattern is now the strongest evidence in the
project for running things for real early.

## D46 — Real end-to-end validation: the whole pipeline runs, and the transcript layer is the real risk
Ran full real builds (YouTube + Gemini + Gemini embeddings + Postgres). Findings,
in order of importance:

1. **The pipeline works end to end.** A real build went outline → 69 videos
   retrieved → 31 transcripts → moments from all 31 → embedding, entirely on real
   infra. Stage 1 and retrieval are validated against production APIs.

2. **The transcript layer is the single biggest reliability risk — confirmed
   live.** After the heavy first run, `youtube-transcript-api` started returning
   `IpBlocked` for every video: YouTube blocks the scraped caption endpoint under
   load. This is the B4 fragility made concrete, and it takes down the whole
   pipeline (no transcripts → no moments → no page). Mitigations added:
   - **Proxy support** (`YTT_PROXY_*` / `WEBSHARE_PROXY_*`) — what production
     transcript services actually use to avoid IP blocks.
   - A distinct `TranscriptIpBlocked` error so a block is not swallowed as "this
     video has no captions". The build stops early on a block and reports the real
     cause with the fix, instead of grinding through every video and failing with a
     misleading message.
   - The Whisper fallback (already built, flagged off) is the other escape hatch.
   The honest position: **for reliable production, this needs either residential
   proxies or Whisper — IP-based scraping alone will not hold.**

3. **Free-tier limits bind before cost does.** Gemini free-tier embedding
   request quota (429) and pro-model access (429) are the practical ceiling, not
   dollars. Handled with backoff + the cost caps in D45.

This is the sixth and most important time this session that running for real
changed the picture. Every one of these was invisible to the (passing) fake-backed
tests.

## D47 — 'Ask about this clip' tutor (B1)
Grounded Q&A on a single clip. The transcript is stored on each assembled clip
(cheap — it was already in the candidate) and read server-side from the persisted
page, so the answer is grounded in the exact curated moment and the client cannot
substitute a different transcript. Same anti-hallucination rule as assembly:
answer only from the transcript, and say "the clip doesn't cover that" rather than
reaching for outside knowledge — surfaced as a `grounded` flag so the not-covered
case is measurable.

## D48 — Whisper via yt-dlp audio bypasses the caption IP block (the unblock)
The transcript IP block (D46) looked fatal for live builds. It is not. Diagnosis:

- youtube-transcript-api and the caption content URLs both hit YouTube's
  `timedtext` endpoint, which is IP-rate-limited under load (429 / IpBlocked).
- **Audio downloads come from googlevideo.com — a different host that is NOT
  blocked.** Verified live: yt-dlp downloaded audio fast while captions 429'd.
- faster-whisper decodes the raw m4a directly (bundled PyAV, no system ffmpeg)
  and transcribed a real 20-min video in 20s on CPU with the `base` model, text
  correct.

So the Whisper fallback — already built, flagged off — is the escape hatch, and
it works with no GPU and no ffmpeg. Wired so `DEEPCLIP_WHISPER=1` makes an IP
block or missing captions fall through to Whisper automatically. The audio is
still deleted in a `finally` (B4), and the duration cap bounds cost.

Trade-off: Whisper is slow (~15-30s/video on CPU vs. instant captions), so a live
build takes minutes rather than seconds. For production the order should be
captions-first (fast, free) with Whisper only as the fallback — which is exactly
the chain implemented. Captions return once the IP block lifts.

This is the seventh time this session that running for real changed the outcome,
and the most consequential: it turns "live builds are blocked" into "live builds
work, slowly, today."

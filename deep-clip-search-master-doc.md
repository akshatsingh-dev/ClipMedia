# Deep Clip Search — Master Document (v3)

**This is the single source of truth.** It merges the original vision/GTM doc and the v2 technical spec, adds the new Entertainment Mode ("scroll with purpose"), and closes with an honest feasibility and business assessment.

**Audience:** Part A–B for humans/investors. Part C is the build spec for Claude Code. Part D is the verdict.

---
---

# PART A — VISION & PRODUCT

## A1. The One-Liner

A search engine that answers "show me X" not with generated text or a random algorithmic feed, but with a **curated, scrollable page of real video moments — jumped to the exact timestamp** — assembled by AI into a coherent journey.

Google gave you links. Perplexity gave you synthesized text. TikTok gave you an algorithm that guesses. We give you **the real footage itself, sequenced on purpose.**

Two modes, one engine:

- **Learn Mode** — "teach me everything about Gandhi" → a documentary-like Deep Page: chapters of a life, each told through the best real clips from YouTube, Shorts, and reels.
- **Entertain Mode** — "best funny Speed moments" → the engine understands intent, gathers the genuinely best clips of IShowSpeed being funny, and serves them in a scrolling feed. Same scroll, zero slot-machine. **You scroll with purpose.**

**The brand line: "Scroll with purpose."** Doomscrolling is what happens when an algorithm optimizes for your attention. This is what happens when an engine optimizes for your *intent*. Both modes are the same promise: you asked for something, the page ends, you got what you came for.

## A2. The Problem

Whether you want depth or entertainment, today's options fail the same way:

1. **Textbooks / Wikipedia** — dense, dry, no faces or voices, low retention for video-native learners.
2. **AI chatbots** — flat generated text. No primary footage, no archival material. Feels synthetic because it is.
3. **YouTube search** — the footage exists but is buried. A 45-minute documentary holds 4 relevant minutes; a 3-hour Speed stream holds 90 seconds of gold. You scrub and hope.
4. **Reels/TikTok** — if you like something, your only recourse is to *hope* the algorithm shows more. No way to say "go deeper," "in order," or "just the best of this."

**Core insight:** the world's best explanations AND funniest moments already exist on video. The missing layer is **retrieval at the moment level + sequencing at the intent level.** Nobody has built the index of moments.

## A3. Why Now

- Transcription is near-free (Whisper-class models make all spoken video searchable).
- Multimodal LLMs can verify what's on screen (archival footage vs. talking head; a laugh vs. a lecture).
- Long-context LLMs can sequence 200 candidate clips into a narrative or a comedy arc.
- Gen Z already starts searches on TikTok/YouTube instead of Google — the behavior exists; the intentional tool doesn't.
- AI-slop is flooding feeds. **"Only real footage, curated" is the differentiator.** We are the anti-slop engine — AI is the librarian and editor, never the actor.

## A4. The Product

### A4.1 Learn Mode: the Deep Page

Type *"Gandhi"* → a scrollable vertical page, part documentary, part feed:

- **AI-generated chapters:** Early Life in Porbandar → London → South Africa → Salt March → Partition → Assassination → Legacy.
- Each chapter: **embedded YouTube players pre-seeked to exact timestamps** — 3 minutes of a 90-minute documentary, 40 seconds of a lecture, a Short from a history creator.
- **Connective text (2–3 sentences max)** bridges clips; it may contextualize, never replace the footage.
- Every clip credits the creator, links to the full video, shows the timestamp range. We drive real views to originals.

The feel: you scroll like Instagram, but you come out the other end understanding a life.

### A4.2 Entertain Mode: purposeful entertainment

Type *"funny Speed clips"*, *"best Messi solo goals"*, *"wildest MrBeast moments"* → the engine parses intent (subject + vibe), retrieves candidate videos and Shorts, finds the *moments* (not whole videos), ranks them on actual moment-level signals (reaction cues in transcript/audio, view velocity, clip density), and serves a scrolling feed of embedded timestamped clips.

Differences from Learn Mode are ranking weights and page shape, not architecture:
- No chapters — a ranked flow with optional groupings ("Speed × soccer," "Speed × streams gone wrong").
- Ranking optimizes *moment intensity* (laughter, shock, spectacle) instead of explanation quality.
- Auto-advance defaults ON (lean-back), but the feed still **ends** — "You've seen the best 25. Want a different vibe?"

Why this matters for marketing: Learn Mode is the moat and the mission; Entertain Mode is the *hook*. "Best funny Speed clips, zero scrubbing" is a 10-second demo any teenager immediately gets — and it onboards the exact audience Learn Mode serves before an exam.

### A4.3 The killer loop: "Teach me more like this" (reel import)

Paste a reel/Short you loved (Stoicism, Kriya Yoga, fall of Constantinople, or a Speed clip):
1. We analyze it (transcript/caption → topic, sub-topic, depth level or vibe).
2. We generate a **path** of real timestamped clips that goes progressively deeper (Learn) or serves more of the same vibe, ranked (Entertain).

This converts the most common frustrated behavior on social platforms — "I loved this, and the algorithm just shows me repetitive junk" — into an intentional action. It's the wedge feature: shareable, demo-able in 15 seconds, and incumbents can't copy it without fighting their own engagement model.

### A4.4 What we deliberately don't do

- **No AI-generated video or voice. Ever.** Real footage only.
- **No infinite feed.** Pages and feeds end. Completion is the goal, not session time. This is brand, trust, and the entire marketing position.

---
---

# PART B — MARKET & COMPETITIVE RESEARCH (July 2026)

## B1. Direct-adjacent products (learning)

**LearnPath (learnwithpath.com)** — closest in spirit. Curates free YouTube videos into structured learning paths with adaptive quizzes and branching. Their published pipeline is worth copying at the retrieval layer: they query the YouTube Data API with terms derived from topic/level/goals, then pull each candidate's full transcript — manual captions first, then auto-captions, then description as last resort — and treat the transcript as the primary ranking input, because titles/descriptions are SEO-written while transcripts reveal what a video actually teaches. **Steal:** transcript-first evaluation + caption fallback chain. **Their gap:** whole videos, not timestamped moments; skills (Python, guitar), not people/narrative; no short-form.

**LearnLens Studio (studio.learnerslens.ai)** — validates the moment thesis. They segment videos into bite-sized pieces, trim intros to keep "only the teaching moments," rank teachers by explanation clarity rather than views, and curate the single best explanation per concept across creators — arguing speaker-switching triggers the brain's orienting reflex and maintains focus. **Steal:** best-explanation-per-concept as the ranking objective; enforced speaker variety; learning-science framing for marketing. **Gap:** courses, not narrative Deep Pages; no reel-import; no entertainment.

**Pathio (pathio.ai)** — AI-curated path for any topic with a context-aware tutor that answers based on what you're currently watching. **Steal:** the "ask about this clip" tutor — nearly free for us since the transcript segment is already in context. **Gap:** whole videos, no timestamps.

## B2. Moment-search infrastructure (technique donors)

- **VidNavigator** — semantic YouTube search with jump-to-timestamp results, whole-channel indexing, AI answers with timestamped evidence, LLM-ready JSON. **Steal:** proactive channel-level batch indexing of trusted channels; the `answer + [video_id, t_start, t_end, evidence]` response shape.
- **Twelve Labs** — serious multimodal video-understanding API (visual + audio + language in one embedding). **Decision:** don't build multimodal embeddings in v1; transcript embeddings get ~90% there. Evaluate their API before ever building vision embeddings ourselves.
- **Moments Lab** — raised $24M for AI video indexing sold B2B to Reuters, Hearst, Sinclair, Amazon Ads. Proves the moment-index has enterprise value; consumer is untouched.
- **Google "Key Moments"** — Google already uses AI to deep-link key moments in search results, but only *within one video per result*. They stopped one step short of cross-video synthesis — and their ad/watch-time incentives explain why.
- **Choppity / WayinVideo / Memories.ai** — creator-tool moment finders (keyword → scored moments in one video). **Steal:** per-moment relevancy scores surfaced in internal debug tooling.

## B3. The open gap

Nobody combines: **moment-level retrieval** (infra players have it) × **path sequencing** (LearnPath/LearnLens have it) × **narrative pages for people/history** (nobody) × **short-form + reel-import loop** (nobody) × **intent-driven entertainment feeds** (nobody — the entertainment incumbents are algorithmic by design). We're not first to "AI + YouTube learning"; we're first to *timestamped, intent-driven synthesis across long-form and short-form.*

## B4. Data-source legal reality

| Source | Discovery at scale | Transcript | Playback | Verdict |
|---|---|---|---|---|
| YouTube long-form | ✅ Data API v3 `search.list` | captions → Whisper | iframe embed `?start=&end=` | **Primary** |
| YouTube Shorts | ✅ Data API (post-hoc filter) | same | iframe embed | **Primary** |
| Instagram Reels | ❌ no public search API | ❌ | oEmbed display only | **Inbound-only** (user-pasted links) |
| TikTok | ❌ Research API = academia only | ❌ | oEmbed | **Inbound-only, post-MVP** |

Key constraints found: Meta's Graph API returns data only for Business/Creator accounts you own; you cannot fetch arbitrary public content. The Instagram oEmbed endpoint is restricted to front-end display — using its metadata or content derivations for any other purpose is explicitly prohibited. Third-party scraper APIs (Apify, SociaVault, Data365) exist but violate Meta's ToS even when the provider absorbs infrastructure risk.

**Architecture consequence:** all *outbound* discovery and indexing is YouTube-only (official API + official embeds). Instagram/TikTok enter only as **user-pasted links** (feature A4.3), rendered via official oEmbed, analyzed only from user-initiated input and public caption text. Ingestion is built behind a `SourceAdapter` interface so Vimeo, archive.org, and podcast video can be added later.

**Embed, don't download — the load-bearing decision.** Clips play via YouTube's official iframe with `start`/`end` parameters. We never host, re-upload, or cut video files. This keeps us inside ToS, sends views and watch time to creators (our political shield), and kills the copyright problem that ended every prior "video remix" startup. Our IP is the **moment index and the sequencing intelligence**, never the footage.

---
---

# PART C — TECHNICAL SPECIFICATION (build spec for Claude Code)

## C1. Architecture

```
                        ┌──────────────────────────────┐
                        │        Next.js frontend       │
                        │ /q/[query] /path/[id] /e/[q]  │
                        └──────────┬───────────────────┘
                                   │ REST + SSE
                        ┌──────────▼───────────────────┐
                        │      FastAPI gateway          │
                        │ /api/deep-page /api/feed      │
                        │ /api/import                   │
                        └──────┬───────────────┬───────┘
                     cache hit │               │ miss → enqueue
                        ┌──────▼─────┐   ┌────▼──────────────────┐
                        │  Postgres   │   │ Worker pool (arq/Redis)│
                        │  + pgvector │   │ pipeline stages 1–8    │
                        └──────▲─────┘   └────┬──────────────────┘
                               └──────────────┘
        External: YouTube Data API v3 · caption fetch · faster-whisper (GPU) ·
                  Anthropic API · IG/TikTok oEmbed
```

**Stack (final decisions):**
- **Frontend:** Next.js 14 (App Router) + Tailwind. SSR for cached pages (every Deep Page is an SEO-indexable landing page). SSE streaming for live builds.
- **API:** FastAPI (keep everything Python — the pipeline is Python).
- **DB:** Postgres 16 + pgvector (HNSW). One database; no dedicated vector DB until >5M segments.
- **Queue:** arq (Redis, asyncio-native).
- **Transcription:** `youtube-transcript-api` first (lists per-video tracks, exposes manual vs. auto-generated, prefers manual by default). Fallback: `faster-whisper large-v3` on rented GPU — audio downloaded only for transcription, deleted immediately after; only text + timestamps stored.
- **LLM:** Claude API. Haiku-class for bulk classification; Sonnet-class for outline, final ranking, and assembly.
- **Embeddings:** benchmark an open model (e.g., bge-m3) vs. a hosted small embedding model on a 200-query eval set; ≤1024 dims.

## C2. Data model (Postgres)

```sql
CREATE TABLE videos (
  id            TEXT PRIMARY KEY,          -- yt video id / ig shortcode
  source        TEXT NOT NULL,             -- 'youtube'|'youtube_shorts'|'instagram'|'tiktok'
  title         TEXT, channel_id TEXT, channel_name TEXT,
  duration_s    INT, published_at TIMESTAMPTZ,
  view_count    BIGINT, like_count BIGINT,
  transcript_kind TEXT,                    -- 'manual'|'auto'|'whisper'|NULL
  lang          TEXT,
  credibility   REAL DEFAULT 0.5,          -- channel-level (Learn Mode)
  ingested_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE segments (
  id          BIGSERIAL PRIMARY KEY,
  video_id    TEXT REFERENCES videos(id),
  t_start     REAL NOT NULL, t_end REAL NOT NULL,
  text        TEXT NOT NULL,
  embedding   VECTOR(1024),
  vis_tags    JSONB,                       -- {'archival':0.9,...} (post-MVP)
  quality     REAL,                        -- explanation-quality 0–1 (Learn)
  intensity   REAL                         -- moment-intensity 0–1 (Entertain)
);
CREATE INDEX ON segments USING hnsw (embedding vector_cosine_ops);

CREATE TABLE deep_pages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  query_norm  TEXT UNIQUE,
  mode        TEXT NOT NULL DEFAULT 'learn',  -- 'learn'|'entertain'
  outline     JSONB,
  page        JSONB,
  status      TEXT,                           -- 'building'|'ready'|'failed'
  built_at    TIMESTAMPTZ, build_cost_usd REAL
);

CREATE TABLE learning_paths (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seed_url    TEXT, seed_analysis JSONB,      -- topic/subtopic/depth or vibe
  page        JSONB, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE hint_cache (                     -- quota protection
  hint TEXT PRIMARY KEY, video_ids TEXT[], fetched_at TIMESTAMPTZ
);
```

Segmentation rule: semantic boundaries, 30–90s target, 15s overlap, sentence-aligned from caption timings; merge fragments <10s.

## C3. Pipeline stages (composable async worker functions)

### Stage 1 — Intent + outline
Normalize query → Sonnet call classifies `mode` and produces the plan.

Learn output:
```json
{"mode":"learn","entity_type":"person","chapters":[
  {"title":"Early Life in Porbandar",
   "search_hints":["Gandhi childhood Porbandar","Gandhi early life"],
   "coverage_goals":["birth 1869","family","marriage at 13"]}]}
```
Entertain output:
```json
{"mode":"entertain","subject":"IShowSpeed","vibe":"funny",
 "search_hints":["IShowSpeed funniest moments","Speed funny clips",
                 "IShowSpeed stream highlights #shorts"],
 "groupings":["soccer","streams","IRL"]}
```
6–10 chapters for a life; 4–8 concept nodes for a topic; 3–5 groupings for entertainment.

### Stage 2 — Candidate retrieval (YouTube)
Per hint: `search.list` `part=snippet&type=video&maxResults=25&videoEmbeddable=true&relevanceLanguage=en`.
**Quota math is the binding constraint:** `search.list` = 100 units of the default 10k/day. An 8-chapter Learn page ≈ 1,600 units of search. Mitigations, all mandatory: (a) file for quota increase week 1; (b) check `hint_cache` (30-day TTL) before any search; (c) `videos.list` batched 50 ids/call (1 unit) for metadata.

### Stage 3 — Shorts handling
No Shorts filter exists in the API. Detect post-hoc: `duration_s <= 180` (+ vertical when player metadata reveals it) → `source='youtube_shorts'`; additionally run hint variants with `#shorts` appended. Learn Mode slots Shorts as chapter *openers* (hook, not substance). Entertain Mode treats Shorts as first-class — often the best candidates, since creators have already clipped the moment.

### Stage 4 — Transcript ingestion
Fallback chain: manual captions → auto captions → Whisper on ephemeral audio → skip. Record `transcript_kind` (manual > auto > whisper as ranking prior — auto-captions mangle names: "Jinnah" → "gina"). Run a cheap LLM name-repair pass on auto/whisper text using the outline's entity list *before* embedding. For Entertain Mode also preserve non-speech caption cues (`[laughter]`, `[screaming]`, `[music]`) — they are intensity features, not noise.

### Stage 5 — Segmentation, embedding, scoring
Segment → embed → batched Haiku scoring per video:
- `quality` (Learn): is this substantive explanation vs. intro/ad/banter/outro? (removes ~40% junk pre-ranking)
- `intensity` (Entertain): reaction density — laughter/shock cues in text and non-speech tags, exclamation cadence, named-event spectacle. Score 0–1.

### Stage 6 — Ranking
**Learn (per chapter, per coverage_goal):** vector top-50 →
```
score = 0.40·cosine + 0.20·quality + 0.15·channel_credibility
      + 0.10·transcript_kind_prior + 0.10·visual_richness(0 in v1)
      + 0.05·recency_or_archival
      − drop if cosine>0.85 vs any already-selected segment
```
2–4 segments/chapter; **hard constraint: ≥2 distinct channels per chapter** (LearnLens speaker-switching).

**Entertain (per grouping):**
```
score = 0.35·cosine(vibe query) + 0.30·intensity
      + 0.20·engagement_velocity            -- views/day since publish, log-scaled
      + 0.10·clip_density                   -- Shorts & compilations rank up
      + 0.05·recency
      − same redundancy drop; also drop near-duplicate reuploads
        (title-similarity + duration match heuristic)
```
20–30 clips per feed, interleaved across groupings, best-first.

### Stage 7 — Assembly
Sonnet call with selected segments → final page JSON. Learn: verify chapter order, write 2–3 sentence bridges (hard prompt rule: bridges may contextualize, never introduce facts absent from clips), snap `t_start` back to nearest sentence boundary, per-clip credit + "why this clip." Entertain: order for pacing (open strong, vary subjects, close strongest), one-line captions max, end-card copy.

### Stage 8 — Vision pass (post-MVP, feature-flagged)
Final-round candidates only (≤200 segments/page): sample storyboard frames, batch Claude vision → `vis_tags` (archival/map/reenactment/talking_head for Learn; face_reaction/action for Entertain). Bounded cost.

### Reel-import pipeline (feature A4.3)
1. Resolve pasted URL platform. YouTube/Shorts → full pipeline access. Instagram → oEmbed embed HTML only (display), never download media.
2. Analysis: YT → stage-4 transcript. IG → Sonnet infers topic candidates from public caption/title text only, user confirms via one tap.
3. Classify `{topic, subtopic, depth_level | vibe, style}`.
4. Learn seed → progression outline from depth_level+1, run stages 2–7 on the YouTube corpus. Entertain seed → vibe feed via entertain ranking.
5. Output row in `learning_paths` → same renderer. Generate OG share card: "From 1 reel → the full picture of {topic}."

## C4. Credibility scoring (Learn Mode, channel-level, lazy)
Haiku per new channel: metadata + 3 sampled transcripts → 0–1 on educational intent, sourcing signals (spoken dates/names/citations), sensationalism (inverse). Seed allowlist ~100 channels (documentary/university/established history creators) pinned ≥0.9. Contested chapters (flagged in stage 1) must include ≥2 channels ≥0.7 credibility with differing framing, bridge text noting the disagreement.

## C5. Frontend spec
Page JSON render tree (Learn):
```json
{"title":"Mahatma Gandhi","mode":"learn","chapters":[
  {"title":"...","intro_text":"...",
   "clips":[{"video_id":"abc","t_start":312,"t_end":495,
             "channel":"...","video_title":"...","credit_url":"...",
             "why":"Best archival footage of the 1930 march"}]}]}
```
Entertain uses `{"groups":[{"label":"soccer","clips":[...]}]}` with the same clip shape.

- Playback: YouTube IFrame Player API, `start`/`end`, `enablejsapi=1`. **Lazy-mount** players (thumbnail façade until scroll-into-view) — mandatory on 20-iframe pages.
- Auto-advance: `onStateChange→ENDED` scrolls to and plays next clip. Default OFF in Learn, ON in Entertain. Feeds end with an end-card, never infinite.
- Instagram clips (import paths only): render oEmbed HTML unmodified, no seeking (unsupported), full attribution.
- Live-build UX: SSE progress stream — outline renders in ~5s, chapters/groups fill as ranked. Perceived latency ≈5s even at 60s full build.
- Every clip: creator name + link to original. Non-negotiable (ToS posture + creator goodwill).

## C6. Repo structure & build order

```
deepclip/
├── apps/web/                 # Next.js
│   ├── app/q/[slug]/page.tsx        # learn
│   ├── app/e/[slug]/page.tsx        # entertain
│   ├── app/path/[id]/page.tsx       # imported paths
│   └── components/{ClipPlayer,ChapterSection,FeedSection,BuildStream}.tsx
├── services/api/             # FastAPI: routes/{pages,feed,paths,import}.py, sse.py
├── services/worker/
│   ├── pipeline/{outline,retrieve,transcripts,segment,rank_learn,rank_entertain,assemble,vision}.py
│   ├── sources/{base.py,youtube.py,youtube_shorts.py,instagram.py}   # SourceAdapter ABC
│   └── llm/{prompts/,client.py}
├── packages/db/{schema.sql,migrations/}
├── eval/
└── docker-compose.yml        # postgres+pgvector, redis, api, worker
```

Build order:
1. `packages/db` schema + docker-compose.
2. `sources/youtube.py`: search + metadata + transcript fallback chain. Test on 5 hardcoded hints.
3. `segment.py` + embeddings into pgvector.
4. `outline.py` + `rank_learn.py` + `assemble.py` against the golden-page eval (C7).
5. FastAPI + SSE.
6. Frontend Learn renderer, lazy iframes.
7. `rank_entertain.py` + `/e/` route (reuses stages 1–5 wholesale).
8. Reel-import (YouTube seed first, IG oEmbed after).

**First command for Claude Code:** scaffold per above, implement steps 1–2, output ranked-segment JSON for "Mahatma Gandhi Salt March" as the first integration test.

## C7. Evaluation harness (build BEFORE tuning ranking)
- **Golden pages:** hand-curate Gandhi, MLK, Stoicism (Learn) + "funny Speed clips" (Entertain) — human-picked timestamps. Metrics: coverage recall vs. goals, clip overlap@k with golden picks, redundancy rate, junk rate.
- **LLM judge:** Sonnet grades each generated chapter/group 1–5 on coverage/coherence/clip quality against transcript evidence. Tracked per-commit in `eval/results/`.
- **Ship gate:** ≥80% of golden judge score on all four before public launch.

## C8. Cost model (per uncached page, order of magnitude)
- YouTube quota: ~1.6k units search + ~50 units metadata (free-tier *constraint*, not dollars).
- Transcripts: $0 for ~85% (captions); Whisper ≈ $0.006/min for the rest.
- Embeddings ~2k segments ≈ $0.03. Haiku scoring ≈ $0.10. Sonnet outline+rank+assemble ≈ $0.40.
- **≈ $0.60–1.00 per page, once. Cached serves ≈ $0.** Pre-building the top 5k pages ≈ $4–5k — that spend IS the seed of the moat.

---
---

# PART D — GO-TO-MARKET, BUSINESS, AND THE HONEST VERDICT

## D1. Positioning
*"Perplexity made the internet's text answerable. We make the internet's video intentional."*
Consumer line: **"Scroll with purpose."**

## D2. GTM sequence
1. **Weeks 1–12 — history/philosophy internet + one entertainment wedge.** Seed 50 gorgeous Learn pages AND ~20 Entertain feeds for massive-fandom creators (Speed, MrBeast, Ronaldo/Messi). Post the *experience* ("I learned Gandhi's whole life in 12 min" / "every legendary Speed moment, zero scrubbing") to Reels/TikTok/X. Target history meme accounts, philosophy creators, AP/UPSC student communities, and creator fandoms.
2. **Months 3–6 — students.** Exam-aligned pages (AP/IB History, intro philosophy, Indian competitive exams). Campus ambassadors: UCSD + the Stanford BASES network are the first two campuses.
3. **Months 4+ — the import loop.** Reel-import turns every social platform into an acquisition channel; share cards send paths back out.

## D3. Business model
- Free core (index grows on volume).
- Pro $6–10/mo: unlimited long-tail generation, saved paths, export notes, auto spaced-repetition cards from watched clips.
- B2B/education: curriculum-aligned page packs for schools/test-prep.
- **Never:** ads inside the flow; AI-generated content. Both would destroy the brand's entire premise.

## D4. Metrics
Page/feed **completion rate** (the anti-watch-time north star) · "got what I came for" one-tap rating · click-throughs to full videos (creator value = our license to exist) · imports per user + paths shared (viral loop) · time-to-page <60s uncached · weekly return rate.

## D5. Moats (honest)
1. **The moment index** — compounding; every query leaves behind processed, scored, embedded video. Query #10,000 is free and instant.
2. **Sequencing taste** — narrative/pacing quality is a hard eval-and-prompt problem; months of iteration to match.
3. **Creator flywheel** — if we drive measurable referral views, creators structure content *for* us (as SEO was to Google).
4. **Brand: real footage, purposeful, no slop** — incumbents can't credibly copy it.
Not a moat: the pipeline (replicable in a weekend). Speed + index + brand are the defense.

## D6. Risks
- **YouTube quota** — #1 MVP risk. Increase request week 1; hint-cache; pre-build.
- **Platform dependence** — mitigated by strict ToS compliance, provable referral value, source diversification later (Vimeo, archive.org, lectures, podcasts).
- **Meta ToS** — never crawl IG; oEmbed display-only; analysis only on user-initiated links + public caption text.
- **Wrong/misleading clip on contested history** — credibility scoring, multi-perspective rule, report button day one.
- **Entertain Mode brand tension** — if the feed ever feels like another slot machine, the brand dies. The "feed ends" rule is inviolable.
- **"Feature, not company"** — the honest bear case; retention is the only rebuttal. So retention is what the MVP must prove.

## D7. Is it technically possible? — **Yes, with two hard parts.**

Every component is individually proven in production by someone today: transcript-first curation of YouTube at scale (LearnPath runs this pipeline publicly), moment-level semantic search with timestamp jumping (VidNavigator, Twelve Labs, Moments Lab — the last raised $24M doing it B2B), AI key-moment detection (Google ships it in Search), and timestamped iframe embedding (official YouTube feature). Nothing here requires research-grade breakthroughs — it's integration engineering plus taste.

The two genuinely hard parts:
1. **Ranking taste.** "Technically retrieves relevant segments" and "feels like a great documentary editor chose these" are far apart. This is why the golden-page eval harness (C7) is built before ranking is tuned, and why the founder hand-curates the first pages personally. Expect this to consume most iteration time. It is also, conveniently, the moat.
2. **The quota/cost wall at scale.** Solvable (caching, pre-building, quota increases, eventually YouTube partnership), but it shapes the architecture from day one, which is why it's baked into every stage above.

Everything else — the pipeline, the app, the import loop — is a competent 6–10 week build for one strong engineer plus Claude Code.

## D8. Is it worth building? — **Yes, conditionally. Here is the honest read.**

**The bull case (real):**
- The gap is genuine. Learning-path products recommend whole videos; moment-search products sell B2B infrastructure; nobody does timestamped narrative synthesis for consumers, and nobody touches intent-driven entertainment. Google/YouTube structurally *can't* follow — a product that ends your session and skips 90% of each video fights their entire revenue model. That's the best kind of incumbent protection: not that they can't build it, but that they won't want to until it's too late (at which point acquisition is the rational move for them).
- The timing tailwinds (cheap transcription, long-context sequencing, anti-slop sentiment, Gen Z video-native search behavior) are all real and all recent.
- The cost structure works: ~$1/page once, ~$0 cached, and the spend compounds into the index.

**The bear case (also real — don't look away from it):**
- **Crowded adjacency.** LearnPath, LearnLens, Pathio and a dozen others exist; adding timestamps is on their roadmap eventually. The defensible position is the vertical (people/history/narrative) + the import loop + moving fast, not the tech.
- **Consumer distribution is brutal.** The graveyard of "better than the algorithm" products is large. The product can be excellent and still die of no-distribution. The share-card loop and exam-season use case are the plan, but this is the highest-variance risk — higher than anything technical.
- **Entertain Mode competes with the strongest habit loops ever engineered.** "Purposeful scrolling" vs. TikTok is a values pitch; values pitches convert slower than dopamine. Treat Entertain as a *marketing hook and demo*, not the core bet — the moment it becomes the main product, you're in a knife fight with ByteDance and losing.
- **Platform risk is permanent.** YouTube tolerance is probable (you drive them views) but never guaranteed.

**Verdict:** worth building **as a wedge, with a kill/scale criterion.** Build Learn Mode for the people/history vertical first — it's the defensible gap, the exam-driven use case gives distribution a seasonal engine, and it's where "real footage, sequenced" is 10x better than every alternative. Use Entertain feeds as marketing artillery, not the product. Then let one number decide everything: **do users finish pages and come back the following week?** If W1 retention on the golden pages beats ~25–30% among students in exam season, this is a company and the acquisition narrative (YouTube buying the company that indexed its own content at the moment level) writes itself. If completion is high but return is low, it's a feature — sell the index B2B (Moments Lab's $24M shows that market exists) and you've still built something valuable.

And on acquisition as the goal: keep it as the *outcome*, never the *strategy*. Companies built to be bought build defensively and die. Build the thing students open every night before an exam; acquirers find those.

---

**Next three concrete actions (unchanged, now with one addition):**
1. Hand-build ONE Deep Page (Gandhi) manually — you picking timestamps — to define "great" before any code. It becomes the eval standard.
2. Hand-build ONE Entertain feed ("funny Speed clips") the same way — it defines the intensity ranking target and doubles as your first marketing post.
3. Run the pipeline against both; ship when the AI hits 80% of your hand-made versions with 10 real Gen Z users finishing the pages.

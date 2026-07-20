# Research findings — 2026-07-20

Two parallel research passes: defensible moat, and real demand. Both came back
with findings that contradict load-bearing assumptions in the master doc.

**These are research outputs, not verdicts.** Several are legal/strategic claims
that should be verified directly before acting. Sources are linked throughout so
they can be checked.

---

## Part 1 — Moat

### The finding that reframes the architecture

The YouTube API Services Developer Policies appear to directly attack the
"moment index compounds forever" thesis (master doc D5, moat #1):

- **30-day storage cap.** Developers may store Authorized Data "for no longer
  than 30 calendar days"; stored API data must be deleted or refreshed on that
  cycle. A permanent proprietary index of YouTube-derived data may not be a
  compliant asset.
- **No derived metrics.** Clients "must not... access or use [API Data] to
  create new or derived data or metrics." Our `quality`, `intensity`, and
  `credibility` columns sit squarely under this clause.
- **No cross-channel aggregation.** Aggregates may only span one content owner's
  channels and "must only be viewable by that content owner." This appears to
  prohibit the creator-analytics flywheel (moat #3) as designed.
- **Transcripts are scraped, not API.** There is no official transcript API;
  `youtube-transcript-api` hits undocumented caption endpoints. ToS §5.B bans
  automated access without written permission. **This is the library our stage-4
  pipeline depends on.**

Source: https://developers.google.com/youtube/terms/developer-policies

**Implication if accurate:** the C8 plan to pre-build 5,000 pages for $4–5k as
"the seed of the moat" would be building a liability that grows with success,
not equity.

### The incumbent-reluctance thesis is falsified

Master doc D8 argues Google "structurally can't follow" because it fights their
watch-time model. **They shipped it.** "Ask YouTube" — conversational search
returning an AI summary plus *a primary cited video linked to a timestamped
section*, with galleries of longform and Shorts. Reported >20M users/month on
the Ask tool as of December, now rolling onto TVs.

- https://www.searchenginejournal.com/google-tests-ask-youtube-conversational-search-experiment/573175/
- https://ppc.land/youtubes-q1-2026-tv-update-brings-ai-search-and-family-controls-to-smart-tvs/

They gated it behind Premium, which *aligns* it with revenue rather than fighting
it. The remaining gap is narrower than the doc assumes: cross-video sequencing
into a finished page. That is a product-shape gap, not a capability gap.

### Per-moment engagement data is not the asset it looks like

YouTube already computes **Most Replayed** — every video sliced into 100
segments with normalized per-segment view counts, continuously updated, across
the whole corpus. It captures completion, rewind, skip. It is also scrapeable
today.

a16z's "Empty Promise of Data Moats" is the general case: early data points carry
most of the signal, later ones add noise. **Waze is the exception that proves the
rule** — its data was perishable within minutes, so a competitor's snapshot went
stale immediately. Clip-quality data is the opposite: "this is the best 40
seconds on the Salt March" stays true next year. Durable data is copyable data.

The one real asymmetry: **intent-conditioned** satisfaction — not "was this
replayed" but "did this satisfy *this query*." Google's heatmaps are
query-agnostic. Worth instrumenting from day one (nearly free), not worth
pitching as a moat until there is query volume.

### The closest precedent is a loss

**Genius v. Google.** Same shape: add a valuable interpretive layer on top of
content you do not own, index it, watch the platform absorb the layer, discover
you have no standing because you never owned the underlying rights. Genius lost
on copyright preemption — it only licensed the lyrics. Click-through reportedly
fell up to 70%.

**Moments Lab is the encouraging counter-example**, and note *why*: it does not
index someone else's public corpus. It indexes archives its customers own, under
contract. The moat is the contract, not the model.

### Ranked candidate moats

1. **Off-YouTube rights-cleared corpus in one vertical** (12–24 months to
   replicate). University lecture archives, regional broadcaster morgues, museum
   oral histories. What prevents copying is not exclusivity — commercial archives
   are structurally anti-exclusive — but relationship latency and unglamorous
   clearance work. Cheap start: Prelinger Archives, ~8,500 public-domain films,
   free to reuse, zero ToS risk, and no YouTube-only competitor has segmented them.
2. **Institutional / curriculum embedding** (12–18 months per account, zero-sum).
   The doc buries this as the consolation prize in D8. It may be the most
   defensible item in the whole document.
3. **A human editorial judgment corpus** (6–12 months of labeling). This is
   "sequencing taste" reformulated into an actual asset: thousands of pairwise
   judgments, versioned and private. Taste in a founder's head is not a moat; a
   labeled corpus is. **This is what our C7 eval harness becomes if we keep going
   past four golden pages.**
4. **Owned audience / habit.** Real but slow — and the SEO channel behind it is
   decaying: ~69% of Google queries are now zero-click, ~83% for AI Overview
   queries.
5. *(deferred)* Intent-conditioned satisfaction data.
6. **The moment index — rejected.** 2–6 weeks to replicate, plus the policy
   exposure above.
7. **Creator analytics flywheel — rejected.** Prohibited as designed,
   commoditized where legal (VidIQ, TubeBuddy lock in nobody), defeated by
   multihoming. Referral traffic is a political shield, not a moat. Keep it,
   reclassify it.

---

## Part 2 — Demand

### Method limitation, stated honestly

**Reddit was completely inaccessible** — blocked at the network layer for this
user agent, across every route tried. The agent declined to fabricate quotes or
upvote counts to fill the gap. So the Reddit dimension of this research is an
open task requiring a human with a browser.

What was reachable turned out to be more decisive anyway, because it contains
the graveyard.

### A five-year graveyard

Every "search inside video" launch on Hacker News:

| Post | Date | Points |
|---|---|---|
| Search inside YouTube videos using natural language | 2021-02 | 264 |
| TLDW – Search inside videos | 2020-09 | 90 |
| Remy – AI-Curated Video Playlists on Any Topic | 2024-11 | **6** |
| YouTube In-Video Transcript Search | 2021-03 | **5** |
| WatchLess – timestamped answers | 2026-05 | **2** |
| Chrome extension to search lengthy YouTube videos | 2024-11 | **2** |
| Matriq – Search inside video files | 2026-01 | **3** |

**Remy (2024) is nearly our Learn Mode** — AI-curated playlists by topic,
transcript-based, cached, iframe-compliant. Six points, no momentum. On Product
Hunt, **JumprAI** already ships our Entertain one-liner: *"describe what you want
('funniest moment') and jump straight there instead of scrubbing."*

The risk is not that distribution is hard. It is that **this specific product has
repeatedly failed to find distribution when built by competent people.**

### The nearest competitor validates the pitch and shows the ceiling

**TLDW → LongCut.ai**, Zara Zhang (ex-GGV Capital, real audience), Oct 2025.
Her launch copy is our doc almost verbatim: *"You don't need a generic text
summary of a 1-hour video. You need the 5 minutes that actually change how you
think."* Got mainstream tech press.

After ~9 months, the public evidence of traction is *"many users said this is the
tool they've been waiting for."* **No numbers.** That is the "feature, not
company" failure mode (D6) observed in the wild on our nearest neighbour.

Her product is **single-video** navigation. Cross-video synthesis remains
genuinely unbuilt — our real gap, confirmed by absence rather than by demand.

### The segment that actually pays is not in the doc

**Content creators and clippers.** OpusClip: **$1M ARR in 14 days**, 10M+ users,
172M+ clips, ~$10–20M ARR, $36.8M raised. People pay for "find the good moments"
immediately and repeatedly.

The gap OpusClip leaves is precisely ours: **it clips video you already own.
Nobody does "find me the best real moments of X across all of YouTube."** That is
a compilation editor's manual workflow.

Versus exam students: UPSC/AP guidance content consistently frames YouTube as the
*problem* ("video lectures promote passive learning"), advises capping it, and the
segment is low-ARPU, seasonal, and owned by entrenched incumbents.

### "Scroll with purpose" is brand copy, not an acquisition hook

- Digital wellness apps: **~7.9% 30-day retention.** Calm and Headspace don't
  clear 8.5%. Opal has 4M+ downloads and reviews conclude software alone isn't enough.
- HN's anti-doomscroll "touch grass" app: **1,203 points, 268 comments** — and
  reading the thread, essentially all jokes. Not one commenter said they
  installed it. Two other doomscrolling threads: 343 and 351 points. Massive
  commiseration, no adoption.

Keep it as what people say about you after they show up for a selfish reason.
Never make it the reason they show up.

### Entertain Mode may be dead on arrival as a product

Compilation channels already solve it, free, with human pacing: Daily Dose of
Internet (20M subs), The Pet Collective (9.25M), Kyoot (5.87M), Ozzy Man (5M+).
"Best funny Speed moments" returns a good hand-made compilation today, instantly.

As a *demo artifact* the doc is right. As a product line, the evidence is bad.

### Distribution: what actually worked

**Cal AI**: $0 → ~$40M ARR in ~18 months. The engine was **not** organic — ~250
TikTok/Instagram micro-influencers on monthly retainers, then $1M+/month in Meta
and Google ads. It won on **one hyper-recordable feature** filmable in 10 seconds.

Our equivalent is not the Gandhi Deep Page. It is **reel-import (A4.3)** — paste
a Short, get a path. The doc schedules it for "Months 4+". The research says
that's backwards: it's the wedge or there is no wedge.

Do **not** plan on Show HN or Product Hunt. The category is saturated there and
the audience will clone you rather than use you.

---

## What I would verify before acting on any of this

1. **Read the YouTube Developer Policies yourself, end to end.** The 30-day
   storage cap and derived-metrics clauses are the highest-stakes findings here
   and they change the architecture if accurate. Do this before spending the
   $4–5k pre-build.
2. **Check "Ask YouTube" personally.** If it does what the sources say, D8's
   central strategic assumption needs rewriting.
3. **Do the Reddit research with a browser.** It is the one requested input that
   could not be obtained.
4. **Make five archive calls.** Testing whether a solo founder can get indexing
   rights is the only experiment that could produce a real wall, and it is cheap.
5. **Ask 20 clippers whether they'd pay $20/mo** for cross-YouTube moment
   sourcing. That is a two-week test of the strongest demand signal found.

No code or product decisions have been changed on the basis of this research.

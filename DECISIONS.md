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

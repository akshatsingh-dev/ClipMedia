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

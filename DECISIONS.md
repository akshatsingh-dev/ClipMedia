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

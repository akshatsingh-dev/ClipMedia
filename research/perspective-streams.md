# Perspective Streams — design & research

## The idea (founder's words, distilled)

Two connected capabilities:

1. **Multi-perspective view.** Ask about a contested subject (e.g. "Modi") and see
   it through several lenses — supportive, critical, neutral — each a stream of
   *real clips*, not generated text. The user chooses which lens to watch, or
   compares them.

2. **Your own perspective stream.** A user assembles their own stream of real
   clips that makes a case ("here's why I support X"), and shares it with friends
   as a link. Opinion, but backed by primary footage rather than assertion.

## Why this is the right shape (and the covert-control idea was not)

The earlier "secretly control what kids believe" framing was a legal/PR landmine.
This is its inverse and it is *stronger*:

- **Transparency is the feature, not a compromise.** A shared stream is explicitly
  *one person's perspective*, labeled as such. The multi-lens view explicitly
  *shows the disagreement*. Nobody is being manipulated; everyone can see the
  frame.
- **It fits the master doc's existing rules.** C4/D6 already require contested
  chapters to carry ≥2 credible channels with differing framing and a bridge
  noting the disagreement. `credibility.py` already implements
  `enforce_contested_selection` and `contested_notice`. Multi-perspective is that
  rule promoted to a first-class product surface.
- **It's the anti-slop, anti-bubble position.** "We show you the real footage from
  multiple sides, and let you build and share your own honest case" is a values
  pitch that is actually defensible, unlike "purposeful scrolling" alone.

## Ethical guardrails (baked into the design, not bolted on)

1. A shared stream is **always attributed as a personal perspective** — the UI
   never presents one stream as objective truth.
2. The multi-lens view **labels each lens** (supportive/critical/neutral) and
   **surfaces the other lenses** — you cannot land in one lens without seeing the
   others exist.
3. **Real footage only**, every clip credited and linked to source (the platform's
   existing rule). A perspective is made of primary evidence, not narration.
4. Contested political topics get the **credibility floor** already implemented,
   so a lens is built from sources that actually meet a sourcing bar.
5. No covert anything. If a feed is curated by someone, the viewer is told.

## Part 1 — User-curated perspective streams (buildable now, no LLM)

A "stream" is a user-owned, ordered collection of real clips with a title and a
short stance, shareable by link. This is `learning_paths` generalised to
user-authored, and it reuses the existing clip shape and path renderer.

### Data model
```
streams        (id uuid, anon_id, title, stance, is_public, created_at)
stream_clips   (stream_id, position, video_id, t_start, t_end, note,
                channel, video_title)
```

### Flow
- On any clip (Learn page, feed, search result) → "Add to stream" → pick/create a
  stream.
- A stream editor to reorder, add a note per clip, set the title + stance.
- A public `/stream/[id]` page: plays the clips in order, shows the author's
  stance, labeled clearly as *"{name}'s perspective"*, with per-clip credit.
- Share card: "{title} — a perspective in {N} real clips."

### Why now
Needs no Gemini and no YouTube quota — it is DB + UI over clips that already
exist. It is the shareable/viral surface the master doc's import loop wanted, but
user-authored.

## Part 2 — Multi-lens view (needs the LLM; design for when tokens return)

For a contested query, build several lenses in one page.

### Pipeline change
- **Stage 1 (outline).** Detect a contested/opinion-bearing subject; instead of
  chapters, plan *lenses*: e.g. `["supportive", "critical", "neutral"]`, each with
  its own search hints ("Modi achievements development", "Modi criticism press
  freedom", "Modi neutral analysis").
- **Stages 2–6.** Run retrieval/rank per lens, reusing everything. The credibility
  floor applies so each lens is built from sourced material, not just the loudest
  clips.
- **Stage 7 (assembly).** One page, several labeled lens-streams, with a neutral
  header naming the disagreement (reuse `contested_notice`). Same
  no-new-facts rule on any bridge text.

### Page shape
```json
{"mode":"perspectives","subject":"Narendra Modi",
 "lenses":[
   {"label":"supportive","stance":"...","clips":[...]},
   {"label":"critical","stance":"...","clips":[...]},
   {"label":"neutral","stance":"...","clips":[...]}]}
```

### Guardrail in code
The assembler must produce **all requested lenses or fail** — shipping only the
"supportive" lens would be exactly the manipulation this feature exists to avoid.
Enforce: a perspectives page is invalid unless it has ≥2 lenses.

## Moat implications

- **Shareable perspective streams are a real viral loop** — every shared link is
  an ad, and the thing shared (a curated argument in real clips) is not something
  a text post or a raw playlist can match.
- **Multi-perspective on contested topics is a position incumbents structurally
  avoid** — platforms optimise for engagement, which rewards single-lens outrage.
  "We show you all sides in real footage" is a deliberately un-TikTok stance.
- It leans on the **credibility + contested-source infrastructure already built**,
  which a weekend clone does not have.

## Build order

1. ✅ Contested-source handling (`credibility.py`) — already built.
2. **Streams (Part 1)** — schema, repo, API, editor + `/stream/[id]`, share card.
   No LLM. **Building now.**
3. **Multi-lens outline + assembly (Part 2)** — pipeline change, gated on LLM
   tokens. Designed above; implement when Gemini/该 tokens are available.
4. Turn a shared stream into a seed for "build the other lenses" — closes the loop
   between Part 1 (my view) and Part 2 (all views).

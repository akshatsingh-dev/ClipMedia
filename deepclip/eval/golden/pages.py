"""Golden page definitions — the eval standard AND the demo fixtures (DECISIONS D2).

Video ids here are REAL and are verified against YouTube's public oEmbed endpoint
by build_fixtures.py; title and channel come from that response, so those fields
are authoritative rather than invented.

Clip TIMESTAMPS are NOT verified — nobody watched these videos. They are
plausible placeholders so the UI has something to render. The fixture builder
stamps `timestamps_verified: false` on every page and the UI shows a banner.
Replacing these with hand-picked timestamps is the doc's next-action #1
(master doc lines 408-410) and is what makes this an actual eval standard.
"""

from __future__ import annotations

# Learn Mode golden page. Chapters satisfy the >=2-distinct-channels rule.
LEARN_NEURAL_NETWORKS = {
    "slug": "how-neural-networks-work",
    "query": "how neural networks work",
    "title": "How Neural Networks Actually Work",
    "mode": "learn",
    "subtitle": "From a single neuron to the transformers behind modern LLMs.",
    "chapters": [
        {
            "title": "What a neural network is",
            "intro_text": (
                "Before the maths, the shape: layers of simple units, each passing a "
                "number forward. This is the picture everything else builds on."
            ),
            "clips": [
                {"video_id": "rEDzUT3ymw4", "t_start": 0, "t_end": 62,
                 "why": "Sixty-second version of the whole idea — the hook before the depth."},
                {"video_id": "aircAruvnKk", "t_start": 163, "t_end": 397,
                 "why": "The canonical visual explanation of layers and activations."},
                {"video_id": "VMj-3S1tku0", "t_start": 240, "t_end": 520,
                 "why": "Same concept from code rather than animation — a second voice on the basics."},
            ],
        },
        {
            "title": "How a network learns: gradient descent",
            "intro_text": (
                "A network starts random and wrong. Learning is the search for the "
                "downhill direction in a space with millions of dimensions."
            ),
            "clips": [
                {"video_id": "IHZwWFHWa-w", "t_start": 195, "t_end": 480,
                 "why": "Builds the cost-function landscape intuition before any calculus."},
                {"video_id": "VMj-3S1tku0", "t_start": 1450, "t_end": 1720,
                 "why": "Watches a real loss actually go down in code."},
            ],
        },
        {
            "title": "Backpropagation",
            "intro_text": (
                "The algorithm that makes the search tractable — and the one most "
                "people nod along to without ever quite getting."
            ),
            "clips": [
                {"video_id": "Ilg3gGewQ5U", "t_start": 82, "t_end": 400,
                 "why": "The intuition pass: what each weight nudge is trying to accomplish."},
                {"video_id": "tIeHLnjs5U8", "t_start": 60, "t_end": 340,
                 "why": "The same mechanism with the chain rule made explicit."},
                {"video_id": "VMj-3S1tku0", "t_start": 3100, "t_end": 3400,
                 "why": "Backprop implemented by hand, so it stops being a black box."},
            ],
        },
        {
            "title": "Why depth suddenly worked: AlexNet",
            "intro_text": (
                "The historical break. Deep networks were a curiosity until a 2012 "
                "result made them impossible to ignore."
            ),
            "clips": [
                {"video_id": "UZDiGooFs54", "t_start": 120, "t_end": 460,
                 "why": "The moment the field turned, told as history rather than theory."},
                {"video_id": "5MdSE-N0bxs", "t_start": 300, "t_end": 620,
                 "why": "An academic framing of why depth generalises at all."},
            ],
        },
        {
            "title": "Transformers and attention",
            "intro_text": (
                "The architecture behind every current large language model, and the "
                "one idea inside it that does the real work."
            ),
            "clips": [
                {"video_id": "wjZofJX0v4M", "t_start": 130, "t_end": 470,
                 "why": "Clearest visual account of what a transformer does end to end."},
                {"video_id": "eMlx5fFNoYc", "t_start": 95, "t_end": 430,
                 "why": "Attention specifically, step by step."},
                {"video_id": "bCz4OMemCcA", "t_start": 420, "t_end": 760,
                 "why": "Ties the animation back to the original paper's notation."},
            ],
        },
        {
            "title": "Building one yourself",
            "intro_text": (
                "Understanding ends where implementation begins. Two builds, from "
                "toy GPT to a real reproduction."
            ),
            "clips": [
                {"video_id": "kCc8FmEb1nY", "t_start": 500, "t_end": 850,
                 "why": "A working GPT written live, small enough to follow."},
                {"video_id": "l8pRSuU81PU", "t_start": 300, "t_end": 640,
                 "why": "What changes when the same ideas meet real scale."},
                # Third voice: the two above are both Karpathy, and a chapter
                # from a single channel violates the >=2-channels rule (C6).
                # The eval harness caught this.
                {"video_id": "bCz4OMemCcA", "t_start": 1100, "t_end": 1420,
                 "why": "The same build traced back to the original paper's structure."},
            ],
        },
        {
            "title": "What these models don't do",
            "intro_text": (
                "A closing corrective. Capability benchmarks and understanding are "
                "not the same claim."
            ),
            "clips": [
                {"video_id": "R9OHn5ZF4Uo", "t_start": 60, "t_end": 400,
                 "why": "The strongest short argument against over-reading benchmark scores."},
                {"video_id": "zjkBMFhNj_g", "t_start": 1800, "t_end": 2150,
                 "why": "A practitioner's account of the same limits, from the inside."},
            ],
        },
    ],
}

# Entertain Mode golden feed.
ENTERTAIN_VIRAL_CLASSICS = {
    "slug": "legendary-internet-moments",
    "query": "legendary internet moments",
    "title": "Legendary Internet Moments",
    "mode": "entertain",
    "subtitle": "The clips that built the culture. Best 12, then it ends.",
    "groups": [
        {
            "label": "animals",
            "clips": [
                {"video_id": "0Bmhjf0rKe8", "t_start": 0, "t_end": 17,
                 "why": "The original surprised kitty. Seventeen seconds, no filler."},
                {"video_id": "y8Kyi0WNg40", "t_start": 0, "t_end": 5,
                 "why": "Dramatic Look. Five seconds, still undefeated."},
                {"video_id": "_OBlgSz8sSM", "t_start": 0, "t_end": 56,
                 "why": "Charlie bit my finger — the clip that defined early YouTube."},
            ],
        },
        {
            "label": "music that escaped",
            "clips": [
                {"video_id": "9bZkp7q19f0", "t_start": 0, "t_end": 75,
                 "why": "Gangnam Style's opening — the first video to break a billion."},
                {"video_id": "jofNR_WkoCE", "t_start": 42, "t_end": 110,
                 "why": "What Does The Fox Say, at the exact moment it stops making sense."},
                {"video_id": "ZZ5LpwO-An4", "t_start": 0, "t_end": 60,
                 "why": "HEYYEYAAEYAAAEYAEYAA. No further explanation has ever been offered."},
                {"video_id": "tVj0ZTS4WF4", "t_start": 0, "t_end": 48,
                 "why": "Trololo. The face is the whole clip."},
            ],
        },
        {
            "label": "performances",
            "clips": [
                {"video_id": "dMH0bHeiRNg", "t_start": 0, "t_end": 100,
                 "why": "Evolution of Dance — the original viral stage set."},
                {"video_id": "L_jWHffIx5E", "t_start": 0, "t_end": 70,
                 "why": "All Star's opening line, the most quoted four seconds online."},
                {"video_id": "fJ9rUzIMcZQ", "t_start": 175, "t_end": 240,
                 "why": "The Bohemian Rhapsody headbang section."},
            ],
        },
        {
            "label": "where it started",
            "clips": [
                {"video_id": "jNQXAC9IVRw", "t_start": 0, "t_end": 19,
                 "why": "Me at the zoo. The first video ever uploaded to YouTube."},
                {"video_id": "dQw4w9WgXcQ", "t_start": 43, "t_end": 105,
                 "why": "You know what this is. The chorus, obviously."},
            ],
        },
    ],
}

ALL_PAGES = [LEARN_NEURAL_NETWORKS, ENTERTAIN_VIRAL_CLASSICS]

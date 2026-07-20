"""C4 — channel-level credibility scoring (Learn Mode).

Lazy and cached: scored once per channel, not per video, because credibility is a
property of the channel and re-scoring per page would be pure waste.

Signals the model is asked to weigh: educational intent, sourcing (spoken dates,
names, citations), and sensationalism (inverse). A seed allowlist of
documentary/university/established-history channels is pinned high so the cold
start is not uniformly ignorant.

Contested chapters carry an extra rule: at least two channels above the
credibility floor, with differing framing, and bridge text noting the
disagreement. That is a correctness requirement on history content, not a nicety.
"""

from __future__ import annotations

import logging

from ..llm.client import MODEL_FAST, LLMClient, extract_json

log = logging.getLogger(__name__)

DEFAULT_CREDIBILITY = 0.5
SEED_CREDIBILITY = 0.9
CONTESTED_FLOOR = 0.7
MIN_CONTESTED_CHANNELS = 2
TRANSCRIPT_SAMPLES = 3
SAMPLE_CHARS = 1200

SYSTEM = """You rate the credibility of a video channel for factual/historical \
learning content.

Score 0.0-1.0 weighing:
  + educational intent (explaining vs. performing)
  + sourcing signals: specific dates, named people and places, cited works,
    acknowledgement of uncertainty or disagreement
  - sensationalism: clickbait framing, "what they don't want you to know",
    confident claims with no attribution, conspiracy framing
  - pure entertainment or reaction content (not disqualifying, just not
    credible for factual learning)

Judge sourcing and framing, not production quality or popularity. A plain lecture
outranks a polished documentary that cites nothing.

Output JSON only."""

PROMPT = """Channel: {name}
Description: {description}

Transcript samples:
{samples}

Return JSON:
{{"credibility":0.0-1.0,"educational_intent":0.0-1.0,"sourcing":0.0-1.0,
  "sensationalism":0.0-1.0,"reason":"<one sentence>"}}"""

# Pinned >= 0.9. Deliberately institutions and long-established explainers —
# the point is a trustworthy cold start, not a complete list.
SEED_ALLOWLIST: dict[str, str] = {
    "UCX6b17PVsYBQ0ip5gyeme-Q": "CrashCourse",
    "UCsooa4yRKGN_zEE8iknghZA": "TED-Ed",
    "UC2C_jShtL725hvbm1arSV9w": "CGP Grey",
    "UCYO_jab_esuFRV4b17AJtAw": "3Blue1Brown",
    "UCHnyfMqiRRG1u-2MsSQLbXA": "Veritasium",
    "UCUHW94eEFW7hkUMVaZz4eDg": "MinutePhysics",
    "UCpFFItkfZz1qz5PpHpqzYBw": "Nebula",
    "UCP46_MXP_WG_auH88FnfS1A": "The Great War",
    "UCv_vLHiWVBh_FR9vbeuiY-A": "The Histocrat",
    "UCggHoXaj8BQHIiPmOxezeWA": "Kings and Generals",
    "UC22BdTgxefuvUivrjesETjg": "Oversimplified",
    "UCNIuvl7V8zACPpTmmNIqP2A": "Real Engineering",
    "UCEIwxahdLz7bap-VDs9h35A": "Steve Mould",
    "UC6nSFpj9HTCZ5t-N3Rm3-HA": "Vsauce",
    "UCsXVk37bltHxD1rDPwtNM8Q": "Kurzgesagt",
}


def seed_credibility(channel_id: str) -> float | None:
    """Pinned score for allowlisted channels, else None."""
    return SEED_CREDIBILITY if channel_id in SEED_ALLOWLIST else None


def score_channel(
    channel_id: str,
    channel_name: str,
    transcript_samples: list[str],
    llm: LLMClient,
    description: str = "",
) -> tuple[float, dict]:
    """Score one channel. Returns (credibility, detail).

    Falls back to the neutral default on any failure — an unscored channel must
    not be treated as untrustworthy, which would silently bury new creators.
    """
    pinned = seed_credibility(channel_id)
    if pinned is not None:
        return pinned, {"reason": "seed allowlist", "source": "allowlist"}

    if not transcript_samples:
        return DEFAULT_CREDIBILITY, {"reason": "no transcript samples", "source": "default"}

    samples = "\n\n---\n\n".join(s[:SAMPLE_CHARS] for s in transcript_samples[:TRANSCRIPT_SAMPLES])
    try:
        resp = llm.complete(
            PROMPT.format(
                name=channel_name or channel_id,
                description=description or "(none)",
                samples=samples,
            ),
            system=SYSTEM,
            model=MODEL_FAST,
            max_tokens=512,
        )
        data = extract_json(resp.text)
    except Exception as exc:  # noqa: BLE001
        log.warning("credibility scoring failed for %s: %s", channel_id, exc)
        return DEFAULT_CREDIBILITY, {"reason": f"scoring failed: {exc}", "source": "default"}

    if not isinstance(data, dict):
        return DEFAULT_CREDIBILITY, {"reason": "malformed response", "source": "default"}

    try:
        score = float(data.get("credibility", DEFAULT_CREDIBILITY))
    except (TypeError, ValueError):
        score = DEFAULT_CREDIBILITY

    return max(0.0, min(1.0, score)), {
        "reason": str(data.get("reason", ""))[:300],
        "educational_intent": data.get("educational_intent"),
        "sourcing": data.get("sourcing"),
        "sensationalism": data.get("sensationalism"),
        "source": "llm",
    }


def satisfies_contested_rule(
    candidates, floor: float = CONTESTED_FLOOR, min_channels: int = MIN_CONTESTED_CHANNELS
) -> bool:
    """Does this chapter's selection meet the contested-topic requirement?

    Contested history presented through a single voice is exactly the failure the
    spec calls out (D6: "wrong/misleading clip on contested history"), so a
    chapter flagged contested must carry >= 2 sufficiently-credible channels.
    """
    channels = {c.channel_id for c in candidates if (c.credibility or 0.0) >= floor}
    return len(channels) >= min_channels


def contested_notice(candidates) -> str:
    """Bridge-text addendum for a contested chapter.

    Returned for assembly to append. Naming the disagreement is more honest than
    silently picking a side, and it is cheap.
    """
    channels = sorted({c.channel_id for c in candidates})
    if len(channels) < 2:
        return ""
    return (
        "Accounts of this period differ; the clips below come from sources that "
        "frame it differently."
    )


def enforce_contested_selection(candidates, floor: float = CONTESTED_FLOOR):
    """Re-pick so a contested chapter spans at least two credible channels.

    Keeps the top candidate, then takes the best from each *other* channel above
    the floor. Falls back to the original selection when the corpus genuinely
    cannot satisfy the rule — a thin chapter beats a fabricated balance.
    """
    if not candidates:
        return candidates
    if satisfies_contested_rule(candidates, floor=floor):
        return candidates

    eligible = [c for c in candidates if (c.credibility or 0.0) >= floor]
    if len({c.channel_id for c in eligible}) < MIN_CONTESTED_CHANNELS:
        log.info("corpus cannot satisfy contested rule; keeping original selection")
        return candidates

    picked = []
    seen_channels: set[str] = set()
    for c in eligible:
        if c.channel_id not in seen_channels:
            picked.append(c)
            seen_channels.add(c.channel_id)
    return picked or candidates

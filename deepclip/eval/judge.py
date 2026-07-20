"""C7 — LLM judge.

Sonnet grades each chapter/group 1-5 on coverage, coherence, and clip quality,
judging only against the transcript evidence supplied. Results are tracked per
commit in eval/results/.

The judge is the semantic complement to the lexical metrics: metrics.py catches
"did the words appear", the judge catches "does this actually teach the thing".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from services.worker.llm.client import MODEL_SMART, LLMClient, extract_json

log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"

SYSTEM = """You grade curated video pages against the transcript evidence you are \
given. You are strict and specific.

Grade each section 1-5 on three axes:
  coverage    does it cover what the section claims to cover?
  coherence   do the clips follow each other sensibly? does the bridge text
              actually connect them?
  clip_quality are these substantive moments, or intros, filler, and banter?

Judge ONLY from the transcript evidence provided. If a bridge asserts something \
the transcripts do not support, say so in `issues` and lower coverage — inventing \
facts is the most serious failure this product can have.

Output JSON only."""

PROMPT = """Page: {title} (mode: {mode})

{sections}

Return JSON:
{{"sections":[{{"label":"...","coverage":1-5,"coherence":1-5,
  "clip_quality":1-5,"issues":["..."]}}],
  "overall":1-5,"summary":"<one sentence>"}}"""


@dataclass
class SectionGrade:
    label: str
    coverage: float
    coherence: float
    clip_quality: float
    issues: list[str] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return (self.coverage + self.coherence + self.clip_quality) / 3.0


@dataclass
class JudgeResult:
    overall: float
    sections: list[SectionGrade] = field(default_factory=list)
    summary: str = ""

    @property
    def normalized(self) -> float:
        """1-5 mapped to 0-1, for comparison against the ship gate."""
        return max(0.0, min(1.0, (self.overall - 1.0) / 4.0))

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "normalized": round(self.normalized, 4),
            "summary": self.summary,
            "sections": [
                {
                    "label": s.label,
                    "coverage": s.coverage,
                    "coherence": s.coherence,
                    "clip_quality": s.clip_quality,
                    "mean": round(s.mean, 3),
                    "issues": s.issues,
                }
                for s in self.sections
            ],
        }


def _render_sections(page: dict) -> str:
    blocks = []
    for section in page.get("chapters") or page.get("groups") or []:
        label = section.get("title") or section.get("label") or "(unlabelled)"
        intro = section.get("intro_text", "")
        lines = [f"## {label}"]
        if intro:
            lines.append(f"bridge: {intro}")
        for c in section.get("clips", []):
            lines.append(
                f"  - [{c.get('video_id')}] {c.get('t_start')}-{c.get('t_end')}s "
                f"channel={c.get('channel', '?')}\n"
                f"    why: {c.get('why', '')}\n"
                f"    transcript: {(c.get('transcript') or c.get('text') or '(not supplied)')[:600]}"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _clamp(value, lo=1.0, hi=5.0, default=3.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def judge_page(page: dict, llm: LLMClient) -> JudgeResult:
    resp = llm.complete(
        PROMPT.format(
            title=page.get("title", ""),
            mode=page.get("mode", "learn"),
            sections=_render_sections(page),
        ),
        system=SYSTEM,
        model=MODEL_SMART,
        max_tokens=2048,
    )
    data = extract_json(resp.text)
    if not isinstance(data, dict):
        raise ValueError("judge did not return an object")

    sections = []
    for s in data.get("sections") or []:
        if not isinstance(s, dict):
            continue
        sections.append(
            SectionGrade(
                label=str(s.get("label", "")),
                coverage=_clamp(s.get("coverage")),
                coherence=_clamp(s.get("coherence")),
                clip_quality=_clamp(s.get("clip_quality")),
                issues=[str(i) for i in (s.get("issues") or [])],
            )
        )

    # Prefer the mean of section grades over the model's own `overall`, which
    # tends to be generous relative to the details it just wrote.
    if sections:
        overall = sum(s.mean for s in sections) / len(sections)
    else:
        overall = _clamp(data.get("overall"))

    return JudgeResult(
        overall=overall,
        sections=sections,
        summary=str(data.get("summary", ""))[:500],
    )


def save_result(name: str, payload: dict, results_dir: Path | None = None) -> Path:
    """Write a timestamped result file for per-commit tracking."""
    directory = results_dir or RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{name}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_latest(name: str, results_dir: Path | None = None) -> dict | None:
    """Most recent result for a page, for regression comparison."""
    directory = results_dir or RESULTS_DIR
    if not directory.exists():
        return None
    files = sorted(directory.glob(f"{name}-*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def regression_delta(name: str, current: float, results_dir: Path | None = None) -> float | None:
    """Change in composite score since the last recorded run.

    Negative means this commit made pages worse — the number that matters when
    tuning ranking, since local prompt tweaks routinely help one page and quietly
    break another.
    """
    previous = load_latest(name, results_dir)
    if not previous or "composite" not in previous:
        return None
    return current - float(previous["composite"])

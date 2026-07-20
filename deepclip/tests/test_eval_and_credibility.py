import json

import pytest

from eval.judge import (
    JudgeResult,
    SectionGrade,
    judge_page,
    load_latest,
    regression_delta,
    save_result,
)
from eval.metrics import (
    ClipRef,
    PageScore,
    channel_diversity,
    clips_from_page,
    coverage_recall,
    iou,
    junk_rate,
    overlap_at_k,
    passes_ship_gate,
    redundancy_rate,
    score_page,
)
from services.worker.llm.client import FakeLLMClient
from services.worker.pipeline.credibility import (
    CONTESTED_FLOOR,
    DEFAULT_CREDIBILITY,
    SEED_ALLOWLIST,
    contested_notice,
    enforce_contested_selection,
    satisfies_contested_rule,
    score_channel,
    seed_credibility,
)
from services.worker.pipeline.rank_learn import Candidate

# -- credibility --------------------------------------------------------


def test_seed_allowlist_pins_high():
    known = next(iter(SEED_ALLOWLIST))
    assert seed_credibility(known) == 0.9
    assert seed_credibility("UC_unknown") is None


def test_allowlisted_channel_skips_the_model():
    llm = FakeLLMClient()
    known = next(iter(SEED_ALLOWLIST))
    score, detail = score_channel(known, "name", ["sample"], llm)
    assert score == 0.9
    assert detail["source"] == "allowlist"
    assert llm.calls == [], "must not pay for an allowlisted channel"


def test_score_channel_parses_response():
    llm = FakeLLMClient(responses=[json.dumps({"credibility": 0.82, "reason": "cites dates"})])
    score, detail = score_channel("UC_x", "Chan", ["some transcript"], llm)
    assert score == pytest.approx(0.82)
    assert "cites dates" in detail["reason"]


def test_unscoreable_channel_gets_neutral_not_zero():
    """An unscored channel must not be treated as untrustworthy."""
    score, detail = score_channel("UC_x", "Chan", [], FakeLLMClient())
    assert score == DEFAULT_CREDIBILITY
    assert detail["source"] == "default"


def test_llm_failure_falls_back_to_neutral():
    score, _ = score_channel("UC_x", "Chan", ["s"], FakeLLMClient(responses=["garbage"]))
    assert score == DEFAULT_CREDIBILITY


def test_credibility_clamped():
    llm = FakeLLMClient(responses=[json.dumps({"credibility": 9.5})])
    score, _ = score_channel("UC_x", "Chan", ["s"], llm)
    assert score == 1.0


def cand(channel="UC1", cred=0.9, vid="v1", t=0.0):
    return Candidate(
        segment_id=1, video_id=vid, channel_id=channel, t_start=t, t_end=t + 60,
        text="t", cosine=0.8, credibility=cred,
    )


def test_contested_rule_needs_two_credible_channels():
    assert satisfies_contested_rule([cand("UC1"), cand("UC2", vid="v2")])
    assert not satisfies_contested_rule([cand("UC1"), cand("UC1", vid="v2")])


def test_low_credibility_channels_do_not_count_for_contested():
    """Two voices are not enough if neither is credible."""
    low = [cand("UC1", cred=0.3), cand("UC2", cred=0.4, vid="v2")]
    assert not satisfies_contested_rule(low)


def test_enforce_contested_picks_across_channels():
    cands = [cand("UC1"), cand("UC1", vid="v2"), cand("UC2", vid="v3")]
    out = enforce_contested_selection(cands)
    assert len({c.channel_id for c in out}) >= 2


def test_enforce_contested_gives_up_rather_than_faking_balance():
    """A thin chapter beats fabricated balance."""
    cands = [cand("UC1"), cand("UC1", vid="v2")]
    assert enforce_contested_selection(cands) == cands


def test_contested_notice_names_the_disagreement():
    notice = contested_notice([cand("UC1"), cand("UC2", vid="v2")])
    assert "differ" in notice.lower()
    assert contested_notice([cand("UC1")]) == ""


# -- metrics: iou / overlap ---------------------------------------------


def clip(vid="v1", start=0.0, end=60.0, channel="UC1", text=""):
    return ClipRef(video_id=vid, t_start=start, t_end=end, channel=channel, text=text)


def test_iou_identical_and_disjoint():
    assert iou(clip(), clip()) == pytest.approx(1.0)
    assert iou(clip(start=0, end=10), clip(start=100, end=110)) == 0.0


def test_iou_zero_across_videos():
    assert iou(clip(vid="a"), clip(vid="b")) == 0.0


def test_iou_partial_overlap():
    assert 0.0 < iou(clip(start=0, end=100), clip(start=50, end=150)) < 1.0


def test_overlap_at_k_matches_near_misses():
    """A generated clip a few seconds off a golden pick still counts."""
    golden = [clip(start=100, end=200)]
    generated = [clip(start=105, end=205)]
    assert overlap_at_k(generated, golden) == 1.0


def test_overlap_at_k_respects_k():
    golden = [clip(vid="v9", start=0, end=60)]
    generated = [clip(vid=f"v{i}") for i in range(5)] + [clip(vid="v9")]
    assert overlap_at_k(generated, golden, k=3) == 0.0
    assert overlap_at_k(generated, golden, k=10) == 1.0


def test_overlap_at_k_no_golden():
    assert overlap_at_k([clip()], []) == 0.0


# -- metrics: coverage / redundancy / junk ------------------------------


def test_coverage_recall_detects_covered_goal():
    clips = [clip(text="Gandhi was born in Porbandar in 1869")]
    assert coverage_recall(clips, ["born Porbandar 1869"]) == 1.0


def test_coverage_recall_detects_missing_goal():
    clips = [clip(text="the salt march to Dandi")]
    assert coverage_recall(clips, ["assassination Godse 1948"]) == 0.0


def test_coverage_recall_no_goals_is_one():
    assert coverage_recall([clip()], []) == 1.0


def test_redundancy_detects_overlapping_clips():
    clips = [clip(start=0, end=100), clip(start=10, end=110)]
    assert redundancy_rate(clips) == 1.0


def test_redundancy_detects_similar_text():
    clips = [
        clip(vid="a", text="gandhi led the salt march to dandi"),
        clip(vid="b", text="gandhi led the salt march to dandi sea"),
    ]
    assert redundancy_rate(clips) > 0.0


def test_redundancy_zero_for_distinct_clips():
    clips = [
        clip(vid="a", text="early life in porbandar"),
        clip(vid="b", text="assassination in delhi"),
    ]
    assert redundancy_rate(clips) == 0.0


def test_redundancy_single_clip():
    assert redundancy_rate([clip()]) == 0.0


def test_junk_rate_flags_housekeeping():
    clips = [clip(text="don't forget to subscribe"), clip(vid="b", text="gandhi in 1930")]
    assert junk_rate(clips) == 0.5


def test_junk_rate_empty():
    assert junk_rate([]) == 0.0


def test_channel_diversity_enforced_rule():
    ok = {"ch1": [clip(channel="A"), clip(channel="B")]}
    bad = {"ch1": [clip(channel="A"), clip(channel="A")]}
    assert channel_diversity(ok) == 1.0
    assert channel_diversity(bad) == 0.0


def test_channel_diversity_empty():
    assert channel_diversity({}) == 0.0


# -- page scoring -------------------------------------------------------

PAGE = {
    "slug": "gandhi",
    "mode": "learn",
    "chapters": [
        {
            "title": "Salt March",
            "clips": [
                {"video_id": "v1", "t_start": 100, "t_end": 200, "channel": "A",
                 "why": "the march to Dandi in 1930", "video_title": ""},
                {"video_id": "v2", "t_start": 0, "t_end": 90, "channel": "B",
                 "why": "arrest and aftermath", "video_title": ""},
            ],
        }
    ],
}


def test_clips_from_page_flattens():
    assert len(clips_from_page(PAGE)) == 2


def test_clips_from_empty_page():
    assert clips_from_page({}) == []


def test_score_page_produces_all_metrics():
    s = score_page(PAGE, golden=[clip(vid="v1", start=100, end=200)],
                   coverage_goals=["march Dandi 1930"])
    assert s.overlap_at_k == 1.0
    assert s.coverage_recall == 1.0
    assert s.channel_diversity == 1.0
    assert 0.0 <= s.composite <= 1.0


def test_score_page_notes_missing_inputs():
    s = score_page(PAGE)
    assert any("golden" in n for n in s.notes)
    assert any("coverage goals" in n for n in s.notes)


def test_composite_bounded():
    worst = PageScore(slug="x", redundancy_rate=1.0, junk_rate=1.0)
    best = PageScore(slug="x", coverage_recall=1.0, overlap_at_k=1.0, channel_diversity=1.0)
    assert 0.0 <= worst.composite <= best.composite <= 1.0


def test_ship_gate_requires_every_page():
    """An average would let a good page hide a broken one."""
    good = PageScore(slug="a", coverage_recall=1.0, overlap_at_k=1.0, channel_diversity=1.0)
    bad = PageScore(slug="b", redundancy_rate=1.0, junk_rate=1.0)
    assert passes_ship_gate([good]) is True
    assert passes_ship_gate([good, bad]) is False


def test_ship_gate_empty_fails():
    assert passes_ship_gate([]) is False


# -- judge --------------------------------------------------------------

JUDGE_JSON = {
    "sections": [
        {"label": "Salt March", "coverage": 5, "coherence": 4, "clip_quality": 4, "issues": []},
        {"label": "Legacy", "coverage": 3, "coherence": 3, "clip_quality": 3, "issues": ["thin"]},
    ],
    "overall": 5,
    "summary": "Good but uneven.",
}


def test_judge_parses_sections():
    r = judge_page(PAGE, FakeLLMClient(responses=[json.dumps(JUDGE_JSON)]))
    assert len(r.sections) == 2
    assert r.sections[0].coverage == 5


def test_judge_prefers_section_mean_over_model_overall():
    """The model's own `overall` runs generous relative to its section grades."""
    r = judge_page(PAGE, FakeLLMClient(responses=[json.dumps(JUDGE_JSON)]))
    assert r.overall < 5.0


def test_judge_normalizes_to_unit_range():
    r = JudgeResult(overall=5.0)
    assert r.normalized == 1.0
    assert JudgeResult(overall=1.0).normalized == 0.0


def test_judge_clamps_out_of_range_grades():
    payload = {"sections": [{"label": "x", "coverage": 99, "coherence": -5, "clip_quality": "bad"}]}
    r = judge_page(PAGE, FakeLLMClient(responses=[json.dumps(payload)]))
    assert r.sections[0].coverage == 5.0
    assert r.sections[0].coherence == 1.0
    assert r.sections[0].clip_quality == 3.0


def test_judge_rejects_non_object():
    with pytest.raises(ValueError):
        judge_page(PAGE, FakeLLMClient(responses=["[1,2,3]"]))


def test_section_grade_mean():
    assert SectionGrade("x", 3.0, 3.0, 3.0).mean == 3.0


# -- result persistence -------------------------------------------------


def test_save_and_load_result(tmp_path):
    save_result("gandhi", {"composite": 0.8}, results_dir=tmp_path)
    assert load_latest("gandhi", results_dir=tmp_path)["composite"] == 0.8


def test_load_latest_missing(tmp_path):
    assert load_latest("nothing", results_dir=tmp_path) is None


def test_regression_delta_detects_drop(tmp_path):
    """The number that matters when tuning: did this commit make pages worse?"""
    save_result("gandhi", {"composite": 0.80}, results_dir=tmp_path)
    assert regression_delta("gandhi", 0.70, results_dir=tmp_path) == pytest.approx(-0.10)


def test_regression_delta_without_baseline(tmp_path):
    assert regression_delta("new", 0.5, results_dir=tmp_path) is None

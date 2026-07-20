import json
import os

import pytest

from services.worker.llm.client import FakeLLMClient
from services.worker.pipeline.rank_learn import Candidate
from services.worker.pipeline.vision import (
    LEARN_TAGS,
    MAX_SEGMENTS_PER_PAGE,
    VisionResult,
    apply_vision,
    storyboard_url,
    tag_segments,
    vision_enabled,
)


@pytest.fixture
def vision_on(monkeypatch):
    monkeypatch.setenv("DEEPCLIP_VISION", "1")


def cand(i=0, vid="v1"):
    return Candidate(
        segment_id=i, video_id=vid, channel_id="UC1",
        t_start=i * 60.0, t_end=i * 60.0 + 60, text="t", cosine=0.5,
    )


def test_disabled_by_default(monkeypatch):
    """Post-MVP by spec: must not run unless explicitly enabled."""
    monkeypatch.delenv("DEEPCLIP_VISION", raising=False)
    assert vision_enabled() is False


def test_disabled_pass_makes_no_llm_calls(monkeypatch):
    monkeypatch.delenv("DEEPCLIP_VISION", raising=False)
    llm = FakeLLMClient()
    results = tag_segments([cand(0), cand(1)], llm)
    assert len(results) == 2
    assert llm.calls == []


def test_enabled_via_env(vision_on):
    assert vision_enabled() is True


def test_storyboard_url_is_an_image_never_video():
    url = storyboard_url("abc", 0)
    assert url.startswith("https://i.ytimg.com/vi/abc/")
    assert url.endswith(".jpg")


def test_tags_parsed(vision_on):
    payload = {"frames": [{"id": 0, "tags": {"archival": 0.9, "talking_head": 0.1}}]}
    results = tag_segments([cand(0)], FakeLLMClient(responses=[json.dumps(payload)]))
    assert results[0].tags["archival"] == pytest.approx(0.9)


def test_unknown_tags_discarded(vision_on):
    payload = {"frames": [{"id": 0, "tags": {"archival": 0.9, "not_a_tag": 1.0}}]}
    results = tag_segments([cand(0)], FakeLLMClient(responses=[json.dumps(payload)]))
    assert "not_a_tag" not in results[0].tags


def test_tag_scores_clamped(vision_on):
    payload = {"frames": [{"id": 0, "tags": {"archival": 5.0, "map": -2.0}}]}
    results = tag_segments([cand(0)], FakeLLMClient(responses=[json.dumps(payload)]))
    assert results[0].tags["archival"] == 1.0
    assert results[0].tags["map"] == 0.0


def test_malformed_response_degrades(vision_on):
    """Losing visual_richness costs 0.10 of the score, never a page."""
    results = tag_segments([cand(0)], FakeLLMClient(responses=["garbage"]))
    assert results[0].tags == {}


def test_out_of_range_ids_ignored(vision_on):
    payload = {"frames": [{"id": 99, "tags": {"archival": 1.0}}]}
    results = tag_segments([cand(0)], FakeLLMClient(responses=[json.dumps(payload)]))
    assert results[0].tags == {}


def test_batching(vision_on):
    llm = FakeLLMClient(default='{"frames":[]}')
    tag_segments([cand(i) for i in range(25)], llm, batch_size=10)
    assert len(llm.calls) == 3


def test_segment_cap_enforced(vision_on):
    """The cap is the cost guardrail — this stage scales with clips, not pages."""
    llm = FakeLLMClient(default='{"frames":[]}')
    results = tag_segments(
        [cand(i) for i in range(MAX_SEGMENTS_PER_PAGE + 50)], llm, batch_size=50
    )
    assert len(results) <= MAX_SEGMENTS_PER_PAGE


def test_richness_prefers_archival_over_talking_head():
    """Talking heads are the baseline of educational video; archival is the value."""
    archival = VisionResult(0, {"archival": 1.0})
    head = VisionResult(0, {"talking_head": 1.0})
    assert archival.richness("learn") > head.richness("learn")


def test_richness_bounded_and_empty_safe():
    assert VisionResult(0, {}).richness() == 0.0
    loud = VisionResult(0, {t: 1.0 for t in LEARN_TAGS})
    assert 0.0 <= loud.richness("learn") <= 1.0


def test_entertain_richness_uses_its_own_weights():
    reaction = VisionResult(0, {"face_reaction": 1.0})
    assert reaction.richness("entertain") > reaction.richness("learn")


def test_apply_vision_sets_fields(vision_on):
    payload = {"frames": [{"id": 0, "tags": {"archival": 1.0}}]}
    c = cand(0)
    apply_vision([c], FakeLLMClient(responses=[json.dumps(payload)]))
    assert c.visual_richness > 0.0
    assert c.vis_tags["archival"] == 1.0


def test_apply_vision_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("DEEPCLIP_VISION", raising=False)
    c = cand(0)
    apply_vision([c], FakeLLMClient())
    assert c.visual_richness == 0.0

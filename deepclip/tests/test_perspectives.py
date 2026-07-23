import json
import pytest

from services.worker.llm.client import FakeLLMClient, LLMError
from services.worker.pipeline.outline import (
    build_perspectives_outline,
    parse_perspectives_outline,
)
from services.worker.pipeline.assemble import assemble_perspectives
from services.worker.pipeline.rank_learn import Candidate


PERSP_JSON = {
    "mode": "perspectives", "subject": "Narendra Modi", "title": "Narendra Modi: Multiple Perspectives",
    "lenses": [
        {"label": "supportive", "search_hints": ["Modi development achievements", "Modi economy growth"]},
        {"label": "critical", "search_hints": ["Modi criticism press freedom", "Modi democracy concerns"]},
        {"label": "neutral", "search_hints": ["Modi factcheck analysis", "Modi policy explained neutral"]},
    ],
}


def test_parse_perspectives_outline():
    o = parse_perspectives_outline(PERSP_JSON, "Modi")
    assert o.mode == "perspectives"
    assert {g.label for g in o.groupings} == {"supportive", "critical", "neutral"}


def test_perspectives_requires_two_lenses():
    """The guardrail: a one-sided perspectives page is invalid by design."""
    one = dict(PERSP_JSON, lenses=[{"label": "supportive", "search_hints": ["a"]}])
    with pytest.raises(LLMError, match="one-sided"):
        parse_perspectives_outline(one, "Modi")


def test_perspectives_ignores_unknown_lens_labels():
    data = dict(PERSP_JSON, lenses=[
        {"label": "supportive", "search_hints": ["a"]},
        {"label": "propaganda", "search_hints": ["b"]},  # not a valid lens
        {"label": "critical", "search_hints": ["c"]},
    ])
    o = parse_perspectives_outline(data, "Modi")
    assert {g.label for g in o.groupings} == {"supportive", "critical"}


def test_build_perspectives_outline_uses_smart_model():
    llm = FakeLLMClient(responses=[json.dumps(PERSP_JSON)])
    o = build_perspectives_outline("Modi", llm)
    assert o.mode == "perspectives"
    assert llm.calls[0]["model"] == "claude-sonnet-5"


def cand(vid, channel, text="a real clip about the subject", t=10.0):
    return Candidate(segment_id=1, video_id=vid, channel_id=channel, t_start=t,
                     t_end=t + 40, text=text, cosine=0.8, title="v")


def outline_obj():
    return parse_perspectives_outline(PERSP_JSON, "Modi")


def test_assemble_perspectives_builds_balanced_page():
    lens_clips = {
        "supportive": [cand("v1", "UC1", "the economy grew under his leadership")],
        "critical": [cand("v2", "UC2", "press freedom rankings declined")],
    }
    payload = {
        "subject": "Narendra Modi",
        "lenses": [
            {"label": "supportive", "stance": "Supporters point to economic growth.",
             "clips": [{"video_id": "v1", "t_start": 10, "why": "growth"}]},
            {"label": "critical", "stance": "Critics point to press freedom.",
             "clips": [{"video_id": "v2", "t_start": 10, "why": "press"}]},
        ],
    }
    page = assemble_perspectives(outline_obj(), lens_clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert page["mode"] == "perspectives"
    assert len(page["lenses"]) == 2
    assert {l["label"] for l in page["lenses"]} == {"supportive", "critical"}
    assert "notice" in page


def test_assemble_refuses_one_sided_page():
    """If only one lens has clips, refuse — this is the core guardrail."""
    lens_clips = {"supportive": [cand("v1", "UC1")]}
    with pytest.raises(LLMError, match="one-sided"):
        assemble_perspectives(outline_obj(), lens_clips, FakeLLMClient())


def test_assemble_refuses_if_model_collapses_lenses():
    """Model returns clips for only one lens -> refuse."""
    lens_clips = {
        "supportive": [cand("v1", "UC1")],
        "critical": [cand("v2", "UC2")],
    }
    payload = {"lenses": [
        {"label": "supportive", "stance": "x", "clips": [{"video_id": "v1", "t_start": 10, "why": "w"}]},
        {"label": "critical", "stance": "y", "clips": []},  # collapsed
    ]}
    with pytest.raises(LLMError, match="collapsed"):
        assemble_perspectives(outline_obj(), lens_clips, FakeLLMClient(responses=[json.dumps(payload)]))


def test_stance_with_unsupported_facts_is_dropped():
    lens_clips = {
        "supportive": [cand("v1", "UC1", "the economy grew")],
        "critical": [cand("v2", "UC2", "some concerns exist")],
    }
    payload = {"lenses": [
        {"label": "supportive", "stance": "GDP grew 8.5% in 2019.",  # 8.5/2019 not in clips
         "clips": [{"video_id": "v1", "t_start": 10, "why": "w"}]},
        {"label": "critical", "stance": "There are concerns.",
         "clips": [{"video_id": "v2", "t_start": 10, "why": "w"}]},
    ]}
    page = assemble_perspectives(outline_obj(), lens_clips, FakeLLMClient(responses=[json.dumps(payload)]))
    sup = next(l for l in page["lenses"] if l["label"] == "supportive")
    assert "2019" not in sup["stance"]

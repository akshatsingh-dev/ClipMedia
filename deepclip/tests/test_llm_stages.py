import json

import pytest

from services.worker.llm.client import (
    CostTracker,
    FakeLLMClient,
    LLMError,
    LLMResponse,
    extract_json,
)
from services.worker.pipeline.assemble import (
    assemble_entertain,
    assemble_learn,
    verify_no_new_facts,
)
from services.worker.pipeline.outline import (
    Outline,
    build_outline,
    normalize_query,
    parse_outline,
)
from services.worker.pipeline.rank_learn import Candidate
from services.worker.pipeline.score import (
    looks_like_junk,
    repair_names,
    score_segments,
)
from services.worker.pipeline.segment import Segment

# -- JSON extraction ----------------------------------------------------


def test_extract_plain_json():
    assert extract_json('{"a":1}') == {"a": 1}


def test_extract_fenced_json():
    assert extract_json('```json\n{"a":1}\n```') == {"a": 1}


def test_extract_json_with_surrounding_prose():
    """Models add 'Here's the JSON:' even when told not to."""
    assert extract_json('Sure! Here is the plan:\n{"a":1}\nHope that helps.') == {"a": 1}


def test_extract_json_array():
    assert extract_json("garbage [1,2,3] trailing") == [1, 2, 3]


def test_extract_json_failure_raises():
    with pytest.raises(LLMError):
        extract_json("no json at all here")


# -- cost tracking ------------------------------------------------------


def test_cost_tracker_accumulates():
    t = CostTracker()
    t.record(LLMResponse("x", input_tokens=1_000_000, output_tokens=0, model="claude-sonnet-5"))
    assert t.calls == 1
    assert t.cost_usd == pytest.approx(3.00)


def test_cost_tracker_ignores_unknown_model():
    t = CostTracker()
    t.record(LLMResponse("x", input_tokens=1000, output_tokens=1000, model="mystery"))
    assert t.cost_usd == 0.0


# -- query normalisation ------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Mahatma Gandhi", "  mahatma   gandhi "),
        ("Gandhi's Salt March!", "gandhis salt march"),
        ("Café", "cafe"),
    ],
)
def test_normalize_query_collapses_variants(a, b):
    assert normalize_query(a) == normalize_query(b)


def test_normalize_query_distinguishes_real_differences():
    assert normalize_query("gandhi") != normalize_query("mlk")


# -- outline parsing ----------------------------------------------------

LEARN_JSON = {
    "mode": "learn",
    "entity_type": "person",
    "title": "Mahatma Gandhi",
    "chapters": [
        {
            "title": "Early Life in Porbandar",
            "search_hints": ["Gandhi childhood Porbandar"],
            "coverage_goals": ["birth 1869"],
            "contested": False,
        },
        {
            "title": "Partition",
            "search_hints": ["Gandhi partition 1947"],
            "coverage_goals": ["violence"],
            "contested": True,
        },
    ],
}

ENTERTAIN_JSON = {
    "mode": "entertain",
    "subject": "IShowSpeed",
    "vibe": "funny",
    "title": "Funny Speed Moments",
    "search_hints": ["IShowSpeed funniest moments"],
    "groupings": [
        {"label": "soccer", "search_hints": ["speed soccer funny"]},
        {"label": "streams", "search_hints": ["speed stream fail"]},
    ],
}


def test_parse_learn_outline():
    o = parse_outline(LEARN_JSON, "gandhi")
    assert o.mode == "learn"
    assert len(o.chapters) == 2
    assert o.chapters[1].contested is True
    assert o.query_norm == "gandhi"


def test_parse_entertain_outline():
    o = parse_outline(ENTERTAIN_JSON, "funny speed")
    assert o.mode == "entertain"
    assert [g.label for g in o.groupings] == ["soccer", "streams"]


def test_groupings_accept_bare_strings():
    data = dict(ENTERTAIN_JSON, groupings=["soccer", "irl"])
    o = parse_outline(data, "q")
    assert [g.label for g in o.groupings] == ["soccer", "irl"]


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "nonsense", "chapters": [{"title": "x", "search_hints": ["y"]}]},
        {"mode": "learn", "chapters": []},
        {"mode": "learn"},
        {"mode": "entertain", "groupings": []},
        [],
        "not an object",
    ],
)
def test_invalid_outlines_raise(bad):
    with pytest.raises(LLMError):
        parse_outline(bad, "q")


def test_outline_with_no_hints_raises():
    """A plan that cannot retrieve anything must fail loudly, not silently."""
    data = {"mode": "learn", "chapters": [{"title": "A", "search_hints": []}]}
    with pytest.raises(LLMError):
        parse_outline(data, "q")


def test_chapters_capped():
    data = dict(
        LEARN_JSON,
        chapters=[
            {"title": f"C{i}", "search_hints": [f"h{i}"]} for i in range(30)
        ],
    )
    assert len(parse_outline(data, "q").chapters) <= 10


def test_all_hints_dedupes_preserving_order():
    o = Outline(
        mode="learn",
        title="t",
        query="q",
        query_norm="q",
        search_hints=["alpha", "Alpha ", "beta"],
    )
    assert o.all_hints() == ["alpha", "beta"]


def test_entity_names_extracted_for_repair():
    o = parse_outline(LEARN_JSON, "gandhi")
    names = o.entity_names()
    assert any("Gandhi" in n for n in names)
    assert any("Porbandar" in n for n in names)


def test_build_outline_end_to_end_with_fake():
    llm = FakeLLMClient(responses=[json.dumps(LEARN_JSON)])
    o = build_outline("Mahatma Gandhi", llm)
    assert o.mode == "learn"
    assert llm.calls[0]["model"] == "claude-sonnet-5", "outline must use the smart model"


def test_build_outline_propagates_bad_json():
    with pytest.raises(LLMError):
        build_outline("q", FakeLLMClient(responses=["not json"]))


# -- scoring ------------------------------------------------------------


def seg(i, text="some content here"):
    return Segment(video_id="v1", t_start=i * 60.0, t_end=i * 60.0 + 60.0, text=text)


def test_score_segments_maps_by_id():
    segs = [seg(i) for i in range(3)]
    payload = {"scores": [{"id": 0, "score": 0.9}, {"id": 1, "score": 0.1}, {"id": 2, "score": 0.5}]}
    scores = score_segments(segs, FakeLLMClient(responses=[json.dumps(payload)]))
    assert scores == [0.9, 0.1, 0.5]


def test_score_segments_uses_fast_model():
    llm = FakeLLMClient(responses=['{"scores":[{"id":0,"score":1.0}]}'])
    score_segments([seg(0)], llm)
    assert llm.calls[0]["model"] == "claude-haiku-4-5-20251001"


def test_partial_scores_fall_back_to_default():
    """One missing id must not shift every other segment's score."""
    segs = [seg(i) for i in range(3)]
    payload = {"scores": [{"id": 0, "score": 0.9}, {"id": 2, "score": 0.2}]}
    scores = score_segments(segs, FakeLLMClient(responses=[json.dumps(payload)]), default=0.5)
    assert scores == [0.9, 0.5, 0.2]


def test_malformed_batch_degrades_to_defaults():
    segs = [seg(i) for i in range(3)]
    scores = score_segments(segs, FakeLLMClient(responses=["total garbage"]), default=0.4)
    assert scores == [0.4, 0.4, 0.4], "a bad batch should degrade, not crash"


def test_scores_clamped():
    payload = {"scores": [{"id": 0, "score": 5.0}, {"id": 1, "score": -3.0}]}
    scores = score_segments([seg(0), seg(1)], FakeLLMClient(responses=[json.dumps(payload)]))
    assert scores == [1.0, 0.0]


def test_out_of_range_ids_ignored():
    payload = {"scores": [{"id": 99, "score": 1.0}, {"id": 0, "score": 0.8}]}
    scores = score_segments([seg(0)], FakeLLMClient(responses=[json.dumps(payload)]))
    assert scores == [0.8]


def test_batching_splits_calls():
    segs = [seg(i) for i in range(7)]
    llm = FakeLLMClient(default='{"scores":[]}')
    score_segments(segs, llm, batch_size=3)
    assert len(llm.calls) == 3


def test_empty_segments_makes_no_calls():
    llm = FakeLLMClient()
    assert score_segments([], llm) == []
    assert llm.calls == []


def test_unknown_score_kind_raises():
    with pytest.raises(ValueError):
        score_segments([seg(0)], FakeLLMClient(), kind="vibes")


def test_quality_and_intensity_use_different_systems():
    llm = FakeLLMClient(default='{"scores":[]}')
    score_segments([seg(0)], llm, kind="quality")
    score_segments([seg(0)], llm, kind="intensity")
    assert llm.calls[0]["system"] != llm.calls[1]["system"]


# -- junk pre-filter ----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Don't forget to subscribe to the channel!", True),
        ("This video is sponsored by NordVPN", True),
        ("use code SAVE10 at checkout", True),
        ("Gandhi returned to India in 1915", False),
    ],
)
def test_looks_like_junk(text, expected):
    assert looks_like_junk(text) is expected


# -- name repair --------------------------------------------------------


def test_repair_names_applies_correction():
    llm = FakeLLMClient(responses=['{"text":"Jinnah opposed the plan"}'])
    assert repair_names("gina opposed the plan", ["Jinnah"], llm) == "Jinnah opposed the plan"


def test_repair_names_rejects_wholesale_rewrite():
    """A model that rewrites the passage must not be trusted over the original."""
    original = "gina opposed the plan"
    llm = FakeLLMClient(responses=['{"text":"' + "x" * 500 + '"}'])
    assert repair_names(original, ["Jinnah"], llm) == original


def test_repair_names_noop_without_names():
    llm = FakeLLMClient()
    assert repair_names("text", [], llm) == "text"
    assert llm.calls == []


def test_repair_names_survives_llm_failure():
    llm = FakeLLMClient(responses=["not json"])
    assert repair_names("original text", ["Name"], llm) == "original text"


# -- fact verification --------------------------------------------------


def test_unsupported_date_detected():
    """The core anti-hallucination check."""
    assert "1869" in verify_no_new_facts(
        "Gandhi was born in 1869.", "he was born in Porbandar to a merchant family"
    )


def test_supported_facts_pass():
    assert verify_no_new_facts(
        "Gandhi was born in 1869.", "Gandhi was born in 1869 in Porbandar"
    ) == []


def test_sentence_starters_not_flagged_as_names():
    assert verify_no_new_facts("The march began.", "the march began") == []


def test_unsupported_name_detected():
    assert "Nehru" in verify_no_new_facts("Nehru disagreed.", "gandhi spoke about the march")


def test_empty_bridge_is_clean():
    assert verify_no_new_facts("", "anything") == []


# -- assembly -----------------------------------------------------------


def cand(vid="v1", t=100.0, text="Gandhi led the march to Dandi in 1930", ch="UC1"):
    return Candidate(
        segment_id=1,
        video_id=vid,
        channel_id=ch,
        t_start=t,
        t_end=t + 60,
        text=text,
        cosine=0.8,
        title="A video",
    )


def outline_learn():
    return parse_outline(LEARN_JSON, "gandhi")


def test_assemble_learn_builds_page():
    clips = {"Salt March": [cand()]}
    payload = {
        "title": "Mahatma Gandhi",
        "chapters": [
            {
                "title": "Salt March",
                "intro_text": "The march to Dandi in 1930.",
                "clips": [{"video_id": "v1", "t_start": 100, "why": "best footage"}],
            }
        ],
    }
    page = assemble_learn(outline_learn(), clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert page["mode"] == "learn"
    assert page["chapters"][0]["clips"][0]["video_id"] == "v1"
    assert page["chapters"][0]["clips"][0]["t_end"] == 160.0, "t_end comes from us, not the model"


def test_assemble_strips_unsupported_bridge_sentence():
    """A hallucinated date must not survive into the page."""
    clips = {"Salt March": [cand(text="he walked to the sea with his followers")]}
    payload = {
        "chapters": [
            {
                "title": "Salt March",
                "intro_text": "He walked to the sea. It happened in 1930.",
                "clips": [{"video_id": "v1", "t_start": 100, "why": "w"}],
            }
        ]
    }
    page = assemble_learn(outline_learn(), clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert "1930" not in page["chapters"][0]["intro_text"]


def test_assemble_keeps_supported_bridge():
    clips = {"Salt March": [cand(text="the march to Dandi happened in 1930")]}
    payload = {
        "chapters": [
            {
                "title": "Salt March",
                "intro_text": "The march happened in 1930.",
                "clips": [{"video_id": "v1", "t_start": 100, "why": "w"}],
            }
        ]
    }
    page = assemble_learn(outline_learn(), clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert "1930" in page["chapters"][0]["intro_text"]


def test_assemble_ignores_invented_clips():
    """The model must not be able to add a video that was never retrieved."""
    clips = {"Salt March": [cand(vid="real")]}
    payload = {
        "chapters": [
            {
                "title": "Salt March",
                "intro_text": "",
                "clips": [
                    {"video_id": "real", "t_start": 100, "why": "w"},
                    {"video_id": "HALLUCINATED", "t_start": 5, "why": "w"},
                ],
            }
        ]
    }
    page = assemble_learn(outline_learn(), clips, FakeLLMClient(responses=[json.dumps(payload)]))
    ids = [c["video_id"] for c in page["chapters"][0]["clips"]]
    assert ids == ["real"]


def test_assemble_tolerates_rounded_timestamps():
    clips = {"Ch": [cand(t=312.4)]}
    payload = {
        "chapters": [
            {"title": "Ch", "intro_text": "", "clips": [{"video_id": "v1", "t_start": 312, "why": "w"}]}
        ]
    }
    page = assemble_learn(outline_learn(), clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert page["chapters"][0]["clips"][0]["t_start"] == 312.4


def test_bridge_trimmed_to_three_sentences():
    clips = {"Ch": [cand(text="a b c d e f")]}
    payload = {
        "chapters": [
            {
                "title": "Ch",
                "intro_text": "One. Two. Three. Four. Five.",
                "clips": [{"video_id": "v1", "t_start": 100, "why": "w"}],
            }
        ]
    }
    page = assemble_learn(outline_learn(), clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert page["chapters"][0]["intro_text"].count(".") <= 3


def test_assemble_learn_empty_input_raises():
    with pytest.raises(LLMError):
        assemble_learn(outline_learn(), {}, FakeLLMClient())


def test_assemble_learn_unusable_response_raises():
    clips = {"Ch": [cand()]}
    with pytest.raises(LLMError):
        assemble_learn(outline_learn(), clips, FakeLLMClient(responses=['{"chapters":[]}']))


def test_assemble_entertain_builds_feed():
    o = parse_outline(ENTERTAIN_JSON, "funny speed")
    clips = {"soccer": [cand(vid="s1")]}
    payload = {
        "title": "Funny Speed",
        "groups": [
            {"label": "soccer", "clips": [{"video_id": "s1", "t_start": 100, "why": "he falls over"}]}
        ],
        "end_card": "That's the feed.",
    }
    feed = assemble_entertain(o, clips, FakeLLMClient(responses=[json.dumps(payload)]))
    assert feed["mode"] == "entertain"
    assert feed["end_card"] == "That's the feed."
    assert feed["groups"][0]["clips"][0]["video_id"] == "s1"

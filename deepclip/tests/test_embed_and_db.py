import pytest

from packages.db.repo import (
    SegmentRow,
    VideoRow,
    from_pgvector,
    to_pgvector,
)
from services.worker.pipeline.embed import (
    EMBED_DIM,
    HashingEmbedder,
    build_embedder,
    cosine,
    embed_texts,
    l2_normalize,
)

# -- embeddings ---------------------------------------------------------


def test_hashing_embedder_dim_and_normalised():
    e = HashingEmbedder()
    (v,) = e.embed(["hello world"])
    assert len(v) == EMBED_DIM
    assert cosine(v, v) == pytest.approx(1.0)


def test_hashing_embedder_is_deterministic():
    a = HashingEmbedder().embed(["gandhi salt march"])[0]
    b = HashingEmbedder().embed(["gandhi salt march"])[0]
    assert a == b


def test_identical_text_matches_different_text_does_not():
    e = HashingEmbedder()
    a, b, c = e.embed(["neural networks", "neural networks", "completely other words"])
    assert cosine(a, b) == pytest.approx(1.0)
    assert cosine(a, c) < 0.5


def test_l2_normalize_zero_vector_safe():
    assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]


def test_l2_normalize_unit_length():
    v = l2_normalize([3.0, 4.0])
    assert sum(x * x for x in v) == pytest.approx(1.0)


def test_embed_texts_preserves_alignment_with_blanks():
    """A blank segment must still produce a vector or every later index shifts."""
    out = embed_texts(["real text", "", "   "], HashingEmbedder())
    assert len(out) == 3
    assert all(len(v) == EMBED_DIM for v in out)


def test_embed_texts_empty():
    assert embed_texts([], HashingEmbedder()) == []


def test_embed_texts_detects_count_mismatch():
    class Broken:
        dim = EMBED_DIM

        def embed(self, texts):
            return [[0.0] * EMBED_DIM]  # drops entries

    with pytest.raises(RuntimeError):
        embed_texts(["a", "b"], Broken())


def test_cosine_edge_cases():
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_build_embedder_rejects_unknown():
    with pytest.raises(ValueError):
        build_embedder("nonsense")


def test_build_embedder_hashing_is_opt_in():
    """Hashing must never be reachable by default — it destroys retrieval."""
    assert isinstance(build_embedder("hashing"), HashingEmbedder)


# -- pgvector serialisation --------------------------------------------


def test_to_pgvector_format():
    assert to_pgvector([0.1, 0.2]) == "[0.1,0.2]"


def test_to_pgvector_none_passes_through():
    assert to_pgvector(None) is None


def test_pgvector_roundtrip():
    vec = [0.125, -0.5, 0.75]
    assert from_pgvector(to_pgvector(vec)) == pytest.approx(vec)


def test_from_pgvector_handles_list_and_empty():
    assert from_pgvector([1.0, 2.0]) == [1.0, 2.0]
    assert from_pgvector("[]") == []
    assert from_pgvector(None) is None
    assert from_pgvector("not a vector") is None


def test_pgvector_roundtrip_full_dim():
    vec = l2_normalize([float(i % 7) for i in range(EMBED_DIM)])
    back = from_pgvector(to_pgvector(vec))
    assert len(back) == EMBED_DIM
    assert cosine(vec, back) == pytest.approx(1.0, abs=1e-4)


# -- row dataclasses ----------------------------------------------------


def test_video_row_defaults():
    v = VideoRow(id="x", source="youtube")
    assert v.credibility == 0.5
    assert v.transcript_kind is None


def test_segment_row_optional_fields():
    s = SegmentRow(video_id="v", t_start=0.0, t_end=30.0, text="t")
    assert s.embedding is None
    assert s.id is None

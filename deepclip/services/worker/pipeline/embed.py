"""Stage 5a — embeddings.

Spec C1 says: benchmark an open model (bge-m3) against a hosted small embedding
model on a 200-query eval set; <=1024 dims. That benchmark needs the eval harness
and real traffic, so this module makes the choice swappable rather than baking
one in: `Embedder` is the seam, and `eval/benchmark_embeddings.py` is where the
comparison will live.

Dimension is fixed at 1024 because `segments.embedding` is VECTOR(1024) and the
HNSW index is built on it — changing dims is a migration, not a config flip.
"""

from __future__ import annotations

import hashlib
import time
import logging
import math
import os
import struct
from typing import Protocol, Sequence

log = logging.getLogger(__name__)

EMBED_DIM = 1024
BATCH_SIZE = 64


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def l2_normalize(vec: list[float]) -> list[float]:
    """Normalise so cosine similarity reduces to a dot product.

    pgvector's `vector_cosine_ops` handles this itself, but normalising on write
    keeps in-Python comparisons (redundancy checks in ranking) consistent with
    what the database computes.
    """
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


class HashingEmbedder:
    """Deterministic offline embedder. NOT semantic.

    Exists so the full pipeline — segment -> embed -> store -> vector search —
    can be exercised end to end without a model or network. It produces stable,
    normalised vectors where identical text matches itself and different text
    does not, which is enough to test plumbing.

    It is NOT a fallback for production: retrieval quality with this embedder is
    nil. `build_embedder` will not select it unless explicitly asked.
    """

    dim = EMBED_DIM

    def __init__(self, dim: int = EMBED_DIM):
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        # Hash token trigram-ish features into buckets; stable across runs.
        for token in (text or "").lower().split():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = struct.unpack("<Q", digest)[0] % self.dim
            vec[bucket] += 1.0
        return l2_normalize(vec)


class BGEEmbedder:
    """bge-m3 via sentence-transformers. The open-model candidate from C1."""

    dim = EMBED_DIM

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None):
        from sentence_transformers import SentenceTransformer  # lazy

        self._model = SentenceTransformer(model_name, device=device)
        actual = self._model.get_sentence_embedding_dimension()
        if actual != EMBED_DIM:
            # Truncation is a supported bge-m3 usage (Matryoshka), but silently
            # storing a differently-shaped vector would corrupt the index.
            log.warning(
                "model dim %d != column dim %d; vectors will be truncated",
                actual,
                EMBED_DIM,
            )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raw = self._model.encode(
            list(texts), batch_size=BATCH_SIZE, normalize_embeddings=True
        )
        return [l2_normalize(list(v[:EMBED_DIM])) for v in raw]


class VoyageEmbedder:
    """Hosted candidate. Voyage is Anthropic's recommended embedding provider."""

    dim = EMBED_DIM

    def __init__(self, model: str = "voyage-3", api_key: str | None = None):
        key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise RuntimeError("VOYAGE_API_KEY is not set")
        import voyageai  # lazy

        self._client = voyageai.Client(api_key=key)
        self._model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            resp = self._client.embed(batch, model=self._model, input_type="document")
            out.extend(l2_normalize(list(v[:EMBED_DIM])) for v in resp.embeddings)
        return out


class GeminiEmbedder:
    """Hosted embeddings via Gemini. Requires GEMINI_API_KEY.

    Chosen as the default when a Gemini key is present because it avoids the ~2GB
    bge-m3 download, keeps a single provider, and gemini-embedding-001 outputs
    1024 dims natively — matching the schema's VECTOR(1024) exactly.

    `input_type` distinguishes documents from queries: retrieval quality improves
    when the stored segments are embedded as RETRIEVAL_DOCUMENT and the search
    query as RETRIEVAL_QUERY, which the asymmetry is designed for.
    """

    dim = EMBED_DIM

    def __init__(self, model: str = "gemini-embedding-001", api_key: str | None = None):
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        from google import genai  # lazy

        self._genai = genai
        self._client = genai.Client(api_key=key)
        self._model = model

    def embed(self, texts: Sequence[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            resp = self._embed_batch(batch, task)
            out.extend(l2_normalize(list(e.values[:EMBED_DIM])) for e in resp.embeddings)
        return out

    def _embed_batch(self, batch: list[str], task: str):
        """One batch, with backoff on 429. Free-tier RPM limits are transient, so
        a short wait clears them; a persistent 429 (daily cap) still raises."""
        delay = 2.0
        for attempt in range(4):
            try:
                return self._client.models.embed_content(
                    model=self._model,
                    contents=batch,
                    config=self._genai.types.EmbedContentConfig(
                        output_dimensionality=EMBED_DIM, task_type=task
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                if "429" in str(exc) and attempt < 3:
                    log.warning("embed 429, backing off %.0fs", delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text], task="RETRIEVAL_QUERY")[0]


def build_embedder(kind: str | None = None) -> Embedder:
    """Select an embedder. `kind` overrides the EMBEDDER env var.

    Defaults to Gemini when a GEMINI_API_KEY is present (no download, 1024 dims
    native), else bge-m3 (local, free). 'hashing' must be requested explicitly —
    it is for plumbing tests only and would silently destroy retrieval quality if
    it ever became a default.
    """
    if kind is None:
        kind = os.environ.get("EMBEDDER")
    if kind is None:
        kind = "gemini" if os.environ.get("GEMINI_API_KEY") else "bge"
    kind = kind.lower()
    if kind == "gemini":
        return GeminiEmbedder()
    if kind in {"bge", "bge-m3"}:
        return BGEEmbedder()
    if kind == "voyage":
        return VoyageEmbedder()
    if kind == "hashing":
        log.warning("using HashingEmbedder — retrieval quality will be meaningless")
        return HashingEmbedder()
    raise ValueError(f"unknown embedder: {kind!r}")


def embed_texts(texts: Sequence[str], embedder: Embedder) -> list[list[float]]:
    """Embed with blank-safe handling.

    Empty strings must still yield a vector so positional alignment with the
    caller's segment list is preserved.
    """
    if not texts:
        return []
    cleaned = [t if (t and t.strip()) else " " for t in texts]
    vectors = embedder.embed(cleaned)
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedder returned {len(vectors)} vectors for {len(texts)} texts"
        )
    return vectors


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0

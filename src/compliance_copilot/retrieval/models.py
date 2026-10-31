"""Local embedding and reranking models (loaded once per process).

Both run on the bank's own hardware: document and query text never leaves the
environment for retrieval. BGE-M3 and BGE-reranker-v2-m3 are multilingual models
with strong Thai performance.
"""

from __future__ import annotations

import math
import threading
from functools import lru_cache

from ..config import get_settings

_lock = threading.Lock()


def _device() -> str:
    d = get_settings().device
    if d != "auto":
        return d
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


@lru_cache(maxsize=1)
def embedder():
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(get_settings().embedding_model, device=_device())
    model.max_seq_length = 1024
    return model


@lru_cache(maxsize=1)
def reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(get_settings().reranker_model, device=_device(), max_length=512)


def embed(texts: list[str], batch_size: int = 8, show_progress: bool = False) -> list[list[float]]:
    with _lock:
        vecs = embedder().encode(
            texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=show_progress
        )
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    return embed([text])[0]


def rerank(query: str, passages: list[str], batch_size: int = 8) -> list[float]:
    """Cross-encoder relevance in 0..1 (sigmoid of the raw logit)."""
    if not passages:
        return []
    import torch

    with _lock:
        logits = reranker().predict(
            [(query, p) for p in passages], batch_size=batch_size,
            activation_fn=torch.nn.Identity(), convert_to_numpy=True,
        )
    return [1 / (1 + math.exp(-float(x))) for x in logits]

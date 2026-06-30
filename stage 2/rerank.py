"""Cross-encoder reranker for Stage 2.

Wraps a multilingual cross-encoder (default: BAAI/bge-reranker-v2-m3)
behind a thin API so the rest of stage_2 doesn't see the model details.
"""
from __future__ import annotations

from functools import lru_cache
from sentence_transformers import CrossEncoder


# Multilingual reranker — handles Bulgarian.
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


@lru_cache(maxsize=1)
def get_reranker(model_name: str = DEFAULT_MODEL) -> CrossEncoder:
    return CrossEncoder(model_name, max_length=512)


def rerank(query: str, candidates: list[dict], top_k: int = 5,
           text_field: str = "text", model_name: str = DEFAULT_MODEL) -> list[dict]:
    """Reorder candidates by cross-encoder relevance score.

    Args:
        query: user question
        candidates: list of chunk dicts (must contain `text_field`)
        top_k: how many to keep
        text_field: which field of each candidate holds the text
        model_name: HuggingFace model id

    Returns:
        top_k candidates, sorted by descending relevance.
        Each one gets a `rerank_score` field added.
    """
    if not candidates:
        return []

    model = get_reranker(model_name)
    pairs = [[query, c[text_field]] for c in candidates]
    scores = model.predict(pairs)
    scored = list(zip(candidates, scores))
    scored.sort(key=lambda x: float(x[1]), reverse=True)

    out = []
    for c, s in scored[:top_k]:
        c = dict(c)
        c["rerank_score"] = float(s)
        out.append(c)
    return out

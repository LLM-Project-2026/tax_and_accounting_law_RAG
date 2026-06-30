"""Retrieval evaluation for Stage 2.

Compares two configurations against a golden set:
  A) Dense only            — FAISS top-K
  B) Dense + Rerank        — FAISS top-N → CrossEncoder → top-K

Metrics (per query, then averaged):
  - Hit Rate @K   — did at least one expected article appear in top-K?
  - Recall   @K   — fraction of expected articles found in top-K
  - MRR      @K   — Mean Reciprocal Rank of the first relevant hit
  - nDCG     @K   — discounted gain, rewards higher positions

A chunk is considered relevant if its (law_short, article) tuple is
in the query's `expected` list.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

from retrieve import dense_search, RECALL_K
from rerank import rerank


HERE = Path(__file__).resolve().parent
DEFAULT_GOLDEN = HERE / "golden_set.json"
DEFAULT_OUT = HERE / "evaluation.json"


def is_relevant(chunk: dict, expected: list[list[str]]) -> bool:
    """A chunk matches if its (law_short, article) is in expected."""
    key = [chunk.get("law_short"), str(chunk.get("article"))]
    return any(key == [e[0], str(e[1])] for e in expected)


def per_query_metrics(chunks: list[dict], expected: list[list[str]], k: int) -> dict:
    """Compute Hit@K, Recall@K, MRR, nDCG for a single query."""
    chunks = chunks[:k]
    expected_keys = {(e[0], str(e[1])) for e in expected}

    # Mark relevance per position
    rel_flags = [1 if is_relevant(c, expected) else 0 for c in chunks]

    # Hit Rate — any relevant in top-k?
    hit = 1.0 if any(rel_flags) else 0.0

    # Recall — coverage of unique expected articles
    found_keys = {
        (c["law_short"], str(c["article"]))
        for c, r in zip(chunks, rel_flags) if r
    }
    recall = (len(found_keys & expected_keys) / len(expected_keys)) if expected_keys else 0.0

    # MRR — reciprocal rank of first hit
    mrr = 0.0
    for i, r in enumerate(rel_flags, 1):
        if r:
            mrr = 1.0 / i
            break

    # nDCG@k (binary gains)
    dcg = sum(r / math.log2(i + 1) for i, r in enumerate(rel_flags, 1))
    ideal_hits = min(len(expected_keys), k)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    return {"hit": hit, "recall": recall, "mrr": mrr, "ndcg": ndcg}


def aggregate(rows: list[dict]) -> dict:
    return {
        m: round(statistics.mean(r[m] for r in rows), 4)
        for m in ("hit", "recall", "mrr", "ndcg")
    }


def evaluate(golden: list[dict], recall_k: int, final_k: int) -> dict:
    """Run both modes (dense-only, dense+rerank) and aggregate metrics."""
    print(f"\nRunning evaluation: recall_k={recall_k}  final_k={final_k}")
    print("-" * 60)

    dense_rows, rerank_rows, per_query = [], [], []

    t_dense_total = 0.0
    t_rerank_total = 0.0

    for q in golden:
        t0 = time.time()
        candidates = dense_search(q["query"], k=recall_k)
        t_dense_total += time.time() - t0

        m_dense = per_query_metrics(candidates, q["expected"], k=final_k)

        t0 = time.time()
        reranked = rerank(q["query"], candidates, top_k=final_k)
        t_rerank_total += time.time() - t0
        m_rerank = per_query_metrics(reranked, q["expected"], k=final_k)

        dense_rows.append(m_dense)
        rerank_rows.append(m_rerank)
        per_query.append({
            "id": q["id"],
            "query": q["query"],
            "dense": m_dense,
            "rerank": m_rerank,
        })

        delta = m_rerank["mrr"] - m_dense["mrr"]
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "·")
        print(f"  [{q['id']}] dense MRR={m_dense['mrr']:.2f}  "
              f"→ rerank MRR={m_rerank['mrr']:.2f}  {arrow}")

    n = len(golden)
    summary = {
        "config": {"recall_k": recall_k, "final_k": final_k, "queries": n},
        "dense_only": aggregate(dense_rows),
        "dense_plus_rerank": aggregate(rerank_rows),
        "timing": {
            "dense_total_sec":  round(t_dense_total, 3),
            "rerank_total_sec": round(t_rerank_total, 3),
            "per_query_dense_ms":  round(1000 * t_dense_total / n, 1),
            "per_query_rerank_ms": round(1000 * t_rerank_total / n, 1),
        },
        "per_query": per_query,
    }
    return summary


def print_summary(summary: dict) -> None:
    cfg = summary["config"]
    d = summary["dense_only"]
    r = summary["dense_plus_rerank"]
    t = summary["timing"]

    print()
    print("=" * 60)
    print(f"  RETRIEVAL EVALUATION  ({cfg['queries']} queries)")
    print(f"  Recall depth = {cfg['recall_k']}   Final K = {cfg['final_k']}")
    print("=" * 60)
    print(f"  {'metric':10s}  {'dense':>10s}  {'+rerank':>10s}  {'delta':>10s}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}")
    for m in ("hit", "recall", "mrr", "ndcg"):
        delta = r[m] - d[m]
        sign = "+" if delta >= 0 else ""
        print(f"  {m:10s}  {d[m]:>10.4f}  {r[m]:>10.4f}  {sign}{delta:>9.4f}")
    print()
    print(f"  Latency: dense {t['per_query_dense_ms']} ms/q  •  "
          f"rerank {t['per_query_rerank_ms']} ms/q")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    ap.add_argument("--recall-k", type=int, default=RECALL_K,
                    help="how many candidates to pull from FAISS")
    ap.add_argument("--final-k", type=int, default=5,
                    help="how many to keep after rerank")
    args = ap.parse_args()

    with open(args.golden, encoding="utf-8") as f:
        golden = json.load(f)

    summary = evaluate(golden, recall_k=args.recall_k, final_k=args.final_k)
    print_summary(summary)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nFull report written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

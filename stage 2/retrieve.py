"""Two-stage retrieval for Stage 2:
    1. Dense recall — fetch many candidates from FAISS (default 50)
    2. Cross-encoder rerank — keep the most relevant top_k

This widens the recall surface and then trusts the reranker to bring
the truly relevant chunks to the top.
"""
from __future__ import annotations

import json
import os
import sys

import faiss
from sentence_transformers import SentenceTransformer
from google import genai
from google.genai import types
from dotenv import load_dotenv

from rerank import rerank


load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

embed_model = SentenceTransformer("intfloat/multilingual-e5-small")
index = faiss.read_index("legal_index.faiss")

with open("metadata.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)


# Tunable defaults — wider recall, narrow final context

RECALL_K = 50   # how many candidates to pull from FAISS
FINAL_K = 5     # how many to send to the LLM after rerank


def format_context(chunk: dict) -> str:
    return (
        f"--- ИЗТОЧНИК: {chunk['law_short']}, чл. {chunk['article']} "
        f"({chunk.get('article_title') or ''}) ---\n"
        f"Линк: {chunk['law_url']}\n"
        f"Текст: {chunk['text']}\n"
    )


def dense_search(query: str, k: int = RECALL_K) -> list[dict]:
    """Fetch the top-k chunks from FAISS by cosine similarity."""
    query_text = f"query: {query}"
    qv = embed_model.encode([query_text], normalize_embeddings=True).astype("float32")
    scores, indices = index.search(qv, k)
    out = []
    for score, idx in zip(scores[0], indices[0]):
        if 0 <= idx < len(metadata):
            chunk = dict(metadata[idx])
            chunk["dense_score"] = float(score)
            out.append(chunk)
    return out


def retrieve_chunks(query: str, recall_k: int = RECALL_K,
                    final_k: int = FINAL_K, use_rerank: bool = True) -> list[dict]:
    """Two-stage retrieval: dense recall → rerank → top_k."""
    candidates = dense_search(query, k=recall_k)
    if not candidates:
        return []
    if not use_rerank:
        return candidates[:final_k]
    return rerank(query, candidates, top_k=final_k)


def retrieve_context(query: str, top_k: int = FINAL_K) -> str:
    """Backwards-compatible string context for downstream callers."""
    chunks = retrieve_chunks(query, final_k=top_k)
    return "\n".join(format_context(c) for c in chunks)


def ask_rag(query: str, top_k: int = FINAL_K) -> str:
    chunks = retrieve_chunks(query, final_k=top_k)
    context_str = "\n".join(format_context(c) for c in chunks)

    system_prompt = (
        "Ти си прецизен правен асистент, специализиран в българското законодателство.\n"
        "Отговаряй на въпросите на потребителя изключително и само на базата на предоставения контекст.\n"
        "Ако в контекста няма информация по въпроса, отговори директно: "
        "'Не мога да отговоря на базата на предоставените документи.'\n"
        "Винаги цитирай точно кой закон и кой член използваш за отговора си."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"КОНТЕКСТ:\n{context_str}\n\nВЪПРОС: {query}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
        ),
    )
    return response.text


if __name__ == "__main__":
    question = "Какви са осигурителните вноски за самоосигуряващо се лице?"
    print(f"\nВъпрос: {question}\n" + "-" * 60)
    print("\nИзвлечени чънкове след rerank:")
    for i, c in enumerate(retrieve_chunks(question), 1):
        print(f"  {i}. [{c['law_short']} чл. {c['article']}]  "
              f"dense={c.get('dense_score',0):.3f}  "
              f"rerank={c.get('rerank_score',0):.3f}")
    print("\nОтговор:\n")
    print(ask_rag(question))


sys.modules["retrieve_context"] = retrieve_context

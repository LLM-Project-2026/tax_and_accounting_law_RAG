import json
import os
from functools import lru_cache

# Use only the PyTorch backend; avoids transformers trying to load TensorFlow/Keras,
# which isn't installed in a tf-keras-compatible form. Must be set before the import below.
os.environ.setdefault("USE_TF", "0")

import faiss
from sentence_transformers import SentenceTransformer

# Data lives in the "stage 2" directory; resolve paths relative to this file so
# retrieval works regardless of the current working directory.
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stage 2")
_INDEX_PATH = os.path.join(_DATA_DIR, "legal_index.faiss")
_METADATA_PATH = os.path.join(_DATA_DIR, "metadata.json")
_EMBED_MODEL = "intfloat/multilingual-e5-small"


@lru_cache(maxsize=1)
def _load():
    """Load the embedding model, FAISS index and metadata once per process."""
    model = SentenceTransformer(_EMBED_MODEL)
    index = faiss.read_index(_INDEX_PATH)
    with open(_METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    return model, index, metadata


def _format_context(chunk):
    return (
        f"--- ИЗТОЧНИК: {chunk['law_short']}, чл. {chunk['article']} ({chunk['article_title'] or ''}) ---\n"
        f"Линк: {chunk['law_url']}\n"
        f"Текст: {chunk['text']}\n"
    )


def retrieve_context(query, top_k=3):
    """Return the top-k most relevant legal chunks for `query`, formatted as text."""
    model, index, metadata = _load()
    query_vector = model.encode(
        [f"query: {query}"], normalize_embeddings=True
    ).astype("float32")
    _, indices = index.search(query_vector, top_k)
    chunks = [metadata[idx] for idx in indices[0] if idx < len(metadata)]
    return "\n".join(_format_context(c) for c in chunks)

import json
import os
import faiss
from sentence_transformers import SentenceTransformer


model = SentenceTransformer("intfloat/multilingual-e5-small")

def format_chunk(chunk):
    law_title = chunk.get("law_title", "Нeизвeстeн закон")
    article = chunk.get("article", "-")
    article_title = chunk.get("article_title", "")
    text = chunk.get("text", "")
    
    return f"passage: Закон: {law_title}\nЧлeн: {article} ({article_title})\nТeкст: {text}"

def main():
    jsonl_path = "chunks.jsonl"
    if not os.path.exists(jsonl_path):
        print(f"Грeшка: Липсва файл {jsonl_path}!")
        return

    with open(jsonl_path, "r", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
        
    chunks = [c for c in chunks if not c.get("is_repealed", False)]

    texts_to_embed = [format_chunk(c) for c in chunks]

    embeddings = model.encode(texts_to_embed, batch_size=32, show_progress_bar=True, normalize_embeddings=True)

    # IndexFlatIP(Inner Product) == Cosine Similarity
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings.astype('float32'))

    faiss.write_index(index, "legal_index_free.faiss")
    with open("metadata_free.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
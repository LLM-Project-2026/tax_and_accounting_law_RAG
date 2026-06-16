import json
import faiss
import os
from sentence_transformers import SentenceTransformer
from google import genai
from google.genai import types
from dotenv import load_dotenv


load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


embed_model = SentenceTransformer("intfloat/multilingual-e5-small")
index = faiss.read_index("legal_index.faiss")

with open("metadata.json", "r", encoding="utf-8") as f:
    metadata = json.load(f)

def format_context(chunk):
    return (
        f"--- ИЗТОЧНИК: {chunk['law_short']}, чл. {chunk['article']} ({chunk['article_title'] or ''}) ---\n"
        f"Линк: {chunk['law_url']}\n"
        f"Текст: {chunk['text']}\n"
    )

def ask_rag(query, top_k=3):

    query_text = f"query: {query}"
    query_vector = embed_model.encode([query_text], normalize_embeddings=True).astype('float32')
    

    _, indices = index.search(query_vector, top_k)

    retrieved_chunks = [metadata[idx] for idx in indices[0] if idx < len(metadata)]
    context_str = "\n".join([format_context(c) for c in retrieved_chunks])
    
    # master prompt
    system_prompt = (
        "Ти си прецизен правен асистент, специализиран в българското законодателство.\n"
        "Отговаряй на въпросите на потребителя изключително и само на базата на предоставения контекст.\n"
        "Ако в контекста няма информация по въпроса, отговори директно: 'Не мога да отговоря на базата на предоставените документи.'\n"
        "Винаги цитирай точно кой закон и кой член използваш за отговора си."
    )
    

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=f"КОНТЕКСТ:\n{context_str}\n\nВЪПРОС: {query}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1
        )
    )
    
    return response.text

if __name__ == "__main__":
    question = "Какво знаеш за продажбаа на стоки дистанционно"
    # question = "Разбираш ли от наследство"
    # question = "Каква причина да използвам при напускане на работа заради физически проблем в съответствие с работнечиския кодекс"
    print(f"\nВъпрос: {question}\n" + "-"*50)
    
    answer = ask_rag(question)
    print(f"\nОтговор:\n{answer}")
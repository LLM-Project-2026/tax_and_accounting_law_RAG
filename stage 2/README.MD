# stage_2 — Векторизация, Retrieval и Reranking

Стъпки 3–4 от пайплайна: **векторизация** на нормативните чънкове и
**двустъпков retrieval** (FAISS recall → cross-encoder rerank),
последван от генерация на отговор с цитати.

## Технологичен стек
* **Embeddings:** `intfloat/multilingual-e5-small` (локален, безплатен)
* **Vector Index:** `FAISS` (IndexFlatIP — Cosine Similarity)
* **Reranker:** `BAAI/bge-reranker-v2-m3` (multilingual cross-encoder)
* **LLM:** `Google Gemini 2.5 Flash`
* **Configuration:** `.env`

## Двустъпков retrieval

```
въпрос
   │
   ▼
[1] dense_search          FAISS top-50  (RECALL_K)
   │
   ▼
[2] rerank                cross-encoder → top-5  (FINAL_K)
   │
   ▼
контекст за LLM
```

| Стъпка | Цел | Какво прави |
|---|---|---|
| **Recall** (top-50) | Не изпускай релевантен чънк | Семантично търсене с по-голяма дълбочина |
| **Rerank** (top-5) | Сложи най-релевантните най-горе | Cross-encoder оценява двойката (въпрос, чънк) с по-висока точност |

Параметрите `RECALL_K=50` и `FINAL_K=5` в `retrieve.py` се настройват.

## Файлове

```text
stage 2/
├── prepare.py        — chunks.jsonl → FAISS индекс
├── retrieve.py       — dense_search → rerank → LLM (Gemini)
├── rerank.py         — cross-encoder wrapper
├── evaluate.py       — Recall@K, MRR, Hit Rate, nDCG
├── golden_set.json   — 15 ръчно изградени въпроса с очаквани членове
├── evaluation.json   — генериран отчет
├── legal_index.faiss
└── metadata.json
```

## Метрики за retrieval

Скриптът `evaluate.py` сравнява два режима:

| Режим | Какво прави |
|---|---|
| `dense_only` | само FAISS top-K |
| `dense_plus_rerank` | FAISS top-N → cross-encoder → top-K |

Изчислени метрики (на въпрос, после осреднени):

| Метрика | Какво измерва |
|---|---|
| **Hit Rate @K** | Има ли поне един очакван член в top-K? |
| **Recall @K**   | Каква част от очакваните членове са в top-K? |
| **MRR**         | Колко високо е първият релевантен резултат? (1/ранг) |
| **nDCG @K**     | Качество на ранкирането с тегло към горните позиции |

Един чънк се брои за **релевантен**, ако неговата двойка
`(law_short, article)` присъства в `expected` за съответния въпрос.

## Как се пуска

1. **Конфигурация:** създай `.env`:
   ```text
   GEMINI_API_KEY=твоят_ключ
   ```

2. **Зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Стъпки:**
   ```bash
   # (a) Индексиране — само веднъж при промяна на корпуса
   python prepare.py

   # (b) Кратък тест „въпрос → отговор"
   python retrieve.py

   # (c) Пълно оценяване — сравнява dense vs dense+rerank
   python evaluate.py

   # (d) С персонализирани параметри
   python evaluate.py --recall-k 30 --final-k 3
   ```

## Какво показва `evaluation.json`

```jsonc
{
  "config": { "recall_k": 50, "final_k": 5, "queries": 15 },
  "dense_only":        { "hit": 0.X, "recall": 0.X, "mrr": 0.X, "ndcg": 0.X },
  "dense_plus_rerank": { "hit": 0.X, "recall": 0.X, "mrr": 0.X, "ndcg": 0.X },
  "timing": { "per_query_dense_ms": ..., "per_query_rerank_ms": ... },
  "per_query": [ ... ]   // подробна разбивка
}
```

Очаквана динамика: rerank-ът обикновено повишава **MRR** и **nDCG**
с цената на ~100–300 ms добавена латентност на въпрос. `Recall@K`
расте, само ако rerank-ът „спасява" чънк, който е в top-N но извън
top-K при dense-only.

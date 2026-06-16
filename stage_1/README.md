# stage_1 — Сваляне и трансформация (Студент 1)

Стъпки 1–2 от пайплайна на RAG асистента: **сваляне** и
**трансформация** на нормативната уредба в структурирани чънкове,
плюс отчети за L3 (токенизация) и L6 (качество).

## Какво произвежда този слой

`data/parsed/chunks.jsonl` — една единица на ред, готова за вграждане. Пример:

```json
{
  "id": "ZKPO_124_al2",
  "law_code": "ZKPO",
  "law_short": "ЗКПО",
  "law_title": "Закон за корпоративното подоходно облагане",
  "law_url": "https://lex.bg/laws/ldoc/2135540562",
  "part": "Част втора. КОРПОРАТИВЕН ДАНЪК",
  "chapter": "Глава деветнадесета. ПРЕДОТВРАТЯВАНЕ НА ОТКЛОНЕНИЕ ОТ ДАНЪЧНО ОБЛАГАНЕ",
  "section": null,
  "article": "124",
  "article_title": "...",
  "paragraph": "2",
  "text": "...",
  "char_count": 312,
  "is_repealed": false,
  "fetched_at": "2026-06-14T17:41:..."
}
```

## Корпус

| Закон | Чънкове | Уникални членове |
|---|---:|---:|
| КСО (Кодекс за социално осигуряване) | 2 469 | 554 |
| ЗДДС (Закон за данък върху добавената стойност) | 1 455 | 293 |
| ЗКПО (Закон за корпоративното подоходно облагане) | 1 282 | 352 |
| ЗДДФЛ (Закон за данъците върху доходите на физическите лица) | 412 | 102 |
| ЗС (Закон за счетоводството) | 279 | 87 |
| **Общо** | **5 897** | **1 388** |

## Стъпки на пайплайна

```text
lex.bg HTML ──▶ data/raw/<CODE>__<YYYYMMDD>.html
                         │
                         ▼
                ingest.parse  ── нормализация + разделяне по член/алинея
                         │
                         ▼
                data/parsed/chunks.jsonl
                         │
                         ├─▶ ingest.quality    → reports/quality.json + L6 отчет
                         └─▶ analysis.tokenizers → reports/tokenizers.json + L3 отчет
```

## Структура на репото

```
RAG_Legal/stage_1/
├── requirements.txt
├── ingest/
│   ├── laws.py            ← регистър на 5-те закона
│   ├── download.py        ← scraper (lex.bg рейт-лимитва, тества)
│   ├── import_local.py    ← внасяне на ръчно запазен HTML (когато scraper-ът е блокиран)
│   ├── parse.py           ← HTML → article/paragraph chunks
│   └── quality.py         ← L6 — критерии за качество
├── analysis/
│   └── tokenizers.py      ← L3 — tiktoken vs XLM-R сравнение
├── data/
│   ├── raw/               ← суров HTML + manifest.json
│   └── parsed/chunks.jsonl
└── reports/
    ├── L3_tokenizers.md
    ├── L6_quality.md
    ├── quality.json
    └── tokenizers.json
```

## Как се пуска

```bash
# 1. Зависимости
py -3 -m pip install -r requirements.txt

# 2. Алтернатива: запазване страниците от Chrome (Save complete page)
py -3 -m ingest.import_local

# 3. Парсване
py -3 -m ingest.parse

# 4. Качество (L6)
py -3 -m ingest.quality

# 5. Токенизация (L3)
py -3 -m analysis.tokenizers
```

## Интерфейс към Студент 2

Получаваме `data/parsed/chunks.jsonl`:

- `id` — уникален идентификатор `<LAW>_<ART>[_al<N>]`
- `text` — нормализиран съдържателен текст за embedding
- `law_code`, `law_short`, `law_title`, `law_url` — за citation back-reference
- `part`, `chapter`, `section`, `article`, `article_title`, `paragraph` — за филтриране и rerank по контекст
- `is_repealed` — препоръчително да се изключи от индексиране
- `char_count` — за вторично разделение, ако моделът не побира

## Известни ограничения

- **Празни членове в КСО** (125 случая) — самият закон ги съдържа без
  тяло; виж `reports/L6_quality.md`.
- **Дубликати на „(Отм.)" чънкове** — реално припокриване в текста, не
  бъг; виж `reports/L6_quality.md`.

## Следваща стъпка (предвидена с план A)

Към всеки чънк ще се добави поле `refs_out` — списък от извличания към
други нормативни актове (`["LEGAL:чл:26_ЗКПО", "LEGAL:чл:6_ЗДДС", ...]`),
полезни за hybrid search. Реализира се в отделен модул,
без промяна на текущия парсер.

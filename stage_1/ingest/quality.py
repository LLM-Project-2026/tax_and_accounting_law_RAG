"""Data-quality checks on data/parsed/chunks.jsonl .

Reports:
- Total chunks and articles per law.
- Empty / near-empty chunks.
- Duplicate chunks (same normalized text in different IDs).
- Chunks flagged as repealed.
- Articles with no detected paragraph splitting (kept as single chunk).
- Char-length distribution per chunk and per article.
- Missing hierarchy (article without part/chapter).

Outputs:
- A short text report to stdout.
- A machine-readable JSON report to reports/quality.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "parsed" / "chunks.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "quality.json"

log = logging.getLogger("quality")

EMPTY_THRESHOLD = 30        # chars
LONG_THRESHOLD = 2000       # chars — flag as a candidate for sub-splitting


def load_chunks(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def text_signature(text: str) -> str:
    norm = " ".join(text.split()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def quartiles(values: list[int]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "min": s[0],
        "p25": s[int(0.25 * n)],
        "median": s[n // 2],
        "p75": s[int(0.75 * n)],
        "p95": s[int(0.95 * n)],
        "max": s[-1],
        "mean": round(statistics.mean(s), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    chunks = load_chunks(Path(args.input))
    if not chunks:
        log.error("No chunks loaded from %s", args.input)
        return 1
    log.info("Loaded %d chunks", len(chunks))

    by_law: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_law[c["law_code"]].append(c)

    # Empty / near-empty
    empty = [c for c in chunks if c["char_count"] < EMPTY_THRESHOLD]

    # Duplicates (same text in multiple chunks)
    sigs: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        sigs[text_signature(c["text"])].append(c["id"])
    duplicates = {sig: ids for sig, ids in sigs.items() if len(ids) > 1}
    dup_total_ids = sum(len(ids) for ids in duplicates.values())

    # Repealed
    repealed = [c for c in chunks if c.get("is_repealed")]

    # Hierarchy coverage
    no_part = sum(1 for c in chunks if not c.get("part"))
    no_chapter = sum(1 for c in chunks if not c.get("chapter"))

    # Length distribution
    char_q = quartiles([c["char_count"] for c in chunks])

    # Per-article: how many split into paragraphs vs single
    article_para_count: dict[tuple[str, str], int] = Counter()
    for c in chunks:
        article_para_count[(c["law_code"], c["article"])] += 1
    single_para_articles = sum(1 for v in article_para_count.values() if v == 1)
    multi_para_articles = sum(1 for v in article_para_count.values() if v > 1)

    # Per-law breakdown
    per_law: dict[str, dict] = {}
    for code, cs in by_law.items():
        article_ids = {c["article"] for c in cs}
        per_law[code] = {
            "short": cs[0]["law_short"],
            "title": cs[0]["law_title"],
            "chunks": len(cs),
            "unique_articles": len(article_ids),
            "repealed_chunks": sum(1 for c in cs if c.get("is_repealed")),
            "empty_chunks": sum(1 for c in cs if c["char_count"] < EMPTY_THRESHOLD),
            "long_chunks_ge2000": sum(1 for c in cs if c["char_count"] >= LONG_THRESHOLD),
            "char_quartiles": quartiles([c["char_count"] for c in cs]),
        }

    # Article-number gaps (sanity check: did we drop any articles?)
    gaps: dict[str, list[int]] = {}
    for code, cs in by_law.items():
        nums = set()
        for c in cs:
            a = c["article"]
            base = "".join(ch for ch in a if ch.isdigit())
            if base:
                nums.add(int(base))
        if nums:
            expected = set(range(min(nums), max(nums) + 1))
            missing = sorted(expected - nums)
            if missing:
                gaps[code] = missing[:30]  # cap output

    # Final report
    report = {
        "totals": {
            "chunks": len(chunks),
            "laws": len(by_law),
            "unique_articles": len(article_para_count),
            "empty_chunks_under_30ch": len(empty),
            "duplicate_text_groups": len(duplicates),
            "duplicate_chunks_total": dup_total_ids,
            "repealed_chunks": len(repealed),
            "no_part_metadata": no_part,
            "no_chapter_metadata": no_chapter,
            "articles_kept_as_single_chunk": single_para_articles,
            "articles_split_into_paragraphs": multi_para_articles,
            "char_quartiles": char_q,
        },
        "per_law": per_law,
        "article_number_gaps": gaps,
        "examples": {
            "empty_chunks_first_5": [
                {"id": c["id"], "law": c["law_short"], "text": c["text"]}
                for c in empty[:5]
            ],
            "duplicate_groups_first_5": [
                {"ids": ids, "preview": next(c for c in chunks if c["id"] == ids[0])["text"][:120]}
                for ids in list(duplicates.values())[:5]
            ],
            "repealed_first_5": [
                {"id": c["id"], "law": c["law_short"], "text": c["text"][:120]}
                for c in repealed[:5]
            ],
        },
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Console summary
    t = report["totals"]
    print()
    print("=" * 70)
    print("DATA QUALITY REPORT")
    print("=" * 70)
    print(f"  Chunks:                       {t['chunks']}")
    print(f"  Laws:                         {t['laws']}")
    print(f"  Unique articles:              {t['unique_articles']}")
    print(f"  Empty chunks (<{EMPTY_THRESHOLD} chars):       {t['empty_chunks_under_30ch']}")
    print(f"  Duplicate text groups:        {t['duplicate_text_groups']}")
    print(f"  Duplicate chunks total:       {t['duplicate_chunks_total']}")
    print(f"  Repealed chunks:              {t['repealed_chunks']}")
    print(f"  Missing 'part' metadata:      {t['no_part_metadata']}")
    print(f"  Missing 'chapter' metadata:   {t['no_chapter_metadata']}")
    print(f"  Articles kept as single:      {t['articles_kept_as_single_chunk']}")
    print(f"  Articles split by ал.:        {t['articles_split_into_paragraphs']}")
    print(f"  Char length quartiles:        {t['char_quartiles']}")
    print()
    print("Per-law:")
    for code, p in per_law.items():
        print(f"  {p['short']:6s}  chunks={p['chunks']:>5d}  arts={p['unique_articles']:>4d}  "
              f"repealed={p['repealed_chunks']:>3d}  empty={p['empty_chunks']:>3d}  "
              f"long={p['long_chunks_ge2000']:>3d}")
    if gaps:
        print()
        print("Article number gaps (suggesting missing articles):")
        for code, missing in gaps.items():
            print(f"  {code}: {missing[:15]}{'...' if len(missing) > 15 else ''}")
    print()
    print(f"Full report written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

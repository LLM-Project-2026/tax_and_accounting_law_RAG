"""Parse the locally-saved lex.bg HTML files into structured chunks.

Strategy:
- Walk the DOM in document order; track the current Part / Chapter / Section.
- For each <div class="Article">, extract article number, article title,
  and body text.
- If the body contains explicit paragraph markers "(N)", split into one
  chunk per paragraph. Otherwise the whole article body is one chunk.
- Normalize Cyrillic text (NFC, common whitespace fixes).
- Write data/parsed/chunks.jsonl — one chunk per line with full metadata.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PARSED_DIR = ROOT / "data" / "parsed"

log = logging.getLogger("parse")


# Text normalization

_WS_REPLACEMENTS = {
    " ": " ",   # non-breaking space
    " ": " ",   # thin space
    "​": "",    # zero-width space
    "–": "-",   # en-dash
    "—": "-",   # em-dash
    "−": "-",   # minus sign
}


def normalize_text(text: str) -> str:
    """NFC + whitespace cleanup."""
    text = unicodedata.normalize("NFC", text)
    for k, v in _WS_REPLACEMENTS.items():
        text = text.replace(k, v)
    # collapse runs of whitespace, but preserve a single space
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()



# Article extraction

ARTICLE_NUM_RE = re.compile(r"Чл\.\s*(\d+[а-я]?)", re.UNICODE)

# Paragraph markers: "(1)", "(2)", ...; sometimes "(1а)".
# Match at start of segment OR after sentence break — but to be safe we
# anchor on " (N) " inside the body and split on it.
PARA_RE = re.compile(r"(?:^|\s)\((\d+[а-я]?)\)\s+", re.UNICODE)

REPEALED_HINTS = (
    "(Отм.",
    "(отм.",
    "Отменен",
    "отменена",
)


def is_repealed(text: str) -> bool:
    head = text[:200]
    return any(h in head for h in REPEALED_HINTS)


def article_button_strip(article: Tag) -> None:
    """Remove lex.bg's toolbar links from an Article element in-place."""
    for p in article.find_all("p", class_="buttons"):
        p.decompose()


def extract_article_pieces(article: Tag) -> tuple[str | None, str | None, str]:
    """Return (article_number, article_title, body_text) for an Article div.

    article_number — string like "1", "10а" (without "Чл." prefix).
    article_title  — short title from the <div class="Title"> immediately
                     above the "<b>Чл. N.</b>" marker, if present.
    body_text      — the article body, normalized, with the inline title
                     and number stripped from the start.
    """
    article_button_strip(article)

    # Article title appears as a Title element inside or just before
    # the article element. lex.bg places it as a child Title div.
    title_el = article.find(class_="Title")
    article_title = None
    if title_el:
        article_title = normalize_text(title_el.get_text(" ", strip=True))
        # Remove from tree so it doesn't pollute body extraction.
        title_el.decompose()

    full_text = normalize_text(article.get_text(" ", strip=True))

    # Extract "Чл. N" / "Чл. Nа"
    m = ARTICLE_NUM_RE.search(full_text)
    article_number = m.group(1) if m else None

    # Strip leading "Чл. N." from body
    if m:
        body = full_text[m.end():]
        # remove leading period or whitespace
        body = re.sub(r"^[\.\s]+", "", body)
    else:
        body = full_text

    return article_number, article_title, body


def split_by_paragraph(body: str) -> list[tuple[str | None, str]]:
    """Split article body by "(N)" paragraph markers.

    Returns a list of (paragraph_label, paragraph_text). If no markers are
    found, returns a single (None, body) entry.
    """
    # Find all paragraph marker positions.
    positions: list[tuple[int, int, str]] = []
    for m in PARA_RE.finditer(body):
        positions.append((m.start(), m.end(), m.group(1)))

    if not positions:
        return [(None, body.strip())]

    # If the first marker is not at the very beginning, the prefix is
    # un-numbered preamble — sometimes a leading "(Изм. ...)" history note
    # followed by the actual text. We keep it as a "pre" segment only if
    # it has real content.
    out: list[tuple[str | None, str]] = []
    first_start = positions[0][0]
    prefix = body[:first_start].strip()
    if prefix and len(prefix) > 20:
        out.append((None, prefix))

    for i, (start, end, label) in enumerate(positions):
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        seg = body[end:next_start].strip()
        if seg:
            out.append((label, seg))

    return out



# Main walk


HIERARCHY_CLASSES = ("Part", "Heading", "Section", "Article")


def walk_law(soup: BeautifulSoup) -> list[dict]:
    """Walk the document in order, yielding raw article records.

    Each record carries the current Part / Chapter / Section as context.
    """
    state = {"part": None, "chapter": None, "section": None}
    records: list[dict] = []

    # The lex.bg layout puts all of Part/Heading/Section/Article as siblings
    # under the main content. We grab all of them in document order.
    elements = soup.find_all(class_=lambda c: c in HIERARCHY_CLASSES) \
        if False else soup.find_all(
            lambda tag: tag.has_attr("class") and any(
                cls in HIERARCHY_CLASSES for cls in tag.get("class", [])
            )
        )

    for el in elements:
        classes = el.get("class", [])
        text = normalize_text(el.get_text(" ", strip=True))

        if "Part" in classes:
            state["part"] = text
            state["chapter"] = None
            state["section"] = None
            continue
        if "Heading" in classes:
            state["chapter"] = text
            state["section"] = None
            continue
        if "Section" in classes:
            state["section"] = text
            continue
        if "Article" in classes:
            # Articles are deep — skip if this Article is nested inside another
            # Article we already processed (defensive).
            parent_article = el.find_parent(class_="Article")
            if parent_article is not None and parent_article is not el:
                continue
            number, title, body = extract_article_pieces(el)
            if number is None:
                continue
            records.append({
                "part": state["part"],
                "chapter": state["chapter"],
                "section": state["section"],
                "article_number": number,
                "article_title": title,
                "body": body,
                "lex_id": el.get("id"),
            })

    return records


def parse_one_law(html_path: Path, law_meta: dict) -> list[dict]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "lxml")

    # Document title (sanity check)
    td = soup.find(class_="TitleDocument")
    doc_title = normalize_text(td.get_text(" ", strip=True)) if td else None

    raw_records = walk_law(soup)
    log.info("  %s: %d raw articles", law_meta["short"], len(raw_records))

    chunks: list[dict] = []
    for rec in raw_records:
        article_no = rec["article_number"]
        body = rec["body"]
        repealed = is_repealed(body)

        paragraphs = split_by_paragraph(body)

        for para_label, para_text in paragraphs:
            chunk_id_parts = [law_meta["code"], article_no]
            if para_label:
                chunk_id_parts.append(f"al{para_label}")
            chunk_id = "_".join(chunk_id_parts)

            chunks.append({
                "id": chunk_id,
                "law_code": law_meta["code"],
                "law_short": law_meta["short"],
                "law_title": law_meta["title"],
                "law_url": law_meta["url"],
                "doc_title_seen": doc_title,
                "part": rec["part"],
                "chapter": rec["chapter"],
                "section": rec["section"],
                "article": article_no,
                "article_title": rec["article_title"],
                "paragraph": para_label,
                "text": para_text,
                "char_count": len(para_text),
                "is_repealed": repealed,
                "lex_id": rec["lex_id"],
                "fetched_at": law_meta.get("fetched_at"),
            })

    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PARSED_DIR / "chunks.jsonl"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    manifest_path = RAW_DIR / "manifest.json"
    if not manifest_path.exists():
        log.error("Manifest not found: %s", manifest_path)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)

    total = 0
    by_law: dict[str, int] = {}
    with out_path.open("w", encoding="utf-8") as f:
        for code, meta in manifest.items():
            html_path = RAW_DIR / meta["file"]
            if not html_path.exists():
                log.warning("Missing HTML for %s: %s", code, html_path)
                continue
            log.info("Parsing %s ...", meta["short"])
            chunks = parse_one_law(html_path, {**meta, "code": code})
            by_law[code] = len(chunks)
            for ch in chunks:
                f.write(json.dumps(ch, ensure_ascii=False) + "\n")
                total += 1

    log.info("Wrote %d chunks to %s", total, out_path)
    for code, n in by_law.items():
        log.info("  %s: %d chunks", code, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

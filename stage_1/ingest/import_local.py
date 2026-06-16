from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path

from .laws import LAWS

log = logging.getLogger("import_local")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"


def title_key(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalpha())


_NORMALIZED_RE = __import__("re").compile(r"^([A-Z]+)__(\d{8})\.html$")


def find_local_html() -> list[Path]:
    candidates: list[Path] = []
    for d in (ROOT, RAW_DIR):
        if d.exists():
            candidates.extend(p for p in d.glob("*.html") if p.is_file())
    return [p for p in candidates if not _NORMALIZED_RE.match(p.name)]


def find_normalized_html() -> list[tuple[Path, str, str]]:
    out: list[tuple[Path, str, str]] = []
    if not RAW_DIR.exists():
        return out
    valid_codes = {law["code"] for law in LAWS}
    for p in RAW_DIR.glob("*.html"):
        m = _NORMALIZED_RE.match(p.name)
        if m and m.group(1) in valid_codes:
            out.append((p, m.group(1), m.group(2)))
    return out


def adopt_normalized(manifest: dict) -> int:
    laws_by_code = {law["code"]: law for law in LAWS}
    adopted = 0
    for path, code, date_str in find_normalized_html():
        if code in manifest:
            continue
        law = laws_by_code[code]
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        manifest[code] = {
            "short": law["short"],
            "title": law["title"],
            "url": law["url"],
            "fetched_at": dt.datetime.fromtimestamp(path.stat().st_mtime)
                            .isoformat(timespec="seconds"),
            "file": path.name,
            "sha256": sha,
            "bytes": len(raw),
            "source": "adopted-from-data-raw",
        }
        log.info("  adopted %s from data/raw: %s", law["short"], path.name)
        adopted += 1
    return adopted


def match_law_by_name(filename: str) -> dict | None:
    fkey = title_key(filename)
    for law in LAWS:
        tkey = title_key(law["title"])
        # match if the filename contains the law title (ignoring case/spaces)
        if tkey in fkey:
            return law
    return None


def match_law_by_content(html: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    td = soup.find(class_="TitleDocument")
    if not td:
        return None
    ikey = title_key(td.get_text(" ", strip=True))
    for law in LAWS:
        if title_key(law["title"]) in ikey:
            return law
    return None


def match_law(filename: str, html: str) -> dict | None:
    return match_law_by_name(filename) or match_law_by_content(html)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().strftime("%Y%m%d")
    manifest_path = RAW_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) \
        if manifest_path.exists() else {}

    # Drop stale manifest entries whose file no longer exists.
    stale = [code for code, m in manifest.items()
             if not (RAW_DIR / m["file"]).exists()]
    for code in stale:
        log.warning("Manifest entry for %s points to missing file %s — dropping",
                    code, manifest[code]["file"])
        del manifest[code]

    # Pick up any already-normalized files in data/raw/ that are missing
    # from the manifest (recovers from a deleted manifest.json).
    adopted = adopt_normalized(manifest)
    if adopted:
        log.info("Adopted %d normalized file(s) from data/raw/", adopted)

    local = find_local_html()
    log.info("Found %d browser-saved .html files to import", len(local))

    moved = 0
    for src in local:
        # Detect declared charset (lex.bg uses windows-1251), decode first
        # so we can fall back to matching by the law title inside the file.
        raw = src.read_bytes()
        import re as _re
        m = _re.search(rb'charset=["\']?([\w-]+)', raw[:4000], _re.I)
        enc = m.group(1).decode("ascii").lower() if m else "utf-8"
        try:
            html = raw.decode(enc, errors="replace")
        except LookupError:
            html = raw.decode("utf-8", errors="replace")
        # Re-declare as utf-8 in the saved copy so downstream tools don't trip.
        html = _re.sub(
            r'charset=["\']?[\w-]+',
            'charset=utf-8',
            html,
            count=1,
            flags=_re.I,
        )

        law = match_law(src.name, html)
        if not law:
            log.warning("  skip (no match): %s", src.name)
            continue
        out = RAW_DIR / f"{law['code']}__{today}.html"
        out.write_text(html, encoding="utf-8")
        sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
        manifest[law["code"]] = {
            "short": law["short"],
            "title": law["title"],
            "url": law["url"],
            "fetched_at": dt.datetime.fromtimestamp(src.stat().st_mtime)
                            .isoformat(timespec="seconds"),
            "file": out.name,
            "sha256": sha,
            "bytes": len(html),
            "source": "manual-browser-save",
        }
        log.info("  %s -> %s (%d bytes)", law["short"], out.name, len(html))
        moved += 1

    # Report missing laws
    have = set(manifest.keys())
    missing = [law["short"] for law in LAWS if law["code"] not in have]
    if missing:
        log.warning("Missing laws (no local file matched): %s", ", ".join(missing))

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Manifest written. Total laws ingested: %d", moved)
    return 0


if __name__ == "__main__":
    sys.exit(main())

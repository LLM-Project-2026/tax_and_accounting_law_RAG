"""
Stages:
  1. ingest.import_local   — pick up any raw .html files (root or data/raw/)
                             and normalize them into data/raw/<CODE>__<DATE>.html
  2. ingest.parse          — produce data/parsed/chunks.jsonl
  3. ingest.quality        — write reports/quality.json (+ console summary)
"""
from __future__ import annotations

import argparse
import logging
import sys
from importlib import import_module


STAGES = [
    ("ingest.import_local", "Import local HTML → data/raw/"),
    ("ingest.parse",        "Parse → data/parsed/chunks.jsonl"),
    ("ingest.quality",      "Quality report (L6)"),
]


def run_stage(module_name: str) -> int:
    mod = import_module(module_name)
    return mod.main()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    for i, (mod_name, label) in enumerate(STAGES, 1):
        print()
        print("=" * 72)
        print(f"  STAGE {i}/{len(STAGES)}: {label}")
        print(f"  → {mod_name}")
        print("=" * 72)
        # Some module main()s parse argv themselves; reset it so they pick defaults.
        sys.argv = [mod_name]
        rc = run_stage(mod_name)
        if rc != 0:
            print(f"\n*** Stage {mod_name} failed with exit code {rc}. Stopping.")
            return rc

    print()
    print("Pipeline finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

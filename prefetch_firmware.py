"""
Pre-populate firmware_versions for every vendor in the registry.

For each vendor in vendors.json:
  1. Skip if a Tier-1 fetcher already populates it (MikroTik/Ubiquiti/NVIDIA).
  2. Skip if any row already exists for that vendor in firmware_versions.
  3. Run live_firmware_lookup(vendor) — this searches the web for the
     vendor's firmware page, extracts version + date + notes URL, and
     caches it.

Run sequentially (not parallel) to stay polite to Startpage / Mojeek and
to avoid blowing through their rate limits.

Usage:
    python3 prefetch_firmware.py           # do all 134
    python3 prefetch_firmware.py 20        # stop after 20
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path

from vendor_registry import by_canonical
from live_firmware import live_firmware_lookup

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

DB = Path(__file__).parent / "data" / "switches.db"
TIER1_SKIP = {"MikroTik", "Ubiquiti", "NVIDIA"}   # already covered by Tier-1


def _already_have(vendor: str) -> bool:
    con = sqlite3.connect(DB)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM firmware_versions WHERE vendor=?",
            (vendor,),
        ).fetchone()[0]
        return n > 0
    finally:
        con.close()


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    vendors = list(by_canonical().values())
    if limit:
        vendors = vendors[:limit]

    total = len(vendors)
    hits, misses, skipped = 0, 0, 0
    t0 = time.time()

    print(f"Pre-fetching firmware for {total} vendors "
          f"(sequential, ~9s deadline each, ~{total*9//60} min worst case)")
    print("-" * 60)

    for i, entry in enumerate(vendors, 1):
        name = entry.get("name", "")
        if not name:
            continue
        if name in TIER1_SKIP:
            print(f"  [{i:3d}/{total}] {name:34s} SKIP — Tier-1 fetcher")
            skipped += 1
            continue
        if _already_have(name):
            print(f"  [{i:3d}/{total}] {name:34s} SKIP — already cached")
            skipped += 1
            continue

        try:
            rec = live_firmware_lookup(name, vendor_hint=name,
                                       deadline_sec=8.0)
        except Exception as e:  # pragma: no cover
            print(f"  [{i:3d}/{total}] {name:34s} ERROR {type(e).__name__}")
            misses += 1
            continue

        if rec:
            tail = f" ({rec.release_date})" if rec.release_date else ""
            print(f"  [{i:3d}/{total}] {name:34s} OK   v{rec.version}{tail}")
            hits += 1
        else:
            print(f"  [{i:3d}/{total}] {name:34s} ---  no version found")
            misses += 1

    elapsed = time.time() - t0
    print("-" * 60)
    print(f"Done in {elapsed/60:.1f} min")
    print(f"  hits:    {hits}")
    print(f"  misses:  {misses}")
    print(f"  skipped: {skipped}")
    print(f"  total:   {hits + misses + skipped}")


if __name__ == "__main__":
    main()

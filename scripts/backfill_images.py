"""
One-time backfill of `image_url` for switches that don't have one.

For every record with an HTML (non-PDF) datasheet_url and no image_url,
fetch the page and extract a product image using the existing
scrapers.parsers.find_product_image (og:image -> JSON-LD -> ranked <img>).
Results are written incrementally so an interrupted run loses nothing.

Run (from the project root):
    python3 scripts/backfill_images.py
"""
import concurrent.futures
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from live_extract import fetch_url
from scrapers.parsers import find_product_image

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "switches.db"
MAX_WORKERS = 8
TIMEOUT = 8


def targets(conn) -> list[tuple[int, str, str, str]]:
    rows = conn.execute(
        "SELECT id, vendor, model, datasheet_url FROM switches "
        "WHERE (image_url IS NULL OR image_url = '') "
        "AND datasheet_url != '' "
        "AND lower(datasheet_url) NOT LIKE '%.pdf'"
    ).fetchall()
    return [tuple(r) for r in rows]


def resolve(row: tuple[int, str, str, str]) -> tuple[int, str, str | None]:
    _id, vendor, model, url = row
    content = fetch_url(url, timeout=TIMEOUT)
    if not content:
        return _id, f"{vendor} {model}", None
    try:
        html = content.decode("utf-8", errors="replace")
        return _id, f"{vendor} {model}", find_product_image(html, base_url=url)
    except Exception:
        return _id, f"{vendor} {model}", None


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    todo = targets(conn)
    total = len(todo)
    print(f"Backfilling images for {total} records "
          f"({MAX_WORKERS} workers)...\n", flush=True)

    found = done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for _id, name, img in ex.map(resolve, todo):
            done += 1
            if img:
                conn.execute(
                    "UPDATE switches SET image_url = ? WHERE id = ?",
                    (img, _id),
                )
                conn.commit()
                found += 1
                print(f"[{done}/{total}] ✓ {name} -> {img[:80]}", flush=True)
            else:
                print(f"[{done}/{total}] · {name} (no image found)",
                      flush=True)

    remaining = conn.execute(
        "SELECT count(*) FROM switches "
        "WHERE image_url IS NULL OR image_url = ''"
    ).fetchone()[0]
    conn.close()
    print(f"\nDone. Resolved {found}/{total}. "
          f"Records still without an image: {remaining} "
          f"(includes {35} PDF-only datasheets).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

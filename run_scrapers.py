"""
Run scrapers and ingest results into the DB.

Usage:
    python run_scrapers.py                       # run all vendors
    python run_scrapers.py ubiquiti mikrotik     # run a subset
    python run_scrapers.py --limit 10 ubiquiti   # limit pages per vendor
    python run_scrapers.py --dry-run ubiquiti    # don't write to DB
    python run_scrapers.py --rebuild             # rebuild DB from seed + scrapers

The HTTP layer caches every fetched page under ./data_cache/<vendor>/,
so reruns are fast and you can iterate on the parsers without hammering
vendor sites. Delete the cache dir to force a fresh crawl.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scrapers import REGISTRY, upsert_records


def setup_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    ap = argparse.ArgumentParser(description="Run switch spec scrapers")
    ap.add_argument(
        "vendors", nargs="*",
        help=f"Vendors to scrape (default: all). Available: {', '.join(REGISTRY)}",
    )
    ap.add_argument("--limit", type=int, help="Max models per vendor")
    ap.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    ap.add_argument("--rebuild", action="store_true",
                    help="Rebuild DB from seed_data.json before scraping")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("run")

    if args.rebuild:
        log.info("Rebuilding DB from seed data...")
        import build_db
        build_db.build()

    targets = args.vendors or list(REGISTRY.keys())
    unknown = [v for v in targets if v not in REGISTRY]
    if unknown:
        log.error("Unknown vendors: %s", unknown)
        log.error("Available: %s", list(REGISTRY))
        sys.exit(1)

    grand_total = 0
    summary = []
    for vendor in targets:
        cls = REGISTRY[vendor]
        scraper = cls()
        try:
            records = scraper.run(limit=args.limit)
        except Exception as e:
            log.exception("[%s] crashed: %s", vendor, e)
            summary.append((vendor, "ERROR", 0))
            continue

        if records and not args.dry_run:
            n = upsert_records(records)
            summary.append((vendor, "ok", n))
            grand_total += n
        elif records and args.dry_run:
            summary.append((vendor, "dry-run", len(records)))
        else:
            summary.append((vendor, "no records", 0))

    log.info("=" * 60)
    log.info("Summary:")
    for vendor, status, n in summary:
        log.info("  %-12s %-12s %d records", vendor, status, n)
    log.info("Total written: %d", grand_total)


if __name__ == "__main__":
    main()

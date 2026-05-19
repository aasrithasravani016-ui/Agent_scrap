"""
Fetch firmware version data from public vendor sources.

Usage:
    python fetch_firmware.py                 # all public vendors
    python fetch_firmware.py mikrotik        # one vendor
    python fetch_firmware.py mikrotik -v     # verbose
"""
from __future__ import annotations

import argparse
import logging
import sys

from firmware_fetchers import REGISTRY, upsert_firmware


def main():
    p = argparse.ArgumentParser(description="Fetch firmware version data")
    p.add_argument(
        "vendors", nargs="*",
        help=f"Vendors to fetch (default: all). Available: {', '.join(REGISTRY)}",
    )
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    from logging_config import setup_logging
    setup_logging(verbose=args.verbose)
    log = logging.getLogger("fetch_firmware")

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
        fetcher = cls()
        try:
            records = fetcher.run()
        except Exception as e:
            log.exception("[%s] crashed: %s", vendor, e)
            summary.append((vendor, "ERROR", 0))
            continue

        if records and not args.dry_run:
            n = upsert_firmware(records)
            summary.append((vendor, "ok", n))
            grand_total += n
        elif records and args.dry_run:
            summary.append((vendor, "dry-run", len(records)))
        else:
            summary.append((vendor, "no data", 0))

    log.info("=" * 60)
    log.info("Firmware fetch summary:")
    for vendor, status, n in summary:
        log.info("  %-12s %-12s %d versions", vendor, status, n)
    log.info("Total written: %d", grand_total)


if __name__ == "__main__":
    main()

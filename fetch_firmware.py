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


def _run_nvd(only_vendor: str | None, dry_run: bool, log):
    """Run the NIST NVD security-advisory fetcher (separate from
    firmware_fetchers because it populates security_advisories, not
    firmware_versions)."""
    from scrapers.nvd_fetcher import NvdFetcher, upsert_advisories
    fetcher = NvdFetcher(only_vendor=only_vendor)
    try:
        recs = fetcher.run()
    except Exception as e:
        log.exception("[nvd] crashed: %s", e)
        return ("nvd", "ERROR", 0)
    if not recs:
        return ("nvd", "no data", 0)
    if dry_run:
        return ("nvd", "dry-run", len(recs))
    n = upsert_advisories(recs)
    return ("nvd", "ok", n)


def _run_kev(dry_run: bool, log):
    """Run the CISA KEV overlay — flips the actively_exploited flag on
    any of our cached CVEs that CISA has marked as actively exploited
    in the wild."""
    from scrapers.cisa_kev_fetcher import fetch_kev_catalog, apply_overlay
    catalog = fetch_kev_catalog()
    if not catalog:
        return ("kev", "no data", 0)
    if dry_run:
        return ("kev", "dry-run", len(catalog))
    matched, total = apply_overlay(catalog)
    return ("kev", f"ok ({matched}/{total} matched)", matched)


def main():
    available = list(REGISTRY.keys()) + ["nvd", "kev"]
    p = argparse.ArgumentParser(description="Fetch firmware version data")
    p.add_argument(
        "vendors", nargs="*",
        help=(f"Vendors to fetch (default: all). Available: "
              f"{', '.join(available)}. "
              "Use 'nvd' to pull CVE/security-advisory data from NIST NVD "
              "for vendors whose release notes are login-gated. "
              "Use 'kev' to overlay CISA's actively-exploited flag "
              "(requires 'nvd' to have been run first)."),
    )
    p.add_argument(
        "--nvd-vendor", default=None,
        help="When fetching 'nvd', restrict to one display vendor "
             "(e.g. 'aruba', 'cisco', 'juniper').",
    )
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    from logging_config import setup_logging
    setup_logging(verbose=args.verbose)
    log = logging.getLogger("fetch_firmware")

    targets = args.vendors or available
    unknown = [v for v in targets if v not in available]
    if unknown:
        log.error("Unknown vendors: %s", unknown)
        log.error("Available: %s", available)
        sys.exit(1)

    grand_total = 0
    summary = []
    for vendor in targets:
        if vendor == "nvd":
            summary.append(_run_nvd(args.nvd_vendor, args.dry_run, log))
            grand_total += summary[-1][2]
            continue
        if vendor == "kev":
            summary.append(_run_kev(args.dry_run, log))
            grand_total += summary[-1][2]
            continue

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
        unit = "advisories" if vendor == "nvd" else "versions"
        log.info("  %-12s %-12s %d %s", vendor, status, n, unit)
    log.info("Total written: %d", grand_total)


if __name__ == "__main__":
    main()

"""
Live firmware fallback — pointer tier for vendors without a dedicated
fetcher. Architecture mirrors live_extract.py (specs):

  search → fetch vendor-domain pages → regex out version + date →
  cache to firmware_versions → return a FirmwareRecord

Returns a *version pointer* (version, optional release_date, notes_url).
Bullet-level diff (security/features/bugs) is **not** synthesized — that
requires either a hand-built per-vendor fetcher (Cumulus / MikroTik) or
an LLM, and we have neither for the long tail. Honest by design.

Total deadline: 9 s, same as live spec lookup. Cached on success so the
next query is instant.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

from firmware import FirmwareRecord, parse_version

logger = logging.getLogger("live_firmware")

# "v1.2.3" / "Version 5.10.1" / "Firmware: 7.18.2" / "Release 22.4R3"
_VERSION_RE = re.compile(
    r"(?:version|firmware|release|build|software|nos|os|v)\s*[:\-]?\s*"
    r"v?(\d+(?:\.\d+){1,3}[A-Za-z0-9\-]*)",
    re.IGNORECASE,
)
# 2024-03-15 / 2024/03/15 / 15 Mar 2024 / March 15, 2024
_DATE_RE = re.compile(
    r"(20\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])"
    r"|(?:0?[1-9]|[12]\d|3[01])\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|"
    r"Oct|Nov|Dec)\w*\s+20\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(?:0?[1-9]|"
    r"[12]\d|3[01]),?\s+20\d{2})",
    re.IGNORECASE,
)
_SKU_TOKEN = re.compile(r"\b[A-Z][A-Z]+[-]?\d{2,}[\w\-]*\b")


def _normalize_date(s: str) -> Optional[str]:
    from datetime import datetime
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
                "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def live_firmware_lookup(
    query: str,
    vendor_hint: str = "",
    *,
    deadline_sec: float = 9.0,
) -> Optional[FirmwareRecord]:
    """Search the web for this switch's latest firmware. Returns a
    FirmwareRecord (pointer-tier — no changelog content) or None."""
    t0 = time.time()
    remaining = lambda: deadline_sec - (time.time() - t0)

    # Lazy imports — these pull in requests/bs4 etc.
    from live_search import search_for_switch, guess_vendor
    from live_extract import fetch_parallel, source_confidence

    vendor = vendor_hint or guess_vendor(query) or ""
    if not vendor:
        logger.info("live_firmware: no vendor for %r", query)
        return None

    # ----- 1. Search vendor-targeted firmware queries -----
    if remaining() < 4:
        return None
    queries = [
        f"{vendor} {query} firmware release notes",
        f"{vendor} {query} firmware download latest",
    ]
    seen_urls, candidates = set(), []
    for q in queries:
        try:
            res = search_for_switch(
                q, vendor=vendor, max_results=5,
                timeout=int(max(2, min(remaining() - 4, 3))),
            )
        except Exception as e:
            logger.debug("search failed: %s", e)
            res = []
        for r in res:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            candidates.append(r)
        if len(candidates) >= 4:
            break
    if not candidates:
        logger.info("live_firmware: no search results for %r", query)
        return None

    # ----- 2. Fetch the most vendor-trusted ones -----
    candidates.sort(key=lambda r: -source_confidence(r["url"]))
    urls = [r["url"] for r in candidates[:3]]
    if remaining() < 2.5:
        return None
    pages = fetch_parallel(urls, timeout=int(max(2, remaining() - 1)))
    if not pages:
        logger.info("live_firmware: no pages fetched")
        return None

    # ----- 3. Extract version candidates -----
    found = []  # (version, normalised_date_or_None, url, source_confidence)
    for url, content in pages.items():
        try:
            text = content[:200_000].decode("latin-1", errors="ignore")
        except Exception:
            continue
        # Reject catalog pages: too many distinct SKUs means the version
        # numbers we see can't be attributed to *this* model.
        if len(set(_SKU_TOKEN.findall(text[:30_000].upper()))) > 25:
            logger.debug("skip catalog page: %s", url)
            continue
        conf = source_confidence(url)
        for m in _VERSION_RE.finditer(text):
            v = m.group(1)
            if parse_version(v) is None:
                continue
            window = text[max(0, m.start() - 250):m.end() + 250]
            d = None
            dm = _DATE_RE.search(window)
            if dm:
                d = _normalize_date(dm.group(1))
            found.append((v, d, url, conf))

    if not found:
        logger.info("live_firmware: no version strings extracted")
        return None

    # ----- 4. Pick the highest version, preferring vendor-domain pages -----
    found.sort(
        key=lambda x: (parse_version(x[0]) or (), x[3]),
        reverse=True,
    )
    best_v, best_d, best_url, _ = found[0]

    # ----- 5. Build the record -----
    from agent import VENDOR_ALIASES
    canonical = VENDOR_ALIASES.get(vendor.lower(), vendor.title())
    rec = FirmwareRecord(
        vendor=canonical,
        nos=canonical,           # no NOS info from live extraction
        version=best_v,
        release_date=best_d,
        release_notes_url=best_url,
        train="live-discovered",
    )

    # ----- 6. Cache for next time -----
    try:
        from firmware_fetchers import upsert_firmware
        upsert_firmware([rec])
        logger.info("Cached live firmware %s v%s (from %s)",
                    canonical, best_v, urlparse(best_url).netloc)
    except Exception as e:
        logger.warning("live_firmware cache failed: %s", e)

    elapsed = time.time() - t0
    logger.info("live_firmware: %s v%s in %.1fs", canonical, best_v, elapsed)
    return rec

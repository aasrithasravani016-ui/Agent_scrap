"""
NIST NVD vulnerability fetcher — plugs the hole for vendors whose own
firmware/release-notes portals are login-gated (HPE Aruba, Cisco, Juniper,
Arista, Dell, Fortinet, etc.).

The NVD public REST API has no auth requirement and returns CVE records
with structured version ranges, so even when we cannot scrape the vendor's
own release notes we can still tell the user:

    "Your firmware 10.08.1000 is affected by 12 published CVEs.
     The earliest version that fixes all of them is 10.10.1100."

API docs:    https://nvd.nist.gov/developers/vulnerabilities
Rate limit:  5 requests / 30s without API key, 50 / 30s with a free key.

This file is intentionally standalone (no LLM, no paid APIs).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from scrapers.base import HttpClient

logger = logging.getLogger("nvd_fetcher")

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "switches.db"

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"


# ---------------------------------------------------------------------------
# Vendor / NOS mapping
# ---------------------------------------------------------------------------
# Each entry is (display_vendor, display_nos, [cpe_pattern, ...]).
# The CPE pattern uses NVD's virtualMatchString syntax — vendor:product is
# enough; we don't constrain version (the API matches across all versions
# and gives us the version ranges per CVE).
#
# Multiple CPEs per (vendor, nos) accommodate naming variants (e.g. Aruba is
# split between "arubaos" and "aos-cx", Juniper sometimes ships as "junos"
# vs "junos_os_evolved", Dell switched from "force10" → "networking_os10"
# → "smartfabric_os10" over the years).
# Display labels here MUST stay in sync with what other parts of the agent
# use:
#   - DEFAULT_GATED_NOS in firmware.py (uses these exact strings)
#   - the `nos` column in the switches table (so a switch lookup that
#     returns nos='ArubaOS-CX' resolves to the right advisory bucket)
# If you rename one of these, also update both of those.
VENDOR_CPES: list[tuple[str, str, list[str]]] = [
    # HPE Aruba — ArubaOS-CX (modern data-center OS), ArubaOS (campus), etc.
    ("HPE Aruba",  "ArubaOS-CX",
     ["cpe:2.3:o:arubanetworks:aos-cx",
      "cpe:2.3:o:arubanetworks:arubaos-cx"]),
    ("HPE Aruba",  "ArubaOS",
     ["cpe:2.3:o:arubanetworks:arubaos"]),
    ("HPE Aruba",  "AOS-S",
     ["cpe:2.3:o:arubanetworks:aoss",
      "cpe:2.3:o:arubanetworks:aos-s"]),
    ("HPE Aruba",  "Instant On",
     ["cpe:2.3:o:arubanetworks:instant_on"]),

    # Cisco
    ("Cisco",      "IOS",     ["cpe:2.3:o:cisco:ios"]),
    ("Cisco",      "IOS-XE",  ["cpe:2.3:o:cisco:ios_xe"]),
    ("Cisco",      "NX-OS",   ["cpe:2.3:o:cisco:nx-os"]),

    # Juniper
    ("Juniper",    "Junos",
     ["cpe:2.3:o:juniper:junos",
      "cpe:2.3:o:juniper:junos_os_evolved"]),

    # Arista
    ("Arista",     "EOS",     ["cpe:2.3:o:arista:eos"]),

    # Dell — has shipped under multiple product names over the years
    ("Dell",       "OS10",
     ["cpe:2.3:o:dell:smartfabric_os10",
      "cpe:2.3:o:dell:networking_os10",
      "cpe:2.3:o:dell:emc_networking_os10"]),

    # Fortinet (data-center + campus switches)
    ("Fortinet",   "FortiOS",      ["cpe:2.3:o:fortinet:fortios"]),
    ("Fortinet",   "FortiSwitch",  ["cpe:2.3:o:fortinet:fortiswitchos",
                                    "cpe:2.3:o:fortinet:fortiswitch"]),

    # NVIDIA Cumulus (supplements vendor changelog data)
    ("NVIDIA",     "Cumulus Linux",
     ["cpe:2.3:o:nvidia:cumulus_linux",
      "cpe:2.3:o:nvidia:cumulus_networks_cumulus_linux"]),

    # NVIDIA Onyx (the old Mellanox MLNX-OS / Onyx switch OS, still
    # running on a lot of data-center ToR switches NVIDIA absorbed)
    ("NVIDIA",     "Onyx",
     ["cpe:2.3:o:nvidia:onyx"]),

    # Extreme Networks — two CPE spellings in NVD
    ("Extreme Networks", "EXOS",
     ["cpe:2.3:o:extremenetworks:exos",
      "cpe:2.3:o:extremenetworks:extremexos"]),

    # Huawei — switch CPEs are per-model in NVD, so we enumerate the
    # families that actually have published CVEs. Vendor-wide CVE total
    # is in the thousands, but most are phones / home routers; this
    # list is just the switch (S-series + CloudEngine) products.
    ("Huawei", "VRP",
     ["cpe:2.3:o:huawei:s1700_firmware",
      "cpe:2.3:o:huawei:s2700_firmware",
      "cpe:2.3:o:huawei:s3700_firmware",
      "cpe:2.3:o:huawei:s5700_firmware",
      "cpe:2.3:o:huawei:s6300_firmware",
      "cpe:2.3:o:huawei:s7700_firmware",
      "cpe:2.3:o:huawei:s9300_firmware",
      "cpe:2.3:o:huawei:s9700_firmware",
      "cpe:2.3:o:huawei:cloudengine_5800_firmware",
      "cpe:2.3:o:huawei:cloudengine_6800_firmware",
      "cpe:2.3:o:huawei:cloudengine_7800_firmware",
      "cpe:2.3:o:huawei:cloudengine_12800_firmware"]),

    # Brocade (now Broadcom) — Fabric OS for FC SAN switches
    ("Brocade", "Fabric OS",
     ["cpe:2.3:o:brocade:fabric_os",
      "cpe:2.3:a:brocade:network_advisor"]),

    # Netgear smart-managed switches (the GS/M-series, not home routers)
    ("Netgear", "Smart Managed",
     ["cpe:2.3:o:netgear:gs108e_firmware",
      "cpe:2.3:o:netgear:gs308t_firmware",
      "cpe:2.3:o:netgear:gs710tup_firmware",
      "cpe:2.3:o:netgear:gc108p_firmware",
      "cpe:2.3:o:netgear:gc108pp_firmware",
      "cpe:2.3:o:netgear:m4300-28g_firmware"]),

    # TP-Link Omada controller (the SDN controller that manages their
    # JetStream switches — CVEs hit the controller, not the switch OS)
    ("TP-Link", "Omada Controller",
     ["cpe:2.3:a:tp-link:omada_controller"]),
]


# ---------------------------------------------------------------------------
# Advisory record
# ---------------------------------------------------------------------------
@dataclass
class AdvisoryRecord:
    cve_id: str
    vendor: str
    nos: Optional[str]
    published: Optional[str] = None
    last_modified: Optional[str] = None
    severity: Optional[str] = None
    cvss_score: Optional[float] = None
    cvss_vector: Optional[str] = None
    description: Optional[str] = None
    affected_ranges: list[dict] = field(default_factory=list)
    fixed_versions: list[str] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    source: str = "nvd"


# ---------------------------------------------------------------------------
# Pagination + parsing
# ---------------------------------------------------------------------------
PAGE_SIZE = 2000        # NVD max for CVE 2.0
# Anonymous NVD limit is 5 requests / 30 seconds. We need a per-call sleep
# >= 6 seconds. Long runs sometimes still get 429s when the bucket is
# already depleted from a prior fetch, so we go 8s to leave headroom.
# With a free NVD API key this could drop to ~0.6s.
SLEEP_BETWEEN = 8.0


def _best_cvss(metrics: dict) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """Pick the highest-priority CVSS metric available."""
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        arr = metrics.get(key) or []
        if not arr:
            continue
        c = arr[0].get("cvssData") or {}
        score = c.get("baseScore")
        sev = c.get("baseSeverity") or arr[0].get("baseSeverity")
        vec = c.get("vectorString")
        if score is not None:
            return float(score), sev, vec
    return None, None, None


def _english_description(descs: list) -> Optional[str]:
    for d in descs or []:
        if d.get("lang") == "en":
            return d.get("value")
    return None


def _parse_configurations(cfgs: list, cpe_filter_vendors: set[str]) -> tuple[list[dict], list[str]]:
    """
    Extract version-range matches for any CPE whose vendor is in
    cpe_filter_vendors. Returns (ranges, fixed_versions).

    A range is {product, start, start_incl, end, end_incl}.
    A "fixed_version" is the upper bound of a range (the first known
    version where the vendor stopped being vulnerable, when known).
    """
    ranges: list[dict] = []
    fixed: list[str] = []

    for cfg in cfgs or []:
        for node in cfg.get("nodes", []) or []:
            for m in node.get("cpeMatch", []) or []:
                if not m.get("vulnerable"):
                    continue
                criteria = m.get("criteria") or ""
                # criteria looks like 'cpe:2.3:o:arubanetworks:aos-cx:*:*:*:*:*:*:*:*'
                parts = criteria.split(":")
                if len(parts) < 5:
                    continue
                vendor, product = parts[3], parts[4]
                if vendor not in cpe_filter_vendors:
                    continue

                start_incl = m.get("versionStartIncluding")
                start_excl = m.get("versionStartExcluding")
                end_incl = m.get("versionEndIncluding")
                end_excl = m.get("versionEndExcluding")

                # If neither bound is set this CPE pins one specific version
                # in field 5 (e.g. '17.12.4'). Capture it as start==end.
                exact = parts[5] if len(parts) > 5 and parts[5] not in ("*", "-") else None
                if not any([start_incl, start_excl, end_incl, end_excl]) and exact:
                    start = exact
                    end = exact
                    s_incl = True
                    e_incl = True
                else:
                    start = start_incl or start_excl
                    end = end_incl or end_excl
                    s_incl = bool(start_incl)
                    e_incl = bool(end_incl)
                    if not start and not end:
                        continue  # nothing version-specific

                ranges.append({
                    "product": product,
                    "start": start,
                    "start_incl": s_incl,
                    "end": end,
                    "end_incl": e_incl,
                })
                # First *unfixed* version above the range = the fix.
                # If versionEndExcluding=X, X is the fixed version.
                # If versionEndIncluding=X, X is still vulnerable; we
                # don't synthesize a "next" version (vendor-specific).
                if end_excl:
                    fixed.append(end_excl)
    # dedupe fixed_versions, preserve order
    seen = set()
    fixed_dedup = [v for v in fixed if not (v in seen or seen.add(v))]
    return ranges, fixed_dedup


def _yield_advisories(
    http: HttpClient,
    cpe_substr: str,
    vendor_display: str,
    nos_display: str,
    cpe_vendors: set[str],
) -> Iterator[AdvisoryRecord]:
    """
    Page through all CVEs matching virtualMatchString=<cpe_substr>.
    """
    start_index = 0
    total = None
    while True:
        url = (
            f"{NVD_API}?virtualMatchString={cpe_substr}"
            f"&resultsPerPage={PAGE_SIZE}&startIndex={start_index}"
        )
        raw = http.get_text(url, force=False)
        if not raw:
            logger.warning("NVD page failed: %s", url)
            return
        try:
            data = json.loads(raw)
        except ValueError:
            logger.warning("NVD non-JSON for %s", url)
            return

        if total is None:
            total = data.get("totalResults", 0)
            logger.info("NVD %s -> %s results", cpe_substr, total)

        vulns = data.get("vulnerabilities") or []
        if not vulns:
            return

        for v in vulns:
            c = v.get("cve") or {}
            cve_id = c.get("id")
            if not cve_id:
                continue
            score, sev, vec = _best_cvss(c.get("metrics") or {})
            ranges, fixed = _parse_configurations(
                c.get("configurations") or [], cpe_vendors,
            )
            if not ranges:
                # CVE mentions the vendor in metadata but no version-specific
                # match — skip; the user can't act on it.
                continue

            yield AdvisoryRecord(
                cve_id=cve_id,
                vendor=vendor_display,
                nos=nos_display,
                published=(c.get("published") or "")[:10] or None,
                last_modified=(c.get("lastModified") or "")[:10] or None,
                severity=sev,
                cvss_score=score,
                cvss_vector=vec,
                description=_english_description(c.get("descriptions") or []),
                affected_ranges=ranges,
                fixed_versions=fixed,
                references=[
                    {"url": r.get("url"), "source": r.get("source")}
                    for r in (c.get("references") or [])
                    if r.get("url")
                ],
            )

        start_index += len(vulns)
        if total is not None and start_index >= total:
            return
        time.sleep(SLEEP_BETWEEN)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------
class NvdFetcher:
    """
    Walks every (vendor, nos, [cpe...]) entry in VENDOR_CPES and yields
    AdvisoryRecord objects. Caller upserts into security_advisories.
    """
    VENDOR = "NVD"
    DELAY_SEC = 1.0

    def __init__(self, only_vendor: Optional[str] = None):
        self.only_vendor = only_vendor.lower() if only_vendor else None
        # 6s between API calls — base HttpClient already enforces per-domain
        # rate limiting; we ALSO sleep between pages inside the iterator.
        self.http = HttpClient("nvd", delay=self.DELAY_SEC)

    def run(self) -> list[AdvisoryRecord]:
        out: list[AdvisoryRecord] = []
        seen: set[tuple[str, str]] = set()   # (cve_id, vendor)
        first = True
        for vendor, nos, cpes in VENDOR_CPES:
            if self.only_vendor and self.only_vendor not in vendor.lower():
                continue
            cpe_vendor_set = {c.split(":")[3] for c in cpes if len(c.split(":")) > 3}
            for cpe in cpes:
                # Inter-CPE sleep — many of the per-model CPEs return only
                # a single page so the in-page sleep doesn't fire and we'd
                # otherwise hammer NVD with N back-to-back calls. The cache
                # means already-fetched pages skip the network, so this only
                # delays actual hits.
                if not first:
                    time.sleep(SLEEP_BETWEEN)
                first = False
                logger.info("[NVD] %s / %s -> %s", vendor, nos, cpe)
                try:
                    for rec in _yield_advisories(
                        self.http, cpe, vendor, nos, cpe_vendor_set,
                    ):
                        key = (rec.cve_id, rec.vendor)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(rec)
                except Exception as e:
                    logger.warning("[NVD] %s failed: %s", cpe, e)
        logger.info("[NVD] total: %d unique advisories", len(out))
        return out


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------
def _ensure_schema(db_path: Path):
    """Create the DB if missing, or ALTER existing DB to add new table."""
    db_path.parent.mkdir(exist_ok=True)
    schema_sql = (ROOT / "schema.sql").read_text()
    con = sqlite3.connect(db_path)
    con.executescript(schema_sql)
    con.commit()
    con.close()


def upsert_advisories(
    records: list[AdvisoryRecord], db_path: Path = DB_PATH,
) -> int:
    if not records:
        return 0
    _ensure_schema(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for rec in records:
        d = {
            "cve_id": rec.cve_id,
            "vendor": rec.vendor,
            "nos": rec.nos,
            "published": rec.published,
            "last_modified": rec.last_modified,
            "severity": rec.severity,
            "cvss_score": rec.cvss_score,
            "cvss_vector": rec.cvss_vector,
            "description": rec.description,
            "affected_ranges": json.dumps(rec.affected_ranges)
                                if rec.affected_ranges else None,
            "fixed_versions": json.dumps(rec.fixed_versions)
                               if rec.fixed_versions else None,
            "references_json": json.dumps(rec.references)
                                if rec.references else None,
            "source": rec.source,
            "last_updated": now,
        }
        existing = con.execute(
            "SELECT id FROM security_advisories WHERE cve_id=? AND vendor=?",
            (d["cve_id"], d["vendor"]),
        ).fetchone()
        if existing:
            sets = ",".join(
                f"{k}=?" for k in d if k not in ("cve_id", "vendor")
            )
            vals = [v for k, v in d.items() if k not in ("cve_id", "vendor")]
            con.execute(
                f"UPDATE security_advisories SET {sets} WHERE id=?",
                vals + [existing["id"]],
            )
        else:
            keys = ",".join(d.keys())
            qs = ",".join("?" * len(d))
            con.execute(
                f"INSERT INTO security_advisories ({keys}) VALUES ({qs})",
                list(d.values()),
            )
        written += 1
    con.commit()
    con.close()
    return written


# ---------------------------------------------------------------------------
# Module-level entry point (mirrors firmware_fetchers BaseFirmwareFetcher API)
# ---------------------------------------------------------------------------
def fetch_and_upsert(only_vendor: Optional[str] = None) -> tuple[int, int]:
    """
    Returns (fetched, written).
    """
    fetcher = NvdFetcher(only_vendor=only_vendor)
    recs = fetcher.run()
    written = upsert_advisories(recs)
    return len(recs), written

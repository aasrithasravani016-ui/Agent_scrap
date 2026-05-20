"""
CISA Known Exploited Vulnerabilities (KEV) overlay.

Source:  https://www.cisa.gov/known-exploited-vulnerabilities-catalog
Feed:    https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
Auth:    none — official U.S. government public feed, updated daily

KEV is a curated subset of CVEs that attackers are CURRENTLY using in
the wild. Most published CVEs are theoretical; KEV ones are not. When
a CVE we already track is in KEV, we flag it on the existing
security_advisories row so the UI can show an "actively exploited"
badge and the fix recommendation can prioritize that CVE.

This file only sets the overlay columns (actively_exploited,
kev_date_added, kev_due_date, kev_required_action); it never creates
new advisory rows on its own — KEV gives us the CVE id and dates,
not the affected/fixed version ranges. Those have to come from NVD
first via scrapers.nvd_fetcher.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scrapers.base import HttpClient

logger = logging.getLogger("cisa_kev_fetcher")

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "switches.db"

KEV_FEED = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)


def _ensure_schema(db_path: Path):
    """Create the DB if missing, otherwise ensure the KEV columns exist
    (ALTER for older DBs that pre-date the columns)."""
    db_path.parent.mkdir(exist_ok=True)
    schema_sql = (ROOT / "schema.sql").read_text()
    con = sqlite3.connect(db_path)
    con.executescript(schema_sql)
    # Defensive ALTERs for DBs that have the table but not the new cols
    for col, ddl in [
        ("actively_exploited", "INTEGER DEFAULT 0"),
        ("kev_date_added",     "TEXT"),
        ("kev_due_date",       "TEXT"),
        ("kev_required_action","TEXT"),
    ]:
        try:
            con.execute(
                f"ALTER TABLE security_advisories ADD COLUMN {col} {ddl}"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
    con.commit()
    con.close()


def fetch_kev_catalog() -> list[dict]:
    """Download the latest KEV catalog. Returns the raw list of entries."""
    http = HttpClient("cisa_kev", delay=1.0)
    # Force=False uses the on-disk cache; the orchestrator can pass
    # force=True to refresh.
    raw = http.get_text(KEV_FEED, force=True)
    if not raw:
        logger.warning("KEV feed unreachable")
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("KEV feed returned non-JSON")
        return []
    vulns = data.get("vulnerabilities") or []
    logger.info("[KEV] catalog has %d entries", len(vulns))
    return vulns


def apply_overlay(
    catalog: list[dict], db_path: Path = DB_PATH,
) -> tuple[int, int]:
    """
    Flip actively_exploited=1 on every row in security_advisories whose
    CVE ID is in the KEV catalog. Returns (matched, total_kev).
    """
    if not catalog:
        return (0, 0)
    _ensure_schema(db_path)
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()

    # First clear stale flags — a CVE removed from KEV should be cleared.
    con.execute(
        "UPDATE security_advisories SET actively_exploited=0, "
        "kev_date_added=NULL, kev_due_date=NULL, kev_required_action=NULL "
        "WHERE actively_exploited=1"
    )

    matched = 0
    for v in catalog:
        cve_id = v.get("cveID") or v.get("cveId")
        if not cve_id:
            continue
        cur = con.execute(
            "UPDATE security_advisories "
            "SET actively_exploited=1, kev_date_added=?, kev_due_date=?, "
            "    kev_required_action=?, last_updated=? "
            "WHERE cve_id=?",
            (
                v.get("dateAdded"),
                v.get("dueDate"),
                v.get("requiredAction"),
                now,
                cve_id,
            ),
        )
        matched += cur.rowcount
    con.commit()
    con.close()
    logger.info(
        "[KEV] flagged %d of our %d cached advisories as actively exploited",
        matched, len(catalog),
    )
    return (matched, len(catalog))


def fetch_and_apply(db_path: Path = DB_PATH) -> tuple[int, int]:
    """One-shot orchestrator entry point: download KEV, overlay onto DB."""
    catalog = fetch_kev_catalog()
    return apply_overlay(catalog, db_path=db_path)

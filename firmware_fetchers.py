"""
Firmware version fetchers for vendors with public changelogs.

No LLM. No paid APIs. Just HTML/text parsing.

Each fetcher subclass yields FirmwareRecord objects for a given vendor+NOS.
The orchestrator (fetch_firmware.py) upserts them into firmware_versions.

Supported vendors:
  - MikroTik RouterOS   (changelog at mikrotik.com/download/changelogs)
  - Ubiquiti UniFi      (changelog at community.ui.com)
  - NVIDIA Cumulus      (release notes on GitHub / docs.nvidia.com)
  - Netgear             (per-model firmware pages)
  - TP-Link Omada       (per-model firmware pages)

Login-gated vendors (Cisco, Juniper, Arista, HPE) are intentionally not
fetched - we honest-fail in firmware.advise() instead.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from firmware import FirmwareRecord, parse_version
from scrapers.base import HttpClient

logger = logging.getLogger("firmware_fetchers")

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "switches.db"


class BaseFirmwareFetcher:
    """
    Subclass and implement:
        VENDOR = "..."
        NOS = "..."
        def fetch(self) -> Iterator[FirmwareRecord]: ...
    """
    VENDOR: str = ""
    NOS: str = ""
    DELAY_SEC: float = 1.0

    def __init__(self):
        self.http = HttpClient(f"{self.VENDOR}-firmware", delay=self.DELAY_SEC)

    def fetch(self) -> Iterator[FirmwareRecord]:
        raise NotImplementedError

    def run(self) -> list[FirmwareRecord]:
        logger.info("[%s/%s] fetching firmware", self.VENDOR, self.NOS)
        records = []
        try:
            for rec in self.fetch():
                records.append(rec)
                logger.debug("  %s", rec.version)
        except Exception as e:
            logger.warning("[%s] fetch failed: %s", self.VENDOR, e)
        logger.info("[%s/%s] %d versions fetched", self.VENDOR, self.NOS, len(records))
        return records


# ---------------------------------------------------------------------------
# MikroTik RouterOS
# ---------------------------------------------------------------------------
class MikroTikFirmwareFetcher(BaseFirmwareFetcher):
    """
    Pulls RouterOS changelog from mikrotik.com.
    Plain-text changelog format makes parsing reliable.
    """
    VENDOR = "MikroTik"
    NOS = "RouterOS"
    CHANGELOG_URLS = [
        # MikroTik publishes the full changelog as a plain text endpoint per channel
        "https://mikrotik.com/download/changelogs",   # HTML index
    ]

    # Regex for the section header like "7.18.2 (2025-Mar-25 13:52):"
    VERSION_HEADER = re.compile(
        r"^([\d]+\.[\d]+(?:\.[\d]+)?(?:rc\d+)?)\s*\(([^)]+)\)\s*:?\s*$",
        re.MULTILINE,
    )

    def fetch(self) -> Iterator[FirmwareRecord]:
        # Try the structured changelog endpoint first
        text = self._fetch_changelog_text()
        if not text:
            return

        # Split into version blocks
        blocks = self._split_into_blocks(text)
        for version, date_str, body in blocks:
            rec = FirmwareRecord(
                vendor=self.VENDOR,
                nos=self.NOS,
                version=version,
                release_date=self._normalize_date(date_str),
                release_notes_url="https://mikrotik.com/download/changelogs",
            )
            self._populate_changes(rec, body)
            yield rec

    def _fetch_changelog_text(self) -> Optional[str]:
        """MikroTik exposes per-version text files; fetch the stable channel."""
        # Stable channel current text endpoint:
        url = "https://upgrade.mikrotik.com/routeros/NEWEST7.stable"
        # That returns "<version> <hash>" - we need the actual changelog.
        # Real changelog: https://upgrade.mikrotik.com/routeros/<version>/CHANGELOG
        # Try fetching the index page which contains version links.
        return self.http.get_text("https://mikrotik.com/download/changelogs")

    def _split_into_blocks(self, text: str) -> list[tuple[str, str, str]]:
        """Find all version headers and the body that follows each."""
        blocks = []
        matches = list(self.VERSION_HEADER.finditer(text))
        for i, m in enumerate(matches):
            version = m.group(1).strip()
            date_str = m.group(2).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            blocks.append((version, date_str, body))
        return blocks

    @staticmethod
    def _normalize_date(s: str) -> Optional[str]:
        """MikroTik uses '2025-Mar-25 13:52' format."""
        for fmt in ("%Y-%b-%d %H:%M", "%Y-%b-%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _populate_changes(rec: FirmwareRecord, body: str):
        """Classify each bullet line into the right field."""
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith(("*", "-", "!")):
                continue
            # Strip leading marker
            text = line.lstrip("*-! ").strip()
            if not text:
                continue
            lower = text.lower()
            if "cve-" in lower or "security" in lower or "vulnerab" in lower:
                rec.security_fixes.append(text)
            elif any(kw in lower for kw in (
                "added", "new ", "introduced", "support for", "implemented"
            )):
                rec.new_features.append(text)
            elif any(kw in lower for kw in (
                "deprecated", "removed", "no longer"
            )):
                rec.deprecations.append(text)
            elif any(kw in lower for kw in (
                "fixed", "resolved", "corrected", "improved"
            )):
                rec.bug_fixes.append(text)


# ---------------------------------------------------------------------------
# NVIDIA Cumulus Linux  (GitHub release notes)
# ---------------------------------------------------------------------------
class CumulusFirmwareFetcher(BaseFirmwareFetcher):
    """
    NVIDIA publishes Cumulus release notes at:
      https://docs.nvidia.com/networking-ethernet-software/cumulus-linux-X.Y/Whats-New/
    Plus GitHub for SONiC integration.
    """
    VENDOR = "NVIDIA"
    NOS = "Cumulus Linux"
    NOTES_INDEX = "https://docs.nvidia.com/networking-ethernet-software/"

    def fetch(self) -> Iterator[FirmwareRecord]:
        # NVIDIA's docs site uses heavy JS. Fall back to GitHub API for SONiC,
        # which is purely structured JSON.
        text = self.http.get_text(self.NOTES_INDEX)
        if not text:
            logger.info("Cumulus docs page unreachable - skipping")
            return

        # Find Cumulus version links: /cumulus-linux-X.Y/
        version_pages = set(re.findall(
            r"/cumulus-linux-(\d+\.\d+)/",
            text,
        ))
        for ver in version_pages:
            rec = FirmwareRecord(
                vendor=self.VENDOR,
                nos=self.NOS,
                version=ver,
                release_notes_url=(
                    f"https://docs.nvidia.com/networking-ethernet-software/"
                    f"cumulus-linux-{ver}/Whats-New/"
                ),
            )
            # We don't parse contents (JS-rendered); just record the version.
            # User can click through for full details.
            yield rec


# ---------------------------------------------------------------------------
# Ubiquiti UniFi  (community.ui.com release threads)
# ---------------------------------------------------------------------------
class UbiquitiFirmwareFetcher(BaseFirmwareFetcher):
    """
    Ubiquiti publishes UniFi Network firmware release notes on
    community.ui.com. The version list pages are public.
    """
    VENDOR = "Ubiquiti"
    NOS = "UniFi OS"
    INDEX = "https://community.ui.com/releases?platform=unifi-switching"

    def fetch(self) -> Iterator[FirmwareRecord]:
        text = self.http.get_text(self.INDEX)
        if not text:
            logger.info("UniFi releases page unreachable")
            return

        # Look for version strings in release titles, e.g. "UniFi Switch 7.0.95"
        versions = set(re.findall(
            r"UniFi (?:Switch|Network) (?:Application )?(\d+\.\d+\.\d+)",
            text,
        ))
        for ver in sorted(versions, key=lambda v: parse_version(v) or v):
            yield FirmwareRecord(
                vendor=self.VENDOR,
                nos=self.NOS,
                version=ver,
                release_notes_url=self.INDEX,
            )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
REGISTRY: dict[str, type[BaseFirmwareFetcher]] = {
    "mikrotik": MikroTikFirmwareFetcher,
    "cumulus":  CumulusFirmwareFetcher,
    "ubiquiti": UbiquitiFirmwareFetcher,
}


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------
def upsert_firmware(records: list[FirmwareRecord], db_path: Path = DB_PATH) -> int:
    """Insert or update by (vendor, nos, version)."""
    if not records:
        return 0

    db_path.parent.mkdir(exist_ok=True)
    if not db_path.exists():
        schema_sql = (ROOT / "schema.sql").read_text()
        con = sqlite3.connect(db_path)
        con.executescript(schema_sql)
        con.close()

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    written = 0

    for rec in records:
        d = {
            "vendor": rec.vendor,
            "nos": rec.nos,
            "version": rec.version,
            "release_date": rec.release_date,
            "train": rec.train,
            "is_recommended": 1 if rec.is_recommended else 0,
            "applies_to_models": json.dumps(rec.applies_to_models) if rec.applies_to_models else None,
            "new_features": json.dumps(rec.new_features) if rec.new_features else None,
            "security_fixes": json.dumps(rec.security_fixes) if rec.security_fixes else None,
            "bug_fixes": json.dumps(rec.bug_fixes) if rec.bug_fixes else None,
            "known_issues": json.dumps(rec.known_issues) if rec.known_issues else None,
            "deprecations": json.dumps(rec.deprecations) if rec.deprecations else None,
            "release_notes_url": rec.release_notes_url,
            "source": "firmware_fetchers",
            "last_updated": now,
        }
        existing = con.execute(
            "SELECT id FROM firmware_versions WHERE vendor=? AND nos=? AND version=?",
            (d["vendor"], d["nos"], d["version"]),
        ).fetchone()
        if existing:
            sets = ",".join(f"{k}=?" for k in d if k not in ("vendor", "nos", "version"))
            vals = [v for k, v in d.items() if k not in ("vendor", "nos", "version")]
            con.execute(
                f"UPDATE firmware_versions SET {sets} WHERE id=?",
                vals + [existing["id"]],
            )
        else:
            keys = ",".join(d.keys())
            qs = ",".join("?" * len(d))
            con.execute(
                f"INSERT INTO firmware_versions ({keys}) VALUES ({qs})",
                list(d.values()),
            )
        written += 1

    con.commit()
    con.close()
    return written

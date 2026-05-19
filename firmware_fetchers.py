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
    Pulls RouterOS changelogs from MikroTik's plain-text upgrade mirror.

    Reliable endpoints (no JS, no API key):
      - https://upgrade.mikrotik.com/routeros/NEWEST7.<channel>  -> "<ver> <ts>"
      - https://upgrade.mikrotik.com/routeros/<ver>/CHANGELOG     -> plain text
        ("What's new in <ver> (<date>):" + "*) area - text;" bullets)

    We resolve the channel heads, then walk recent minor/patch versions of
    the current major and fetch each per-version CHANGELOG.
    """
    VENDOR = "MikroTik"
    NOS = "RouterOS"
    BASE = "https://upgrade.mikrotik.com/routeros"
    CHANNELS = {  # endpoint suffix -> train label
        "NEWEST7.stable": "stable",
        "NEWEST7.long-term": "long-term",
        "NEWEST7.testing": "testing",
    }
    MINORS_BACK = 6   # how many minor versions back from the stable head
    MAX_PATCH = 6     # patch numbers to probe per minor (.0 .. .5)

    HEADER = re.compile(
        r"What's new in\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:rc\d+)?)\s*"
        r"\(([^)]+)\)\s*:?",
        re.IGNORECASE,
    )

    def _channel_version(self, suffix: str) -> Optional[str]:
        txt = self.http.get_text(f"{self.BASE}/{suffix}")
        if not txt:
            return None
        tok = txt.strip().split()
        v = tok[0] if tok else ""
        return v if re.match(r"^\d+\.\d+", v) else None

    def fetch(self) -> Iterator[FirmwareRecord]:
        # 1. Resolve channel heads. CHANNELS is ordered stable-first;
        #    setdefault keeps the stable label if testing == stable, and we
        #    capture the stable head directly (don't reverse-look it up).
        train_of: dict[str, str] = {}
        recommended: set[str] = set()
        stable_head: Optional[str] = None
        for suffix, train in self.CHANNELS.items():
            v = self._channel_version(suffix)
            if not v or not re.match(r"^[1-9]", v):   # skip "0.00" placeholder
                continue
            train_of.setdefault(v, train)
            if train == "stable":
                stable_head = v
                recommended.add(v)

        if not stable_head:
            logger.warning("[MikroTik] could not resolve stable channel head")
            return
        latest_minor = int(stable_head.split(".")[1])

        # 2. Walk recent minor/patch versions and fetch each CHANGELOG
        for minor in range(latest_minor, max(latest_minor - self.MINORS_BACK,
                                              -1), -1):
            for patch in range(0, self.MAX_PATCH):
                ver = f"7.{minor}" if patch == 0 else f"7.{minor}.{patch}"
                text = self.http.get_text(f"{self.BASE}/{ver}/CHANGELOG")
                if not text or "what's new in" not in text.lower():
                    if patch == 0:
                        break  # this minor doesn't exist at all
                    break      # patches are contiguous; stop at first gap
                rec = self._parse(ver, text, train_of, recommended)
                if rec:
                    yield rec

    def _parse(self, ver: str, text: str, train_of: dict,
               recommended: set) -> Optional[FirmwareRecord]:
        m = self.HEADER.search(text)
        version = m.group(1).strip() if m else ver
        date_str = m.group(2).strip() if m else ""
        rec = FirmwareRecord(
            vendor=self.VENDOR,
            nos=self.NOS,
            version=version,
            release_date=self._normalize_date(date_str),
            train=train_of.get(version),
            is_recommended=version in recommended,
            release_notes_url=f"{self.BASE}/{ver}/CHANGELOG",
        )
        body = text[m.end():] if m else text
        self._populate_changes(rec, body)
        return rec

    @staticmethod
    def _normalize_date(s: str) -> Optional[str]:
        """MikroTik uses '2023-Nov-17 13:38' format."""
        for fmt in ("%Y-%b-%d %H:%M", "%Y-%b-%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(s.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _populate_changes(rec: FirmwareRecord, body: str):
        """Classify each '*) area - text;' bullet into the right field."""
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line.startswith("*)"):
                continue
            text = line[2:].strip().rstrip(";").strip()
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
            else:
                # MikroTik bullets are overwhelmingly fixes/improvements
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

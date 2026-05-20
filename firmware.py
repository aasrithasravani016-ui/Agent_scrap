"""
Firmware version advisor - no LLM, no paid APIs.

Three layers:
  1. version_compare()   - parse and compare semver-like version strings
                           across multiple vendor formats (MikroTik 7.18.2,
                           Cisco 17.12.4, Junos 22.4R3, EOS 4.31.2F, etc.)
  2. firmware_diff()     - given current vs target version, produce a
                           structured diff (new features, security fixes,
                           etc.) by querying the firmware_versions table
  3. advise()            - top-level entry point: takes (switch_model,
                           current_version) and returns either a structured
                           recommendation or an honest "not available"

Data sources are populated by separate per-vendor fetchers (firmware_sources/).
This module is read-only over the DB.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("firmware")

DB_PATH = Path(__file__).parent / "data" / "switches.db"


# -----------------------------------------------------------------------------
# Version parsing & comparison
# -----------------------------------------------------------------------------

# Numeric component followed by optional letter suffix (e.g. "4.31.2F").
# We tokenize a version into (int, str) pairs and compare lexicographically.

_VERSION_TOKEN = re.compile(r"(\d+)([A-Za-z]*)")


@dataclass(frozen=True)
class Version:
    """Parsed version. Comparable. Vendor-agnostic."""
    raw: str
    parts: tuple

    def __lt__(self, other: "Version") -> bool:
        return self.parts < other.parts

    def __le__(self, other: "Version") -> bool:
        return self.parts <= other.parts

    def __gt__(self, other: "Version") -> bool:
        return self.parts > other.parts

    def __ge__(self, other: "Version") -> bool:
        return self.parts >= other.parts

    def __eq__(self, other) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.parts == other.parts

    def __hash__(self) -> int:
        return hash(self.parts)

    def __str__(self) -> str:
        return self.raw


def parse_version(s: str) -> Optional[Version]:
    """
    Parse a vendor firmware version string into a comparable Version.

    Handles:
      MikroTik:   7.18.2, 6.49.7
      Cisco IOS:  15.2(7)E10, 17.12.4
      Cisco IOS-XE: 17.6.4, 17.12.4
      Junos:      22.4R3, 22.4R3-S2, 23.2R1
      Arista EOS: 4.31.2F, 4.32.0F
      ArubaOS-CX: 10.13.1000
      Cumulus:    5.7.0
      RouterOS:   7.18.2

    Returns None if no version-like tokens found.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    tokens = _VERSION_TOKEN.findall(s)
    if not tokens:
        return None
    # (int, letter-rank) tuples. Empty letter sorts before any letter,
    # so "4.31.2" < "4.31.2F" (which is fine - F = "First customer ship"
    # and is the "released" variant).
    parts = []
    for num, letter in tokens:
        try:
            parts.append((int(num), letter.upper()))
        except ValueError:
            continue
    if not parts:
        return None
    return Version(raw=s, parts=tuple(parts))


def version_compare(a: str, b: str) -> Optional[int]:
    """
    Compare two version strings. Returns -1, 0, 1 or None if unparseable.
    """
    va, vb = parse_version(a), parse_version(b)
    if va is None or vb is None:
        return None
    if va < vb: return -1
    if va > vb: return 1
    return 0


# -----------------------------------------------------------------------------
# Firmware DB queries
# -----------------------------------------------------------------------------

@dataclass
class FirmwareRecord:
    """One firmware version's metadata."""
    vendor: str
    nos: str
    version: str
    release_date: Optional[str] = None
    train: Optional[str] = None
    is_recommended: bool = False
    applies_to_models: list[str] = field(default_factory=list)
    new_features: list[str] = field(default_factory=list)
    security_fixes: list[str] = field(default_factory=list)
    bug_fixes: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    deprecations: list[str] = field(default_factory=list)
    release_notes_url: Optional[str] = None

    @property
    def parsed(self) -> Optional[Version]:
        return parse_version(self.version)


def _row_to_firmware(row: sqlite3.Row) -> FirmwareRecord:
    """Convert a DB row into a FirmwareRecord."""
    def _parse_json_field(value):
        if not value:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return FirmwareRecord(
        vendor=row["vendor"],
        nos=row["nos"],
        version=row["version"],
        release_date=row["release_date"],
        train=row["train"],
        is_recommended=bool(row["is_recommended"]),
        applies_to_models=_parse_json_field(row["applies_to_models"]),
        new_features=_parse_json_field(row["new_features"]),
        security_fixes=_parse_json_field(row["security_fixes"]),
        bug_fixes=_parse_json_field(row["bug_fixes"]),
        known_issues=_parse_json_field(row["known_issues"]),
        deprecations=_parse_json_field(row["deprecations"]),
        release_notes_url=row["release_notes_url"],
    )


def list_firmware(vendor: str, nos: str, db_path: Path = DB_PATH) -> list[FirmwareRecord]:
    """List all known firmware versions for a vendor+nos, sorted newest first."""
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM firmware_versions WHERE vendor=? AND nos=?",
        (vendor, nos),
    ).fetchall()
    con.close()
    records = [_row_to_firmware(r) for r in rows]
    # Sort by parsed version, newest first. Unparseable versions go last.
    return sorted(
        records,
        key=lambda r: (r.parsed.parts if r.parsed else (), r.version),
        reverse=True,
    )


def latest_firmware(
    vendor: str,
    nos: str,
    *,
    train: Optional[str] = None,
    model: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> Optional[FirmwareRecord]:
    """
    Return the latest known firmware version for a vendor+nos.
    Optionally restrict by train ('stable', 'LTS') or compatible model.
    """
    candidates = list_firmware(vendor, nos, db_path=db_path)
    if train:
        candidates = [c for c in candidates if (c.train or "").lower() == train.lower()]
    if model:
        candidates = [
            c for c in candidates
            if not c.applies_to_models or any(
                model.lower() in m.lower() for m in c.applies_to_models
            )
        ]
    return candidates[0] if candidates else None


# -----------------------------------------------------------------------------
# Diff between two versions
# -----------------------------------------------------------------------------

@dataclass
class FirmwareDiff:
    """Structured comparison of current vs target firmware."""
    current: FirmwareRecord
    target: FirmwareRecord
    releases_behind: int
    intermediate_versions: list[FirmwareRecord]
    new_features: list[str]
    security_fixes: list[str]
    bug_fixes: list[str]
    known_issues: list[str]
    deprecations: list[str]

    def has_changes(self) -> bool:
        return any([
            self.new_features, self.security_fixes,
            self.bug_fixes, self.known_issues, self.deprecations,
        ])


def firmware_diff(
    vendor: str,
    nos: str,
    current_version: str,
    target_version: Optional[str] = None,
    *,
    db_path: Path = DB_PATH,
) -> Optional[FirmwareDiff]:
    """
    Compute what the user gains by upgrading from current_version to
    target_version (or latest if not specified).

    Returns None if either version isn't in the DB.
    """
    all_releases = list_firmware(vendor, nos, db_path=db_path)
    if not all_releases:
        return None

    # Find the current release record
    current = next(
        (r for r in all_releases if r.version == current_version),
        None,
    )

    # If exact match not found, synthesize a minimal record from the input
    if not current:
        v = parse_version(current_version)
        if not v:
            return None
        current = FirmwareRecord(
            vendor=vendor, nos=nos, version=current_version,
        )

    # Decide target
    if target_version:
        target = next(
            (r for r in all_releases if r.version == target_version),
            None,
        )
        if not target:
            return None
    else:
        target = all_releases[0]  # newest

    # Versions in between (exclusive of current, inclusive of target)
    cur_v = parse_version(current.version)
    tgt_v = parse_version(target.version)
    if not cur_v or not tgt_v or cur_v >= tgt_v:
        return None

    intermediate = [
        r for r in all_releases
        if r.parsed and cur_v < r.parsed <= tgt_v
    ]
    intermediate.sort(key=lambda r: r.parsed.parts if r.parsed else ())

    # Aggregate changes across all intermediate releases
    def _aggregate(field_name: str) -> list[str]:
        seen = set()
        out = []
        for rec in intermediate:
            for item in getattr(rec, field_name):
                if item not in seen:
                    seen.add(item)
                    out.append(item)
        return out

    return FirmwareDiff(
        current=current,
        target=target,
        releases_behind=len(intermediate),
        intermediate_versions=intermediate,
        new_features=_aggregate("new_features"),
        security_fixes=_aggregate("security_fixes"),
        bug_fixes=_aggregate("bug_fixes"),
        known_issues=_aggregate("known_issues"),
        deprecations=_aggregate("deprecations"),
    )


# -----------------------------------------------------------------------------
# Security advisories (CVE data) — populated by scrapers.nvd_fetcher
# -----------------------------------------------------------------------------

@dataclass
class Advisory:
    """One CVE affecting a vendor's NOS. Mirrors security_advisories table."""
    cve_id: str
    vendor: str
    nos: Optional[str]
    published: Optional[str] = None
    last_modified: Optional[str] = None
    severity: Optional[str] = None      # CRITICAL / HIGH / MEDIUM / LOW
    cvss_score: Optional[float] = None
    cvss_vector: Optional[str] = None
    description: Optional[str] = None
    affected_ranges: list[dict] = field(default_factory=list)
    fixed_versions: list[str] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    source: Optional[str] = None


_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, None: 0}


def _row_to_advisory(row: sqlite3.Row) -> Advisory:
    def _j(value):
        if not value:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return Advisory(
        cve_id=row["cve_id"],
        vendor=row["vendor"],
        nos=row["nos"],
        published=row["published"],
        last_modified=row["last_modified"],
        severity=row["severity"],
        cvss_score=row["cvss_score"],
        cvss_vector=row["cvss_vector"],
        description=row["description"],
        affected_ranges=_j(row["affected_ranges"]),
        fixed_versions=_j(row["fixed_versions"]),
        references=_j(row["references_json"]),
        source=row["source"],
    )


def list_advisories(
    vendor: str, nos: Optional[str] = None, db_path: Path = DB_PATH,
) -> list[Advisory]:
    """Pull cached CVE rows for a vendor (optionally narrowed by NOS).

    NOS matching is tolerant: switch rows often have heterogeneous nos
    labels ('OS10 / SONiC', 'ArubaOS-CX' vs 'AOS-CX'), so we expand the
    requested nos into common variants. The query is built with an IN
    clause to keep it a single round-trip."""
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        if nos:
            variants = _nos_match_variants(nos)
            placeholders = ",".join("?" * len(variants))
            rows = con.execute(
                f"SELECT * FROM security_advisories "
                f"WHERE vendor=? AND nos IN ({placeholders})",
                (vendor, *variants),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM security_advisories WHERE vendor=?",
                (vendor,),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    return [_row_to_advisory(r) for r in rows]


def _version_in_range(version: Version, rng: dict) -> bool:
    """True iff `version` falls inside the {start, start_incl, end, end_incl}
    range. None bounds mean unbounded on that side."""
    start = parse_version(rng.get("start")) if rng.get("start") else None
    end = parse_version(rng.get("end")) if rng.get("end") else None
    start_incl = bool(rng.get("start_incl"))
    end_incl = bool(rng.get("end_incl"))
    if start is not None:
        if start_incl:
            if version < start:
                return False
        else:
            if version <= start:
                return False
    if end is not None:
        if end_incl:
            if version > end:
                return False
        else:
            if version >= end:
                return False
    return True


def advisories_for_version(
    vendor: str,
    nos: Optional[str],
    current_version: str,
    db_path: Path = DB_PATH,
) -> list[Advisory]:
    """Return all known CVEs whose affected ranges include current_version.
    Sorted highest-severity first, then by CVSS score, then by date."""
    v = parse_version(current_version)
    if v is None:
        return []
    matching: list[Advisory] = []
    for adv in list_advisories(vendor, nos, db_path=db_path):
        for rng in adv.affected_ranges:
            if _version_in_range(v, rng):
                matching.append(adv)
                break
    matching.sort(
        key=lambda a: (
            -_SEVERITY_RANK.get((a.severity or "").upper(), 0),
            -(a.cvss_score or 0.0),
            a.published or "",
        )
    )
    return matching


def minimum_fixed_version(advisories: list[Advisory]) -> Optional[str]:
    """Across a list of advisories, find the smallest 'fixed_versions' entry
    that's >= all known fixes. Heuristic — vendors don't always backport, so
    the user should still read the per-CVE notes."""
    fixes = []
    for a in advisories:
        for fv in a.fixed_versions:
            v = parse_version(fv)
            if v is not None:
                fixes.append(v)
    if not fixes:
        return None
    return max(fixes).raw


# -----------------------------------------------------------------------------
# Top-level advice
# -----------------------------------------------------------------------------

# Vendors whose firmware info is publicly accessible (can be ingested)
# Only vendors we actually have a working public fetcher for. (Netgear /
# TP-Link were listed here before but have no fetcher — that made advise()
# tell users to run a fetcher that doesn't exist. Honest = list reality.)
PUBLIC_FIRMWARE_VENDORS = {
    "MikroTik": "RouterOS",
    "Ubiquiti": "UniFi OS",
    "NVIDIA": "Cumulus Linux",
}

# vendor -> fetch_firmware.py key (only where a fetcher actually exists)
FETCHER_KEYS = {
    "MikroTik": "mikrotik",
    "Ubiquiti": "ubiquiti",
    "NVIDIA": "cumulus",
}

# Vendors whose full *release notes* are behind a vendor login portal —
# but whose security advisories ARE publicly available via NIST NVD and
# ingested by scrapers.nvd_fetcher. We surface the CVE data even when we
# don't have the full changelog.
LOGIN_GATED_VENDORS = {
    "Cisco": "https://software.cisco.com",
    "Juniper": "https://support.juniper.net/support/downloads/",
    "Arista": "https://www.arista.com/en/support/software-download",
    "HPE Aruba": "https://asp.arubanetworks.com",
    "Dell": "https://www.dell.com/support",  # partially public
    "Fortinet": "https://support.fortinet.com",
}

# vendor -> default NOS used when caller didn't specify one and the
# vendor's release notes are login-gated (so we can't infer NOS from
# firmware_versions). Used to pick the right CVE bucket.
DEFAULT_GATED_NOS = {
    "HPE Aruba": "ArubaOS-CX",
    "Cisco": "IOS-XE",
    "Juniper": "Junos",
    "Arista": "EOS",
    "Dell": "OS10",
    "Fortinet": "FortiSwitch",
}


def _nos_match_variants(nos: str) -> list[str]:
    """Generate plausible nos string variants so a switch row with
    nos='OS10 / SONiC' still matches advisories stored under 'OS10', and
    'ArubaOS-CX' matches 'AOS-CX', etc."""
    if not nos:
        return []
    raw = nos.strip()
    out = {raw, raw.lower()}
    # Split on " / " for combo strings like "OS10 / SONiC / Cumulus".
    for part in re.split(r"\s*/\s*", raw):
        part = part.strip()
        if part:
            out.add(part)
    # Aruba aliases
    if "aruba" in raw.lower() or "aos" in raw.lower():
        out.update({"ArubaOS-CX", "AOS-CX", "ArubaOS", "AOS-S"})
    return [v for v in out if v]


@dataclass
class FirmwareAdvice:
    """Result of an advise() call - always returned, even when no data."""
    vendor: str
    nos: Optional[str]
    current_version: str
    has_data: bool
    message: str = ""
    diff: Optional[FirmwareDiff] = None
    portal_url: Optional[str] = None
    # CVE data — populated from security_advisories (NVD). Independent of
    # diff, which comes from firmware_versions (vendor changelog).
    advisories: list[Advisory] = field(default_factory=list)
    recommended_min_version: Optional[str] = None
    # True when full release notes need a vendor login (CVE data may still
    # be available below via `advisories`).
    release_notes_gated: bool = False


def advise(
    *,
    vendor: str,
    nos: Optional[str],
    current_version: str,
    model: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> FirmwareAdvice:
    """
    Top-level firmware advice. Always returns a FirmwareAdvice (never None).

    Combines two independent data sources:
      - firmware_versions  (vendor changelogs — public-vendor fetchers)
      - security_advisories (CVE data from NIST NVD — works for all
        major vendors including login-gated ones)

    For login-gated vendors we still surface CVE data and an
    "earliest fix" version recommendation, instead of just bouncing the
    user to a login portal.
    """
    gated = vendor in LOGIN_GATED_VENDORS

    # Decide which NOS to query. Priority:
    #   1. Explicit nos= argument
    #   2. Canonical NOS for vendors we publish firmware for
    #   3. Default NOS for login-gated vendors (CVE data is bucketed per-NOS)
    canonical = PUBLIC_FIRMWARE_VENDORS.get(vendor)
    if canonical:
        nos = canonical
    elif not nos and gated:
        nos = DEFAULT_GATED_NOS.get(vendor)
    if not nos:
        return FirmwareAdvice(
            vendor=vendor, nos=None,
            current_version=current_version,
            has_data=False,
            message=f"No NOS specified and no default known for {vendor}.",
        )

    # Pull CVE data first — it's the layer that works for every vendor.
    advisories = advisories_for_version(
        vendor, nos, current_version, db_path=db_path,
    )
    min_fix = minimum_fixed_version(advisories) if advisories else None

    # Then try the changelog diff (vendor-published release notes).
    diff = firmware_diff(vendor, nos, current_version, db_path=db_path)

    if gated:
        portal = LOGIN_GATED_VENDORS[vendor]
        if advisories:
            msg = (
                f"Found {len(advisories)} published CVE(s) affecting "
                f"{vendor} {nos} {current_version}. Full release notes for "
                f"this NOS require a vendor login (see portal link), but "
                f"the security-advisory data below is from NIST NVD and "
                f"is up-to-date."
            )
        else:
            # No CVEs match this version — could mean the version string
            # doesn't match NVD's CPE format, or the version is unaffected,
            # or we haven't ingested NVD yet.
            n_total = len(list_advisories(vendor, nos, db_path=db_path))
            if n_total == 0:
                msg = (
                    f"No security-advisory data cached for {vendor} {nos}. "
                    f"Run `python3 fetch_firmware.py nvd --nvd-vendor "
                    f"{vendor.split()[-1].lower()}` to populate it from "
                    f"NIST NVD (free, no login)."
                )
            else:
                msg = (
                    f"{n_total} CVE(s) are known for {vendor} {nos}, but "
                    f"none match firmware version {current_version}. Either "
                    f"the version is unaffected or the version string is "
                    f"not in the NVD-recognized format. Full release notes "
                    f"require a vendor login."
                )
        return FirmwareAdvice(
            vendor=vendor, nos=nos,
            current_version=current_version,
            has_data=bool(advisories) or bool(diff),
            message=msg,
            diff=diff,
            portal_url=portal,
            advisories=advisories,
            recommended_min_version=min_fix,
            release_notes_gated=True,
        )

    # Non-gated vendors: prefer the changelog diff, fall back to advisory data.
    if not diff:
        if not list_firmware(vendor, nos, db_path=db_path):
            key = FETCHER_KEYS.get(vendor)
            if key:
                msg = (f"No firmware data cached for {vendor} {nos}. "
                       f"Populate it: `python3 fetch_firmware.py {key}`.")
            else:
                msg = (f"No public firmware source available for {vendor} "
                       f"{nos} at $0/no-LLM. Check the vendor's support "
                       f"site for release notes.")
            return FirmwareAdvice(
                vendor=vendor, nos=nos,
                current_version=current_version,
                has_data=bool(advisories),
                message=msg,
                advisories=advisories,
                recommended_min_version=min_fix,
            )
        return FirmwareAdvice(
            vendor=vendor, nos=nos,
            current_version=current_version,
            has_data=True,
            message=(
                f"{current_version} appears to be at or newer than the latest "
                f"known release. Nothing to upgrade to."
            ),
            advisories=advisories,
            recommended_min_version=min_fix,
        )

    return FirmwareAdvice(
        vendor=vendor, nos=nos,
        current_version=current_version,
        has_data=True,
        diff=diff,
        advisories=advisories,
        recommended_min_version=min_fix,
    )


# -----------------------------------------------------------------------------
# Plain-text formatting (no LLM, just print)
# -----------------------------------------------------------------------------

def format_advice(advice: FirmwareAdvice) -> str:
    """Render a FirmwareAdvice as plain text suitable for CLI output."""
    lines = []
    header = f"{advice.vendor} {advice.nos or ''} firmware advice".strip()
    lines.append(header)
    lines.append("=" * len(header))

    if not advice.has_data:
        lines.append(f"\n  {advice.message}")
        if advice.portal_url:
            lines.append(f"\n  Portal: {advice.portal_url}")
        return "\n".join(lines)

    if not advice.diff:
        lines.append(f"\n  Current: {advice.current_version}")
        lines.append(f"  {advice.message}")
        return "\n".join(lines)

    d = advice.diff
    lines.append(f"\n  Current:  {d.current.version}")
    if d.current.release_date:
        lines.append(f"            released {d.current.release_date}")
    lines.append(f"  Latest:   {d.target.version}")
    if d.target.release_date:
        lines.append(f"            released {d.target.release_date}")
    lines.append(f"  Behind:   {d.releases_behind} release(s)")

    if d.security_fixes:
        lines.append("\n  Security fixes you would gain:")
        for fix in d.security_fixes[:10]:
            lines.append(f"    + {fix}")
        if len(d.security_fixes) > 10:
            lines.append(f"    ... and {len(d.security_fixes) - 10} more")

    if d.new_features:
        lines.append("\n  New features since your version:")
        for feat in d.new_features[:10]:
            lines.append(f"    + {feat}")
        if len(d.new_features) > 10:
            lines.append(f"    ... and {len(d.new_features) - 10} more")

    if d.bug_fixes:
        lines.append(f"\n  Bug fixes: {len(d.bug_fixes)} resolved since your version")
        for fix in d.bug_fixes[:5]:
            lines.append(f"    + {fix}")
        if len(d.bug_fixes) > 5:
            lines.append(f"    ... and {len(d.bug_fixes) - 5} more")

    if d.known_issues:
        lines.append("\n  Known issues still open in the target version:")
        for issue in d.known_issues[:5]:
            lines.append(f"    ! {issue}")

    if d.deprecations:
        lines.append("\n  Things removed/deprecated (read before upgrading):")
        for dep in d.deprecations[:5]:
            lines.append(f"    - {dep}")

    if d.target.is_recommended:
        lines.append(
            f"\n  This release is marked as vendor-recommended "
            f"({d.target.train or 'stable'})."
        )

    if d.target.release_notes_url:
        lines.append(f"\n  Release notes: {d.target.release_notes_url}")

    return "\n".join(lines)

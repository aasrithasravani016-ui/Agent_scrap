#!/usr/bin/env python3
"""
run_diagnostics.py - One-shot test runner for the Switch Spec Agent.

Drop this file in the project root (next to cli.py) and run:

    python run_diagnostics.py

It will test every scraper, every firmware fetcher, and every coverage tier,
then write ONE output file: diagnostics_report.txt

Send that file back. Safe to run unattended - all failures captured to the
report rather than crashing.

Options:
    python run_diagnostics.py             # full test (~10-15 min)
    python run_diagnostics.py --quick     # skip live fallback (offline only)
    python run_diagnostics.py --limit N   # test only first N vendors
"""
from __future__ import annotations

import argparse
import platform
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# What to test - edit if your vendor list differs
# ---------------------------------------------------------------------------

# (cli_alias, model_1, model_2)  - 2 models per vendor
FULL_SCRAPER_VENDORS = [
    ("cisco",    "Cisco Catalyst 9300-48P",    "Cisco Nexus 9336C-FX2"),
    ("arista",   "Arista 7050SX3-48YC8",       "Arista 7280CR3-32D4"),
    ("juniper",  "Juniper EX4400-48P",         "Juniper QFX5120-48Y"),
    ("aruba",    "Aruba 6300M-48G-PoE4+",      "Aruba 8325-48Y8C"),
    ("dell",     "Dell S5248F-ON",             "Dell Z9332F-ON"),
    ("nvidia",   "NVIDIA SN4700",              "NVIDIA SN5600"),
    ("extreme",  "Extreme 5520-48W",           "Extreme 7520-48Y"),
    ("huawei",   "Huawei CE6865-48S8CQ-EI",    "Huawei S6730-H48X6C"),
    ("fortinet", "FortiSwitch-448E-FPOE",      "FortiSwitch-1048E"),
    ("ubiquiti", "USW-Pro-24-PoE",             "USW-Enterprise-24-PoE"),
    ("mikrotik", "CRS326-24G-2S+RM",           "CRS354-48G-4S+2Q+RM"),
    ("tplink",   "TL-SG3428",                  "TL-SG3210XHP-M2"),
    ("netgear",  "M4350-48G4XF",               "GS752TPP"),
    ("h3c",      "H3C S6850-56HF",             "H3C S5560X-30C-EI"),
    ("ruijie",   "Ruijie RG-S6520-48ST6X-HI",  "Ruijie RG-S6920-4C"),
    ("edgecore", "Edgecore AS7726-32X",        "Edgecore AS9716-32D"),
    ("zyxel",    "Zyxel XGS4600-32F",          "Zyxel XS1930-12HP"),
    ("lenovo",   "Lenovo NE10032",             "Lenovo NE2572"),
]

# Login-gated firmware (agent should honestly say "check portal")
LOGIN_GATED_FW_TESTS = [
    ("Cisco Catalyst 9300-48P",  "17.6.4"),
    ("Arista 7050SX3-48YC8",     "4.28.6M"),
    ("Juniper EX4400-48P",       "21.4R3"),
    ("Aruba 6300M-48G-PoE4+",    "10.10.1000"),
]

# Public firmware (need fetch_firmware.py to populate first)
PUBLIC_FW_TESTS = [
    ("mikrotik", "MikroTik CRS326-24G-2S+RM",   "7.10.2"),
    ("ubiquiti", "USW-Pro-24-PoE",              "6.5.59"),
    ("cumulus",  "NVIDIA SN4700",               "5.4.0"),
    ("tplink",   "TL-SG3428",                   "1.0.0"),
    ("netgear",  "M4350-48G4XF",                "13.0.5.20"),
]

# No-custom-scraper vendors - should work via live fallback
LIVE_FALLBACK_VENDORS = [
    "D-Link DGS-1520-28MP",
    "Allied Telesis AT-x550-18XSPQm",
    "Moxa EDS-G508E",
    "Hirschmann RSP30",
    "FS.com S5860-48SC",
    "Cambium cnMatrix EX2052-P",
]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.pass_count = 0
        self.fail_count = 0
        self.warn_count = 0
        self.skip_count = 0
        self.start = time.time()

    def h1(self, title):
        self.lines.extend(["", "=" * 70, f"  {title}", "=" * 70])

    def h2(self, title):
        self.lines.extend(["", "-" * 70, f"  {title}", "-" * 70])

    def text(self, *msgs):
        for m in msgs:
            self.lines.append(str(m))

    def passed(self, label, detail=""):
        self.pass_count += 1
        self.lines.append(f"  [PASS] {label}" + (f"  -- {detail}" if detail else ""))

    def failed(self, label, detail=""):
        self.fail_count += 1
        self.lines.append(f"  [FAIL] {label}" + (f"  -- {detail}" if detail else ""))

    def warn(self, label, detail=""):
        self.warn_count += 1
        self.lines.append(f"  [WARN] {label}" + (f"  -- {detail}" if detail else ""))

    def skip(self, label, detail=""):
        self.skip_count += 1
        self.lines.append(f"  [SKIP] {label}" + (f"  -- {detail}" if detail else ""))

    def block(self, content, indent=8, max_lines=40):
        prefix = " " * indent
        lines = str(content).splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines // 2] + [
                f"... [{len(lines) - max_lines} lines truncated] ..."
            ] + lines[-max_lines // 2:]
        for line in lines:
            self.lines.append(prefix + line)

    def summary(self):
        elapsed = time.time() - self.start
        self.h1("SUMMARY")
        self.text(f"  Pass:    {self.pass_count}")
        self.text(f"  Fail:    {self.fail_count}")
        self.text(f"  Warn:    {self.warn_count}")
        self.text(f"  Skip:    {self.skip_count}")
        self.text(f"  Elapsed: {elapsed:.1f}s")

    def write(self, path):
        Path(path).write_text("\n".join(self.lines) + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cmd(cmd, timeout=60, cwd=None):
    """Run command. Return (returncode, stdout, stderr, elapsed)."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        return proc.returncode, proc.stdout, proc.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout}s", time.time() - t0
    except FileNotFoundError as e:
        return -2, "", f"Not found: {e}", time.time() - t0
    except Exception as e:
        return -3, "", f"{type(e).__name__}: {e}", time.time() - t0


def cli_lookup(query, *, timeout=15, verbose=False, no_live=False, firmware=None):
    cmd = [sys.executable, "cli.py"]
    # NOTE: this cli.py has no -v/--verbose flag; passing it makes argparse
    # exit 2 ("unrecognized arguments: -v") and every lookup falsely FAILs.
    _ = verbose  # accepted for API compatibility, intentionally unused
    if no_live: cmd.append("--no-live")
    if firmware:
        cmd.extend(["--firmware", query, firmware])
    else:
        cmd.append(query)
    return run_cmd(cmd, timeout=timeout)


# ---------------------------------------------------------------------------
# Test stages
# ---------------------------------------------------------------------------

def stage_environment(r):
    r.h1("STAGE 1 - Environment")
    r.text(f"  Python:    {sys.version.split()[0]}")
    r.text(f"  Platform:  {platform.platform()}")
    r.text(f"  Directory: {Path.cwd()}")
    r.text(f"  Timestamp: {datetime.now().isoformat()}")

    files = ["cli.py", "agent.py", "build_db.py", "schema.sql"]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        r.failed("Critical files", f"missing: {missing}")
        r.text("")
        r.text("  >>> Run this from your project root (where cli.py lives).")
        return False
    r.passed("Critical files present")

    optional = {
        "scrapers/__init__.py": "scrapers package",
        "firmware.py": "firmware module",
        "firmware_fetchers.py": "firmware fetchers",
        "live_extract.py": "live fallback",
        "live_search.py": "search module",
        "tests/smoke_test.py": "smoke test",
    }
    for path, name in optional.items():
        if Path(path).exists():
            r.passed(f"Has {name}")
        else:
            r.warn(f"Missing {name}", path)
    return True


def stage_smoke(r):
    r.h1("STAGE 2 - Smoke tests")
    if not Path("tests/smoke_test.py").exists():
        r.skip("No tests/smoke_test.py")
        return
    rc, out, err, elapsed = run_cmd(
        [sys.executable, "tests/smoke_test.py"], timeout=60,
    )
    if rc == 0:
        last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
        r.passed("Smoke tests", f"{elapsed:.1f}s, {last}")
    else:
        r.failed("Smoke tests", f"exit={rc}")
    r.block(out + ("\nSTDERR:\n" + err if err.strip() else ""))


def stage_build_db(r):
    r.h1("STAGE 3 - Build database")
    if not Path("build_db.py").exists():
        r.skip("No build_db.py")
        return False
    rc, out, err, _ = run_cmd([sys.executable, "build_db.py"], timeout=60)
    if rc == 0:
        r.passed("Build DB")
        r.block(out)
        return True
    r.failed("Build DB", f"exit={rc}")
    r.block(out + "\n" + err)
    return False


def stage_db_contents(r):
    r.h1("STAGE 4 - Database contents")
    db = Path("data/switches.db")
    if not db.exists():
        r.failed("data/switches.db missing")
        return
    try:
        con = sqlite3.connect(db)
        tables = [t[0] for t in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        r.passed("Tables", str(tables))

        if "switches" in tables:
            rows = con.execute(
                "SELECT vendor, COUNT(*) FROM switches GROUP BY vendor ORDER BY vendor"
            ).fetchall()
            total = sum(n for _, n in rows)
            r.text(f"  Switches: {total} rows")
            for vendor, n in rows:
                r.text(f"    {vendor:25s} {n}")

        if "firmware_versions" in tables:
            fw = con.execute(
                "SELECT vendor, nos, COUNT(*) FROM firmware_versions "
                "GROUP BY vendor, nos ORDER BY vendor"
            ).fetchall()
            fw_total = sum(n for _, _, n in fw)
            r.text(f"  Firmware: {fw_total} versions")
            for vendor, nos, n in fw:
                r.text(f"    {vendor:15s} {nos:30s} {n}")
        con.close()
    except Exception as e:
        r.failed("DB inspect", str(e))
        r.block(traceback.format_exc())


def stage_offline_lookups(r):
    r.h1("STAGE 5 - Seeded lookups (offline, fast)")
    tests = [
        ("Cisco Catalyst 9300-48P", "Cisco"),
        ("C9300-48P", "Cisco"),
        ("Arista 7050SX3-48YC8", "Arista"),
        ("EX4400-48P", "Juniper"),
        ("USW-Pro-24-PoE", "Ubiquiti"),
    ]
    for query, expect_vendor in tests:
        rc, out, err, elapsed = cli_lookup(query, timeout=15, no_live=True)
        if rc == 0 and expect_vendor.lower() in out.lower():
            r.passed(f"Seeded: {query}", f"{elapsed*1000:.0f}ms")
        elif rc == 0:
            r.warn(f"Seeded: {query}", f"no '{expect_vendor}' in output")
        else:
            r.failed(f"Seeded: {query}", f"exit={rc}")
            if err.strip():
                r.block(err[:500])


def stage_live_fallback_known(r, args):
    r.h1("STAGE 6 - Live fallback (vendors WITH scrapers)")
    if args.quick:
        r.skip("--quick: skipping live tests")
        return

    vendors = FULL_SCRAPER_VENDORS
    if args.limit:
        vendors = vendors[:args.limit]

    for vendor_alias, model1, model2 in vendors:
        r.h2(f"Vendor: {vendor_alias}")
        for model in (model1, model2):
            rc, out, err, elapsed = cli_lookup(model, timeout=45, verbose=True)
            if rc != 0:
                r.failed(f"{model}", f"exit={rc}, {elapsed:.1f}s")
                r.block(err[:800] if err.strip() else out[:800])
                continue

            # Did we get something useful?
            out_low = out.lower()
            looks_good = any(kw in out_low for kw in (
                "ports", "switching", "vendor", "datasheet"
            ))
            looks_empty = "no matching" in out_low or len(out.strip()) < 50

            if looks_empty:
                r.failed(f"{model}", f"empty result, {elapsed:.1f}s")
            elif looks_good:
                # Extract first useful info line for the summary
                summary = next(
                    (ln.strip() for ln in out.splitlines()
                     if ln.strip() and not ln.startswith(" ")),
                    "(no header)",
                )[:80]
                r.passed(f"{model}", f"{elapsed:.1f}s | {summary}")
            else:
                r.warn(f"{model}", f"unclear output, {elapsed:.1f}s")


def stage_live_fallback_unknown(r, args):
    r.h1("STAGE 7 - Live fallback (vendors WITHOUT scrapers)")
    if args.quick:
        r.skip("--quick: skipping")
        return
    for model in LIVE_FALLBACK_VENDORS:
        rc, out, err, elapsed = cli_lookup(model, timeout=45, verbose=True)
        if rc != 0:
            r.failed(model, f"exit={rc}")
            r.block((err or out)[:500])
            continue
        out_low = out.lower()
        if "no matching" in out_low or len(out.strip()) < 50:
            r.failed(model, f"empty, {elapsed:.1f}s")
        else:
            r.passed(model, f"{elapsed:.1f}s")


def stage_login_gated_firmware(r):
    r.h1("STAGE 8 - Login-gated firmware (honest portal message)")
    for model, version in LOGIN_GATED_FW_TESTS:
        rc, out, err, _ = cli_lookup(model, firmware=version, timeout=20)
        if rc != 0:
            r.failed(f"{model} v{version}", f"exit={rc}")
            r.block(err[:300])
            continue
        out_low = out.lower()
        if any(kw in out_low for kw in ("login", "portal", "credentials", "support contract")):
            r.passed(f"{model} v{version}", "honest message")
        else:
            r.warn(f"{model} v{version}", "no portal message - check format")
            r.block(out[:400])


def stage_firmware_fetchers(r, args):
    r.h1("STAGE 9 - Firmware fetchers")
    if not Path("fetch_firmware.py").exists():
        r.skip("No fetch_firmware.py")
        return
    if args.quick:
        r.skip("--quick: skipping")
        return

    fetchers = ["mikrotik", "ubiquiti", "cumulus", "tplink", "netgear"]
    for f in fetchers:
        r.h2(f"Firmware: {f}")
        rc, out, err, elapsed = run_cmd(
            [sys.executable, "fetch_firmware.py", f, "-v"],
            timeout=120,
        )
        if rc != 0:
            r.failed(f"fetch_firmware {f}", f"exit={rc}")
            r.block((err or out)[:800])
            continue
        # Look for "X versions fetched" or similar
        if "0 versions" in out or "no data" in out.lower():
            r.warn(f"fetch_firmware {f}", "0 versions fetched")
            r.block(out[:600])
        else:
            r.passed(f"fetch_firmware {f}", f"{elapsed:.1f}s")
            # Capture summary line
            for line in out.splitlines():
                if "versions" in line.lower() or "Total" in line:
                    r.text(f"        {line.strip()}")


def stage_firmware_advisor(r):
    r.h1("STAGE 10 - Firmware advisor (public vendors with data)")
    for vendor, model, old_ver in PUBLIC_FW_TESTS:
        rc, out, err, elapsed = cli_lookup(model, firmware=old_ver, timeout=20)
        if rc != 0:
            r.failed(f"{model} v{old_ver}", f"exit={rc}")
            r.block(err[:300])
            continue
        out_low = out.lower()
        if "no firmware data" in out_low or "run the firmware fetcher" in out_low:
            r.warn(f"{model} v{old_ver}", "no data - run fetcher first")
        elif "behind" in out_low or "latest" in out_low:
            r.passed(f"{model} v{old_ver}", "structured diff produced")
        else:
            r.warn(f"{model} v{old_ver}", "unclear output")
            r.block(out[:300])


def stage_scraper_discovery(r, args):
    r.h1("STAGE 11 - Scraper discovery (3 vendors, --limit 2)")
    if not Path("run_scrapers.py").exists():
        r.skip("No run_scrapers.py")
        return
    if args.quick:
        r.skip("--quick: skipping")
        return
    # Test 3 vendors with --limit 2 to keep total time reasonable
    test_vendors = ["ubiquiti", "mikrotik", "h3c"]
    for v in test_vendors:
        r.h2(f"Scraper: {v}")
        rc, out, err, elapsed = run_cmd(
            [sys.executable, "run_scrapers.py", v, "-v", "--limit", "2"],
            timeout=120,
        )
        if rc != 0:
            r.failed(f"run_scrapers {v}", f"exit={rc}")
            r.block((err or out)[:600])
            continue
        # Look for "Found N models"
        if "0 models" in out.lower() or "found 0" in out.lower():
            r.failed(f"run_scrapers {v}", "0 models found")
        else:
            r.passed(f"run_scrapers {v}", f"{elapsed:.1f}s")
        # Always include the last 20 lines for context
        last_lines = out.strip().splitlines()[-20:]
        r.block("\n".join(last_lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quick", action="store_true",
                   help="Skip live fallback tests (offline only)")
    p.add_argument("--limit", type=int, default=None,
                   help="Test only first N vendors")
    p.add_argument("-o", "--output", default="diagnostics_report.txt",
                   help="Output file path")
    args = p.parse_args()

    r = Report()
    r.h1("SWITCH SPEC AGENT - DIAGNOSTICS REPORT")
    r.text(f"  Started: {datetime.now().isoformat()}")
    if args.quick:
        r.text("  Mode: QUICK (offline only)")
    if args.limit:
        r.text(f"  Vendor limit: {args.limit}")

    try:
        if not stage_environment(r):
            r.summary()
            r.write(args.output)
            print(f"\nReport written to {args.output}")
            print("Fix the missing files first, then re-run.")
            return

        stage_smoke(r)
        # Stage 3 (build_db) intentionally skipped: it would unlink and
        # rebuild data/switches.db from seed_data.json (54 records, 0
        # images), destroying the 240-record image-rich DB the app uses.
        r.h1("STAGE 3 - Build database")
        r.skip("build_db.py SKIPPED to preserve the live 240-record image DB")
        stage_db_contents(r)
        stage_offline_lookups(r)
        stage_live_fallback_known(r, args)
        stage_live_fallback_unknown(r, args)
        stage_login_gated_firmware(r)
        stage_firmware_fetchers(r, args)
        stage_firmware_advisor(r)
        stage_scraper_discovery(r, args)

    except KeyboardInterrupt:
        r.h1("INTERRUPTED")
        r.text("  User stopped the run with Ctrl+C")
    except Exception as e:
        r.h1("UNEXPECTED ERROR")
        r.text(f"  {type(e).__name__}: {e}")
        r.block(traceback.format_exc())

    r.summary()
    r.write(args.output)
    print(f"\nReport written to {args.output}")
    print(f"  Pass: {r.pass_count}  Fail: {r.fail_count}  "
          f"Warn: {r.warn_count}  Skip: {r.skip_count}")
    print(f"\nSend {args.output} back and I'll analyze it.")


if __name__ == "__main__":
    main()

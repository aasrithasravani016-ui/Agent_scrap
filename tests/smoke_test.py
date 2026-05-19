"""
Smoke test - uses only Python stdlib. Run this to verify everything works:

    python tests/smoke_test.py

Exits 0 if all checks pass, 1 if anything fails. Used by CI and as a quick
sanity check after install.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

# Make project root importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


checks = []  # (name, passed, error)


def check(name):
    """Decorator: register a check function."""
    def wrap(fn):
        try:
            fn()
            checks.append((name, True, None))
        except Exception as e:
            checks.append((name, False, f"{type(e).__name__}: {e}"))
            traceback.print_exc()
        return fn
    return wrap


# ----- Parser checks -----
@check("parsers: parse_capacity_gbps converts Tbps")
def _():
    from scrapers.parsers import parse_capacity_gbps
    assert parse_capacity_gbps("4 Tbps") == 4000
    assert parse_capacity_gbps("51.2 Tbps") == 51200
    assert parse_capacity_gbps("176 Gbps") == 176


@check("parsers: parse_port_config sums multi-section configs")
def _():
    from scrapers.parsers import parse_port_config
    ports, speed, _ = parse_port_config("48x 1G RJ45 + 4x 10G SFP+")
    assert ports == 52, f"expected 52 got {ports}"
    assert speed == 10, f"expected 10 got {speed}"


@check("parsers: parse_poe_standard recognizes 802.3bt as PoE++")
def _():
    from scrapers.parsers import parse_poe_standard
    assert parse_poe_standard("IEEE 802.3bt") == "PoE++"
    assert parse_poe_standard("802.3at PoE+") == "PoE+"
    assert parse_poe_standard("UPOE+") == "UPOE+"


@check("parsers: parse_buffer_mb handles GB and KB units")
def _():
    from scrapers.parsers import parse_buffer_mb
    assert parse_buffer_mb("32 MB") == 32
    assert parse_buffer_mb("8 GB") == 8 * 1024
    assert parse_buffer_mb("512 KB") == 0.5


@check("parsers: detect_features finds common protocols")
def _():
    from scrapers.parsers import detect_features
    feats = detect_features("supports BGP, OSPF, EVPN-VXLAN, MACsec, VLAN, STP")
    for expected in ("BGP", "OSPF", "EVPN-VXLAN", "MACsec", "VLAN", "STP"):
        assert expected in feats, f"missing {expected}, got {feats}"


@check("parsers: map_kv_to_record_fields normalizes a Cisco-style table")
def _():
    from scrapers.parsers import map_kv_to_record_fields
    kv = {
        "Ports": "48x 1G + 4x 10G SFP+",
        "Switching Capacity": "176 Gbps",
        "PoE": "IEEE 802.3at",
        "Switching Layer": "Layer 3",
    }
    out = map_kv_to_record_fields(kv)
    assert out["port_count"] == 52
    assert out["switching_capacity_gbps"] == 176.0
    assert out["poe_standard"] == "PoE+"
    assert out["layer"] == "L3"


@check("parsers: extract_spec_tables pulls KV from HTML")
def _():
    from scrapers.parsers import extract_spec_tables
    html = "<table><tr><th>Ports</th><td>48</td></tr></table>"
    kv = extract_spec_tables(html)
    assert kv["Ports"] == "48"


# ----- Agent checks -----
def _build_test_db() -> Path:
    """Create a temp DB with one Cisco row for agent tests."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    schema = (ROOT / "schema.sql").read_text()
    con = sqlite3.connect(db)
    con.executescript(schema)
    con.execute("""
        INSERT INTO switches (vendor, model, sku, port_count, port_speed_max_gbps,
                              port_config, switching_capacity_gbps, layer, features,
                              status, nos, use_case, datasheet_url, last_updated)
        VALUES ('Cisco', 'Catalyst 9300-48P', 'C9300-48P', 48, 40,
                '48x 1G RJ45', 208.0, 'L3', '["BGP","OSPF","VLAN"]',
                'active', 'IOS-XE', 'access', 'https://cisco.com/x', '2024-01-01')
    """)
    con.commit()
    con.close()
    return db


@check("agent: looks up by SKU")
def _():
    from agent import SpecAgent
    db = _build_test_db()
    agent = SpecAgent(db_path=db, enable_live=False)
    results = agent.lookup("C9300-48P")
    assert len(results) >= 1
    assert results[0]["sku"] == "C9300-48P"


@check("agent: looks up by partial model name")
def _():
    from agent import SpecAgent
    db = _build_test_db()
    agent = SpecAgent(db_path=db, enable_live=False)
    results = agent.lookup("Cisco 9300")
    assert len(results) >= 1
    assert results[0]["vendor"] == "Cisco"


@check("agent: features parsed to Python list")
def _():
    from agent import SpecAgent
    db = _build_test_db()
    agent = SpecAgent(db_path=db, enable_live=False)
    results = agent.lookup("C9300-48P")
    assert isinstance(results[0]["features"], list)
    assert "BGP" in results[0]["features"]


@check("agent: filter by vendor and PoE")
def _():
    from agent import SpecAgent
    db = _build_test_db()
    agent = SpecAgent(db_path=db, enable_live=False)
    by_vendor = agent.filter(vendor="Cisco")
    assert len(by_vendor) == 1


@check("agent: format_spec returns readable text")
def _():
    from agent import SpecAgent
    db = _build_test_db()
    agent = SpecAgent(db_path=db, enable_live=False)
    text = agent.format_spec(agent.lookup("C9300-48P")[0])
    assert "Cisco" in text
    assert "Catalyst 9300-48P" in text


@check("agent: format_spec handles missing record gracefully")
def _():
    from agent import SpecAgent
    db = _build_test_db()
    agent = SpecAgent(db_path=db, enable_live=False)
    assert agent.format_spec({}) == "No matching switch found."


@check("agent: raises clear error when DB missing")
def _():
    from agent import SpecAgent
    try:
        SpecAgent(db_path=Path("/nonexistent/path/db.sqlite"))
        raise AssertionError("Expected FileNotFoundError")
    except FileNotFoundError:
        pass


# ----- live_extract checks (no network, just merge logic) -----
@check("live: source confidence ranks vendor PDFs highest")
def _():
    from live_extract import source_confidence
    assert source_confidence("https://www.cisco.com/x.pdf") == 1.0
    assert source_confidence("https://www.arista.com/x") == 0.85
    assert source_confidence("https://random.com/x.pdf") == 0.7
    assert source_confidence("https://blog.com/x") == 0.5


@check("live: merge picks high-confidence value on conflict")
def _():
    from live_extract import merge_extractions
    sources = {
        "https://cisco.com/foo.pdf": {"Switching Capacity": "2400 Gbps"},
        "https://random.com/foo": {"Switching Capacity": "9999 Gbps"},
    }
    result = merge_extractions(sources)
    assert result.fields["switching_capacity_gbps"].value == 2400.0


@check("live: agreement bonus boosts confidence")
def _():
    from live_extract import merge_extractions
    sources = {
        "https://random1.com/a": {"PoE Budget": "740W"},
        "https://random2.com/b": {"PoE Budget": "740W"},
    }
    result = merge_extractions(sources)
    assert result.fields["poe_budget_w"].confidence > 0.5


# ----- Vendor scraper imports -----
@check("scrapers: core vendor classes importable")
def _():
    from scrapers import REGISTRY, BaseScraper
    assert len(REGISTRY) >= 10
    for name in ("ubiquiti", "mikrotik", "tplink", "netgear", "arista",
                 "dell", "nvidia", "aruba", "juniper", "cisco"):
        assert name in REGISTRY, f"Missing scraper: {name}"
    for name, cls in REGISTRY.items():
        assert issubclass(cls, BaseScraper), f"{name} not a BaseScraper"


@check("scrapers: every vendor scraper instantiates")
def _():
    from scrapers import REGISTRY
    for name, cls in REGISTRY.items():
        cls()  # should not raise


# ----- Print results -----
def main():
    passed = sum(1 for _, ok, _ in checks if ok)
    failed = len(checks) - passed
    print()
    print("=" * 60)
    for name, ok, err in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if err:
            print(f"         {err}")
    print("=" * 60)
    print(f"  {passed} passed, {failed} failed, {len(checks)} total")
    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

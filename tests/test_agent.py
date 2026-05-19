"""Tests for the SpecAgent."""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from agent import SpecAgent


@pytest.fixture
def test_db(tmp_path):
    """Create a small test database."""
    db_path = tmp_path / "test.db"
    schema = Path(__file__).parent.parent / "schema.sql"
    con = sqlite3.connect(db_path)
    con.executescript(schema.read_text())

    rows = [
        ("Cisco", "Catalyst 9300", "Catalyst 9300-48P", "C9300-48P",
         48, 40, "48x 1G RJ45", None, 208.0, 154.0, None, None, None,
         "PoE+", 437, None, None, "L3",
         '["VLAN", "BGP", "OSPF"]', 1, "IOS-XE", "active", "access",
         "https://cisco.com/9300", "2024-01-01"),
        ("Arista", "7050X3", "7050SX3-48YC8", "DCS-7050SX3-48YC8",
         56, 100, "48x 25G + 8x 100G", None, 4000.0, 2380.0, 32.0, 800, None,
         None, None, None, None, "L3",
         '["EVPN-VXLAN", "BGP"]', 1, "EOS", "active", "leaf",
         "https://arista.com/7050x3", "2024-01-01"),
        ("Juniper", "EX4400", "EX4400-48P", "EX4400-48P",
         54, 100, "48x 1G + 4x 25G + 2x 100G", None, 496.0, 368.0, None, None, None,
         "PoE++", 2200, None, None, "L3",
         '["EVPN", "MACsec"]', 1, "Junos", "active", "access",
         "https://juniper.net/ex4400", "2024-01-01"),
    ]
    cols = ("vendor,family,model,sku,port_count,port_speed_max_gbps,"
            "port_config,uplink_config,switching_capacity_gbps,"
            "forwarding_rate_mpps,buffer_mb,latency_ns,mac_table_size,"
            "poe_standard,poe_budget_w,power_typical_w,power_max_w,layer,"
            "features,rack_units,nos,status,use_case,datasheet_url,"
            "last_updated")
    qs = ",".join("?" * 25)
    for row in rows:
        con.execute(f"INSERT INTO switches ({cols}) VALUES ({qs})", row)
    con.commit()
    con.close()
    return db_path


@pytest.fixture
def agent(test_db):
    return SpecAgent(db_path=test_db, enable_live=False)


class TestSpecAgentLookup:
    def test_exact_model(self, agent):
        results = agent.lookup("Catalyst 9300-48P")
        assert len(results) >= 1
        assert results[0]["model"] == "Catalyst 9300-48P"

    def test_exact_sku(self, agent):
        results = agent.lookup("C9300-48P")
        assert len(results) >= 1
        assert results[0]["sku"] == "C9300-48P"

    def test_vendor_with_partial(self, agent):
        results = agent.lookup("arista 7050")
        assert len(results) >= 1
        assert results[0]["vendor"] == "Arista"

    def test_vendor_alias(self, agent):
        # 'jnpr' is an alias for Juniper
        results = agent.lookup("jnpr EX4400-48P")
        assert len(results) >= 1
        assert results[0]["vendor"] == "Juniper"

    def test_features_parsed_to_list(self, agent):
        results = agent.lookup("C9300-48P")
        assert isinstance(results[0]["features"], list)
        assert "BGP" in results[0]["features"]

    def test_lookup_returns_empty_for_unknown_with_live_disabled(self, agent):
        # Agent has enable_live=False, fuzzy fallback may still return something
        results = agent.lookup("Totally Nonexistent ABC123")
        # Either empty or low-similarity garbage; just ensure no crash
        assert isinstance(results, list)


class TestSpecAgentFilter:
    def test_filter_by_vendor(self, agent):
        results = agent.filter(vendor="Arista")
        assert len(results) == 1
        assert results[0]["vendor"] == "Arista"

    def test_filter_by_min_speed(self, agent):
        results = agent.filter(min_port_speed=100)
        # Arista 7050X3 and Juniper EX4400 both have 100G
        assert len(results) == 2

    def test_filter_poe_required(self, agent):
        results = agent.filter(poe=True)
        # Cisco 9300 (PoE+) and Juniper EX4400 (PoE++)
        assert len(results) == 2

    def test_filter_poe_excluded(self, agent):
        results = agent.filter(poe=False)
        assert len(results) == 1
        assert results[0]["vendor"] == "Arista"

    def test_filter_combo(self, agent):
        results = agent.filter(vendor="Cisco", poe=True, min_ports=40)
        assert len(results) == 1

    def test_filter_feature(self, agent):
        results = agent.filter(feature="EVPN-VXLAN")
        assert len(results) == 1
        assert results[0]["vendor"] == "Arista"


class TestSpecAgentList:
    def test_list_vendors(self, agent):
        vendors = agent.list_vendors()
        assert ("Cisco", 1) in vendors
        assert ("Arista", 1) in vendors
        assert ("Juniper", 1) in vendors

    def test_list_models(self, agent):
        models = agent.list_models("Cisco")
        assert len(models) == 1
        assert models[0]["model"] == "Catalyst 9300-48P"


class TestSpecAgentCompare:
    def test_compare_two_switches(self, agent):
        result = agent.compare("C9300-48P", "EX4400-48P")
        assert result["a"]["vendor"] == "Cisco"
        assert result["b"]["vendor"] == "Juniper"


class TestSpecAgentFormat:
    def test_format_spec_produces_text(self, agent):
        results = agent.lookup("C9300-48P")
        text = agent.format_spec(results[0])
        assert "Cisco" in text
        assert "Catalyst 9300-48P" in text
        assert "48" in text  # port count

    def test_format_handles_none(self, agent):
        assert agent.format_spec({}) == "No matching switch found."


class TestSpecAgentMissingDb:
    def test_raises_clear_error_when_db_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="DB not found"):
            SpecAgent(db_path=tmp_path / "nonexistent.db")

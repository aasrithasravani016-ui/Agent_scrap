"""Tests for scrapers/parsers.py - the field normalization layer."""
import pytest

from scrapers.parsers import (
    detect_features,
    extract_spec_tables,
    map_kv_to_record_fields,
    parse_buffer_mb,
    parse_capacity_gbps,
    parse_int,
    parse_layer,
    parse_poe_standard,
    parse_port_config,
)


# ---------- parse_int / parse_float ----------
class TestParseInt:
    def test_simple(self):
        assert parse_int("48") == 48

    def test_with_unit(self):
        assert parse_int("48 ports") == 48

    def test_with_comma(self):
        assert parse_int("16,000") == 16000

    def test_negative(self):
        assert parse_int("-5") == -5

    def test_no_number(self):
        assert parse_int("ports") is None

    def test_none(self):
        assert parse_int(None) is None

    def test_empty(self):
        assert parse_int("") is None


# ---------- parse_capacity_gbps ----------
class TestParseCapacity:
    @pytest.mark.parametrize("input,expected", [
        ("176 Gbps", 176),
        ("176Gbps", 176),
        ("4 Tbps", 4000),
        ("4.8 Tbps", 4800),
        ("51.2 Tbps", 51200),
        ("4 Tb/s", 4000),
        ("500 Mbps", 0.5),
    ])
    def test_units(self, input, expected):
        assert parse_capacity_gbps(input) == expected

    def test_none(self):
        assert parse_capacity_gbps(None) is None


# ---------- parse_buffer_mb ----------
class TestParseBuffer:
    @pytest.mark.parametrize("input,expected", [
        ("32 MB", 32),
        ("8 GB", 8 * 1024),
        ("512 KB", 0.5),
        ("16MB", 16),
    ])
    def test_units(self, input, expected):
        assert parse_buffer_mb(input) == expected


# ---------- parse_poe_standard ----------
class TestParsePoE:
    @pytest.mark.parametrize("input,expected", [
        ("IEEE 802.3bt", "PoE++"),
        ("PoE++ (90W)", "PoE++"),
        ("802.3at PoE+", "PoE+"),
        ("PoE+", "PoE+"),
        ("802.3af", "PoE"),
        ("UPOE+", "UPOE+"),
        ("UPOE plus", "UPOE+"),
        ("No PoE", "None"),
        ("None", "None"),
    ])
    def test_standards(self, input, expected):
        assert parse_poe_standard(input) == expected


# ---------- parse_layer ----------
class TestParseLayer:
    @pytest.mark.parametrize("input,expected", [
        ("Layer 3", "L3"),
        ("L3", "L3"),
        ("Layer 2+", "L2+"),
        ("L2+", "L2+"),
        ("Layer 2", "L2"),
        ("L2", "L2"),
    ])
    def test_layers(self, input, expected):
        assert parse_layer(input) == expected


# ---------- parse_port_config ----------
class TestParsePortConfig:
    def test_single_section(self):
        ports, speed, conf = parse_port_config("32x 100G QSFP28")
        assert ports == 32
        assert speed == 100

    def test_multi_section(self):
        ports, speed, conf = parse_port_config("48x 1G RJ45 + 4x 10G SFP+")
        assert ports == 52
        assert speed == 10

    def test_three_sections(self):
        ports, speed, conf = parse_port_config(
            "48x 1G RJ45 + 4x 25G SFP28 + 2x 100G QSFP28"
        )
        assert ports == 54
        assert speed == 100

    def test_high_speed(self):
        ports, speed, conf = parse_port_config("64x 800G OSFP")
        assert ports == 64
        assert speed == 800

    def test_no_match(self):
        ports, speed, conf = parse_port_config("Various ports")
        assert ports is None
        assert speed is None


# ---------- detect_features ----------
class TestDetectFeatures:
    def test_common_features(self):
        text = ("This switch supports BGP, OSPF, EVPN-VXLAN, and MACsec. "
                "VLAN and STP are available.")
        feats = detect_features(text)
        assert "BGP" in feats
        assert "OSPF" in feats
        assert "EVPN-VXLAN" in feats
        assert "MACsec" in feats
        assert "VLAN" in feats
        assert "STP" in feats

    def test_case_insensitive(self):
        feats = detect_features("supports bgp and OSPF")
        assert "BGP" in feats
        assert "OSPF" in feats

    def test_mlag_variants(self):
        assert "MLAG" in detect_features("supports MLAG")
        assert "MLAG" in detect_features("vPC peer link")
        assert "MLAG" in detect_features("Virtual Chassis")

    def test_no_features(self):
        assert detect_features("nothing relevant here") == []


# ---------- map_kv_to_record_fields ----------
class TestMapKvToFields:
    def test_basic_mapping(self):
        kv = {
            "Ports": "48x 1G + 4x 10G SFP+",
            "Switching Capacity": "176 Gbps",
            "Forwarding Rate": "130.95 Mpps",
            "PoE": "IEEE 802.3at (PoE+)",
            "PoE Budget": "740W",
            "Layer": "Layer 3",
        }
        out = map_kv_to_record_fields(kv)
        assert out["port_count"] == 52
        assert out["port_config"] == "48x 1G + 4x 10G SFP+"
        assert out["switching_capacity_gbps"] == 176.0
        assert out["forwarding_rate_mpps"] == 130.95
        assert out["poe_standard"] == "PoE+"
        assert out["poe_budget_w"] == 740
        assert out["layer"] == "L3"

    def test_case_insensitive_keys(self):
        kv = {"PORTS": "32x 100G", "SWITCHING CAPACITY": "6.4 Tbps"}
        out = map_kv_to_record_fields(kv)
        assert out["port_count"] == 32
        assert out["switching_capacity_gbps"] == 6400.0

    def test_unknown_keys_ignored(self):
        out = map_kv_to_record_fields({"Random key": "random value"})
        assert out == {}

    def test_empty_input(self):
        assert map_kv_to_record_fields({}) == {}


# ---------- HTML extraction ----------
class TestExtractSpecTables:
    def test_simple_table(self):
        html = """
        <html><body>
        <table>
        <tr><th>Ports</th><td>48</td></tr>
        <tr><th>Speed</th><td>1 Gbps</td></tr>
        </table>
        </body></html>
        """
        kv = extract_spec_tables(html)
        assert kv["Ports"] == "48"
        assert kv["Speed"] == "1 Gbps"

    def test_definition_list(self):
        html = """
        <dl>
        <dt>Ports</dt><dd>24</dd>
        <dt>Layer</dt><dd>L3</dd>
        </dl>
        """
        kv = extract_spec_tables(html)
        assert kv["Ports"] == "24"
        assert kv["Layer"] == "L3"

    def test_no_tables(self):
        assert extract_spec_tables("<p>just text</p>") == {}

    def test_handles_whitespace(self):
        html = "<table><tr><th>  Ports  </th><td>\n48\n</td></tr></table>"
        kv = extract_spec_tables(html)
        assert kv["Ports"] == "48"

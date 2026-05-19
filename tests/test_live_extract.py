"""Tests for live_extract merging logic. Does NOT hit the network."""
import pytest

from live_extract import (
    merge_extractions,
    parse_source,
    source_confidence,
)


class TestSourceConfidence:
    def test_vendor_pdf_highest(self):
        assert source_confidence("https://www.cisco.com/c/dam/foo.pdf") == 1.0

    def test_vendor_html(self):
        assert source_confidence("https://www.arista.com/products/x") == 0.85

    def test_random_pdf(self):
        assert source_confidence("https://random.com/datasheet.pdf") == 0.7

    def test_random_html(self):
        assert source_confidence("https://random-blog.com/article") == 0.5


class TestMergeExtractions:
    def test_empty_input(self):
        result = merge_extractions({})
        assert result.fields == {}
        assert result.features == []

    def test_single_source(self):
        sources = {
            "https://cisco.com/foo.pdf": {
                "Ports": "48x 1G + 4x 10G SFP+",
                "Switching Capacity": "176 Gbps",
            }
        }
        result = merge_extractions(sources)
        assert "port_count" in result.fields
        assert result.fields["port_count"].value == 52
        assert result.fields["switching_capacity_gbps"].value == 176.0

    def test_vendor_pdf_beats_reseller_on_conflict(self):
        sources = {
            "https://cisco.com/foo.pdf": {  # confidence 1.0
                "Switching Capacity": "2400 Gbps",
            },
            "https://random-reseller.com/foo": {  # confidence 0.5
                "Switching Capacity": "9999 Gbps",  # wrong value
            },
        }
        result = merge_extractions(sources)
        # High-confidence vendor wins
        assert result.fields["switching_capacity_gbps"].value == 2400.0
        assert result.fields["switching_capacity_gbps"].source.startswith("https://cisco.com")

    def test_agreement_boosts_confidence(self):
        sources = {
            "https://random1.com/a": {"PoE Budget": "740W"},
            "https://random2.com/b": {"PoE Budget": "740W"},
        }
        result = merge_extractions(sources)
        # Two random sources agree -> confidence > 0.5
        fv = result.fields["poe_budget_w"]
        assert fv.value == 740
        assert fv.confidence > 0.5

    def test_features_detected(self):
        sources = {
            "https://cisco.com/foo.pdf": {
                "Features": "BGP, OSPF, EVPN-VXLAN, MACsec",
            }
        }
        result = merge_extractions(sources)
        assert "BGP" in result.features
        assert "EVPN-VXLAN" in result.features
        assert "MACsec" in result.features


class TestParseSourceHtml:
    def test_html_table(self):
        html = b"""
        <html><body>
        <table>
        <tr><th>Ports</th><td>48</td></tr>
        <tr><th>Switching Capacity</th><td>176 Gbps</td></tr>
        </table>
        </body></html>
        """
        kv = parse_source("https://example.com/page", html)
        assert kv.get("Ports") == "48"
        assert kv.get("Switching Capacity") == "176 Gbps"

    def test_empty_content(self):
        assert parse_source("https://example.com", b"") == {}

    def test_non_pdf_non_html(self):
        # Should still try to decode as HTML
        kv = parse_source("https://example.com", b"random text")
        assert kv == {}

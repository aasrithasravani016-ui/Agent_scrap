"""
Scraper registry. Maps vendor names to their scraper classes.
"""
from .aruba import ArubaScraper
from .arista import AristaScraper
from .base import BaseScraper, SpecRecord, upsert_records
from .cisco import CiscoScraper
from .dell import DellScraper
from .extreme import ExtremeScraper
from .fortinet import FortinetScraper
from .huawei import HuaweiScraper
from .juniper import JuniperScraper
from .mikrotik import MikroTikScraper
from .netgear import NetgearScraper
from .nvidia import NvidiaScraper
from .tplink import TPLinkScraper
from .ubiquiti import UbiquitiScraper


REGISTRY: dict[str, type[BaseScraper]] = {
    "ubiquiti": UbiquitiScraper,
    "mikrotik": MikroTikScraper,
    "tplink":   TPLinkScraper,
    "netgear":  NetgearScraper,
    "arista":   AristaScraper,
    "dell":     DellScraper,
    "nvidia":   NvidiaScraper,
    "aruba":    ArubaScraper,
    "juniper":  JuniperScraper,
    "cisco":    CiscoScraper,
    "extreme":  ExtremeScraper,
    "fortinet": FortinetScraper,
    "huawei":   HuaweiScraper,
}

__all__ = ["REGISTRY", "BaseScraper", "SpecRecord", "upsert_records"]

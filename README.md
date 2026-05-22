# switch-spec-agent

A no-LLM, $0-stack agent that returns network-switch specifications and firmware/
security info for any vendor + model. Local SQLite knowledge base, per-vendor
scrapers, and a live-web fallback when the KB doesn't have a hit.

## Layout

```
switch-spec-agent/
├── agent.py              SpecAgent — the public entry point (answer / lookup / firmware_advise)
├── cli.py                CLI wrapper around SpecAgent
├── app.py                Streamlit UI (5 tabs)
│
├── firmware.py           Firmware advisor: layers CVE data over release-note data
├── firmware_fetchers.py  Per-vendor firmware release-note fetchers (Tier 1)
├── live_firmware.py      Live web fallback for firmware versions (Tier 3)
├── live_extract.py       Live web fallback for specs (multi-engine search + parse)
├── live_search.py        Search-engine shim (Startpage → Mojeek → DDG)
├── vendor_registry.py    Canonical vendor names + aliases (vendors.json)
├── logging_config.py     Shared logging setup
│
├── schema.sql            SQLite schema (switches + firmware_versions + security_advisories)
├── seed_data.json        Hand-curated seed for the switches table
├── vendors.json          Vendor registry (134 vendors, aliases, portal URLs)
├── requirements.txt
│
├── data/
│   └── switches.db       Built DB (gitignored except for the committed snapshot)
├── data_cache/           HTTP response cache, per vendor (.gitignored)
│
├── scrapers/             Per-vendor spec scrapers + NVD CVE fetcher + CISA KEV overlay
│   ├── __init__.py       REGISTRY, upsert_records
│   ├── base.py           HttpClient + SpecRecord
│   ├── parsers.py        HTML/PDF parsers (incl. find_product_image)
│   ├── nvd_fetcher.py    NIST NVD CVE puller (for login-gated vendors)
│   ├── cisa_kev_fetcher.py  CISA actively-exploited overlay
│   └── <vendor>.py       arista, aruba, cisco, dell, edgecore, extreme,
│                         fortinet, h3c, huawei, juniper, lenovo, mikrotik,
│                         netgear, nvidia, ruijie, tplink, ubiquiti, zyxel
│
├── scripts/              One-shot build / fetch / report scripts (run from project root)
│   ├── build_db.py                     Build data/switches.db from seed_data.json
│   ├── run_scrapers.py                 Run per-vendor spec scrapers
│   ├── backfill_images.py              Backfill image_url on switches missing one
│   ├── fetch_firmware.py               Fetch firmware versions + NVD CVEs + CISA KEV
│   ├── prefetch_firmware.py            Sequential live firmware lookup for every vendor
│   ├── build_groundtruth_and_test.py   Generate fleet ground-truth CSV/XLSX/HTML
│   └── build_groundtruth_v2.py         v2 of the ground-truth report
│
└── .streamlit/config.toml
```

## Quickstart

```bash
pip3 install -r requirements.txt

# Build the DB if data/switches.db doesn't exist
python3 scripts/build_db.py

# CLI
python3 cli.py "Arista 7050X3"

# Streamlit UI
python3 -m streamlit run app.py
```

## Run from the project root

All scripts in `scripts/` are designed to be invoked from the project root so
their sibling-module imports resolve:

```bash
python3 scripts/run_scrapers.py ubiquiti mikrotik
python3 scripts/fetch_firmware.py nvd --nvd-vendor cisco
python3 scripts/build_groundtruth_v2.py
```

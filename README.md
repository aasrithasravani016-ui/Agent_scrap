# Switch Spec Agent

An agent that fetches network switch specifications for **any vendor, any
model**, in **under 10 seconds**, with **no LLMs, no paid APIs, no monthly
cost**. Pure Python: SQLite + regex + HTML/PDF parsing + free multi-engine
web search.

This is the single consolidated version (all `switch-spec-agent-*` variants
were merged into this one).

## What it does

Ask about any switch — known or unknown:
- `"Cisco Catalyst 9300-48P"` → **~1 ms** (local DB hit)
- `"Arista 7050SX3-48YC8"` → **~1 ms** (local DB hit)
- `"Fortinet FortiSwitch 448E"` → **~4 s** (live web fetch + extraction, then cached)
- `"Zyxel XGS2220-30"` → **~4 s** (same — vendor not even seeded)

After the first live lookup the result is cached in the DB; repeat queries
are instant.

## How it stays fast and free

```
                      "Fortinet FortiSwitch 448E"
                                 |
                     +-----------v-----------+
                     |  SQLite lookup (1-5ms)|
                     +-----------+-----------+
                                 |
                           hit ?-+-? miss
                          /              \
                  return                 Live fallback (no LLM)
                 (instant)                       |
                              +------------------v------------------+
                              | Web search: Startpage -> Mojeek      |
                              |  -> DuckDuckGo  (free, no API key)   |
                              +------------------+------------------+
                                                 |
                              +------------------v------------------+
                              | Fetch top sources in parallel,       |
                              | parse HTML + PDF, merge with voting  |
                              +------------------+------------------+
                                                 |
                                  cache in SQLite + return  (~4 s)
```

No LLMs. No API keys. Pure code throughout.

> Note on search: DuckDuckGo's HTML endpoint now hard-blocks scraping
> (HTTP 202). The agent tries **Startpage → Mojeek → DuckDuckGo** and uses
> the first that responds, so the live fallback keeps working.

## Intelligence (without LLMs)

1. **Multi-source merging.** Live lookup fetches several sources in parallel, extracts from each, and merges with voting + confidence scoring.
2. **Source-aware confidence.** Vendor-domain PDFs = 1.0, vendor HTML = 0.85, random PDF = 0.7, reseller = 0.5. Higher confidence wins on conflict.
3. **Agreement bonus.** When 2+ sources agree, confidence is boosted.
4. **PDF table extraction** via `pdfplumber`/`pymupdf`, with text-pattern fallback.
5. **Cross-vendor normalization.** "switching capacity/bandwidth/throughput" → one field; PoE variants → `PoE++`; Tbps→Gbps, GB→MB.
6. **Vendor disambiguation.** `mellanox`→NVIDIA, `aruba`→HPE Aruba, `cloudengine`→Huawei, `usw`→Ubiquiti, etc.
7. **Graceful degradation.** If no-LLM parsing can't crack a messy PDF, it still returns the official datasheet URL + detected features rather than nothing.

## Coverage

Pre-built scrapers (10 vendors): Cisco · Arista · Juniper · HPE Aruba · Dell ·
NVIDIA · Ubiquiti · MikroTik · TP-Link · Netgear. Plus the live fallback for
**any other vendor** (Extreme, Huawei, H3C, Fortinet, Ruijie, Zyxel, D-Link,
Edgecore, Cambium, FS, …) with no custom scraper needed.

The shipped DB grows as you run scrapers / use the live fallback — check
`python3 cli.py "vendors"` anytime.

## Setup

```bash
cd switch-spec-agent
pip3 install -r requirements.txt     # web UI + scrapers + live PDF parsing
# No build step needed — the DB auto-builds from seed on first run.
```

Use **`python3`** on this machine (there is no `python` / bare `streamlit`).

## Use it

### CLI
```bash
python3 cli.py "Cisco Catalyst 9300-48P"     # known, instant
python3 cli.py "Fortinet FortiSwitch 448E"   # unknown, live fallback ~4s
python3 cli.py --no-live "X9999 Foobar"      # disable live (fail fast)
python3 cli.py "compare C9300-48P vs EX4400-48P"
python3 cli.py "which switches support 400G"
python3 cli.py --firmware "MikroTik CRS326-24G-2S+RM" 7.10.2   # firmware advice
python3 cli.py                                # interactive REPL
```

### Python
```python
from agent import SpecAgent
agent = SpecAgent(enable_live=True)           # `live=True` also works
results = agent.lookup("Cisco Catalyst 9300-48P")
print(results[0]["switching_capacity_gbps"], results[0].get("datasheet_url"))
print(agent.answer("which switches support 400G"))
```

### Web UI
```bash
python3 -m streamlit run app.py   # 6 tabs: Ask/Search/Filter/Compare/Browse/Firmware advisor
```

## Switch image + firmware advisor

- **Product image** — when the live fallback fetches a vendor HTML product
  page, it extracts the product photo (`og:image` → JSON-LD → ranked
  `<img>`) into `image_url` and the UI shows it next to the specs. Cached
  with the record. (PDF-only datasheet results have no image — by design;
  PDFs are skipped.)
- **Firmware version advisor** — `cli.py --firmware MODEL VERSION` or the
  Firmware advisor UI. Populate data with `python3 fetch_firmware.py
  <mikrotik|ubiquiti|cumulus>`. Honest coverage (no fabricated notes):
  - **MikroTik** — full: 15 versions with parsed security/feature/bug
    deltas (plain-text changelog feed).
  - **Ubiquiti** — 61 versions via the public firmware JSON API:
    version-delta + release dates + official notes link (no per-release
    changelog text exists in the source).
  - **NVIDIA Cumulus** — latest version pointer + official "What's New"
    link (docs are JS-nav; only the current version is discoverable).
  - **Login-gated** (Cisco/Juniper/Arista/Aruba) — honest portal link,
    never a guess.

## Growing the DB

1. **Hand-curate** — edit `seed_data.json`, `python3 build_db.py`.
2. **Run scrapers** — `python3 run_scrapers.py tplink` (cached in `data_cache/`, supports `--dry-run`/`--limit`/`--rebuild`).
3. **Live fallback** — every unknown-model query auto-caches; the DB grows with real usage.

## Testing

```bash
python3 tests/smoke_test.py        # stdlib-only, 19 checks, <1s
python3 -m pytest tests/ -q        # full unit suite, 81 tests
python3 run_tests.py               # query/behaviour suite, 34 checks
```

## Architecture for integration

| File | What it does |
|------|--------------|
| `agent.py` | `SpecAgent` — `answer()` router, `lookup()/filter()/compare()`, live-fallback hook |
| `live_search.py` | Free multi-engine web search |
| `live_extract.py` | `live_lookup(query)` — fetch + parse + multi-source merge (~9 s deadline) |
| `scrapers/parsers.py` | No-LLM normalization + `find_product_image()` |
| `scrapers/base.py` | HTTP cache, `SpecRecord`, `upsert_records()` |
| `firmware.py` | Version compare + `advise()` (read-only over DB) |
| `firmware_fetchers.py` / `fetch_firmware.py` | Populate the firmware registry |

Schema in `schema.sql`: `switches` table (now incl. `image_url`) +
`firmware_versions` table. The data is just data.

## Honest limitations

- **No complete dataset of every switch exists** anywhere — coverage is built up by scrapers + on-demand live fallback.
- **No LLM ⇒ best-effort extraction.** Clean spec tables parse well; messy multi-product vendor PDFs return the datasheet URL + features, not fabricated numbers. Check the `confidence` map before trusting a single field.
- **Dell, Juniper, Aruba bot-block a plain $0 client** (Dell 403s robots.txt; Juniper redirects to a 403 HPE store; Aruba = Akamai 403). Covered on-demand via the live fallback, not bulk-scraped.
- **First live lookup ~4 s; repeats instant** (cached). Search engines can rate-limit under heavy use — pre-run scrapers for common models.
- **Firmware data is empty until fetched, and fetchers are best-effort.** The advisor *logic* (version compare, diff, honest messaging) is solid, but the per-vendor firmware fetchers scrape changelog pages and have the same fragility as the spec scrapers — some vendors won't yield data without fixing their fetcher. Login-gated vendors never will (returns a portal link).
- **Product image only when an HTML product page is fetched** — PDF-only results have none.
- **No reasoning.** This fetches specs; it does not recommend or design networks. By design — a fetcher, not a thinker.

## Cost

| Item | Cost |
|------|------|
| Development / running locally | $0 |
| Live web search (Startpage/Mojeek/DDG, no key) | $0 |
| Scrapers, hosting (Streamlit Cloud / local) | $0 |
| **Total** | **$0/mo** |

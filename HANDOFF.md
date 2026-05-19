# Switch Spec Agent — Handoff

A network-switch specification + firmware advisor agent. Pure Python.
**No paid APIs. No LLMs. $0/month.** SQLite-backed. Runs on your hardware.

This is the single consolidated, git-tracked project. All earlier
`switch-spec-agent-*` folders were merged into this one and discarded.

## What you have

- **One git repo**: `/Users/aasritha/agent/switch-spec-agent/` (branch `main`)
- ~238 switch models in `data/switches.db` (seed + scraped; the DB is a
  build artifact and is gitignored — `seed_data.json` + scrapers regenerate it)
- **13 vendor scrapers**: Cisco, Arista, Juniper, HPE Aruba, Dell, NVIDIA,
  Ubiquiti, MikroTik, TP-Link, Netgear, **Extreme, Fortinet, Huawei**
- Live web fallback for any other vendor/model (no scraper needed)

## Capabilities

- Spec lookup by vendor / model / SKU; compare; capability filters
- Natural-language `answer()` router with honest "not in DB" handling
- Live fallback: multi-engine search (Startpage → Mojeek → DuckDuckGo) +
  multi-source extraction + confidence-scored merge, auto-cached
- Product **image** capture (og:image / JSON-LD) shown in the UI
- **Firmware version advisor** (CLI + UI tab): version-compare engine +
  structured diff; honest portal link for login-gated vendors
- Graceful degradation: messy PDFs return datasheet + features, never
  fabricated numbers

## Quick start

```bash
cd /Users/aasritha/agent/switch-spec-agent
pip3 install -r requirements.txt          # optional: UI + scrapers + PDF
# DB auto-builds from seed on first run — no manual step.

python3 cli.py "Cisco Catalyst 9300-48P"
python3 cli.py "Fortinet FortiSwitch 448E"            # live fallback + image
python3 cli.py --firmware "MikroTik CRS326-24G-2S+RM" 7.10.2
python3 -m streamlit run app.py                       # 6-tab web UI
python3 run_scrapers.py fortinet extreme huawei       # grow the DB
```

## Tests

```bash
python3 -m pytest tests/ -q     # 81 passed
python3 run_tests.py            # 34/34 query/behaviour
python3 tests/smoke_test.py     # 19/19 stdlib-only
```

## Known limits (honest, by design — no LLM, $0)

- No complete switch dataset exists anywhere; coverage grows via scrapers +
  live fallback.
- No LLM ⇒ best-effort extraction; arbitrary messy PDFs → datasheet + features.
- Dell / Juniper / Aruba bot-block a plain client → live-fallback only.
- `firmware_versions` starts empty; per-vendor firmware fetchers are
  best-effort (same scraping fragility); login-gated vendors return a portal
  link, never a guess.
- Product image only when a vendor HTML page is among fetched sources.

## Working in this repo

Make changes **here** and commit — do not create new `-N` folders.

```bash
git add -A && git commit -m "what changed"
git log --oneline
```

Author identity: `aasrithasravani016`.

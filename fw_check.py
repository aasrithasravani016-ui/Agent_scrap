"""
Firmware advisor coverage check.

For every vendor in the local catalog, pick up to 2 models and run the
firmware advisor exactly the way the app does. Classify each result and
write a full human-readable report to fw_check_output.txt.

Categories
----------
  FULL            has_data + a real version diff (security/features/etc.)
  PARTIAL         has_data but no diff (already at/newer than latest known)
  LOGIN-GATED     vendor's release notes are behind a login portal
  NO PUBLIC DATA  switch not found, no NOS, or no firmware data available
  ERROR           the call raised (should not happen)

Run from the project directory:
    python3 fw_check.py
"""
import sys
import traceback
from collections import Counter
from datetime import datetime

from agent import SpecAgent
from firmware import format_advice

PROBE_VERSION = "1.0"          # deliberately old so upgradable devices diff
MODELS_PER_VENDOR = 2
OUT = "fw_check_output.txt"


def classify(adv) -> str:
    if adv.has_data and adv.diff:
        return "FULL"
    if adv.has_data and not adv.diff:
        return "PARTIAL"
    if not adv.has_data and getattr(adv, "portal_url", None):
        return "LOGIN-GATED"
    return "NO PUBLIC DATA"


def main() -> int:
    agent = SpecAgent()
    vendors = [v for v, _ in agent.list_vendors()]

    lines: list[str] = []
    counts: Counter = Counter()
    per_vendor: dict[str, list[str]] = {}

    def w(s: str = "") -> None:
        lines.append(s)

    w("FIRMWARE ADVISOR COVERAGE CHECK")
    w(f"Generated      : {datetime.now().isoformat(timespec='seconds')}")
    w(f"Probe version  : {PROBE_VERSION!r} (used for every model)")
    w(f"Models/vendor  : up to {MODELS_PER_VENDOR}")
    w(f"Vendors tested : {len(vendors)}")
    w("=" * 72)

    for vendor in vendors:
        models = agent.list_models(vendor)
        picks = [m["model"] for m in models[:MODELS_PER_VENDOR]]
        per_vendor[vendor] = []
        w("")
        w(f"### {vendor}  —  {len(models)} models in catalog, "
          f"testing {len(picks)}")
        w("-" * 72)

        for model in picks:
            query = f"{vendor} {model}"
            try:
                adv = agent.firmware_advise(query, PROBE_VERSION)
                cat = classify(adv)
                counts[cat] += 1
                per_vendor[vendor].append(cat)
                w("")
                w(f"[{cat}]  {query}   (current v{PROBE_VERSION})")
                w(format_advice(adv))
            except Exception as e:  # noqa: BLE001
                counts["ERROR"] += 1
                per_vendor[vendor].append("ERROR")
                w("")
                w(f"[ERROR]  {query}")
                w(f"  {e!r}")
                w(traceback.format_exc())

    w("")
    w("=" * 72)
    w("PER-VENDOR ROLLUP")
    w("-" * 72)
    for vendor in vendors:
        cats = per_vendor.get(vendor) or ["(no models)"]
        w(f"  {vendor:<16} {', '.join(cats)}")

    w("")
    w("SUMMARY")
    w("-" * 72)
    total = sum(counts.values())
    for cat in ("FULL", "PARTIAL", "LOGIN-GATED", "NO PUBLIC DATA", "ERROR"):
        if counts.get(cat):
            w(f"  {cat:<16} {counts[cat]:>4}")
    w(f"  {'TOTAL':<16} {total:>4}")

    text = "\n".join(lines) + "\n"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"--> written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

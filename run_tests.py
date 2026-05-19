"""Run every query in TEST_QUERIES.md through the agent and show the outcome.

    python3 run_tests.py            # one-line summary per query
    python3 run_tests.py -v         # also print the full result

Exit code is non-zero if any query in a "should match" section fails to
return a spec/compare/filter, or any "Not in KB" query wrongly matches.
"""
import re
import sys
import time
from pathlib import Path

from agent import SpecAgent

ROOT = Path(__file__).parent
VERBOSE = "-v" in sys.argv


def parse_sections(md_text):
    """Yield (section_title, [queries]) from the markdown test file."""
    section, queries = None, []
    in_block = False
    for line in md_text.splitlines():
        h = re.match(r"^##+\s+(.*)", line)
        if h:
            if section and queries:
                yield section, queries
            section, queries = h.group(1).strip(), []
            continue
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            q = line.split("#")[0].strip()      # strip inline comments
            if q:
                queries.append(q)
    if section and queries:
        yield section, queries


def main():
    # live=False: the "Not in KB" section must deterministically return
    # notfound (no network) — this suite tests the local KB + gate logic.
    agent = SpecAgent(live=False)
    md = (ROOT / "TEST_QUERIES.md").read_text()

    total = ok = 0
    failures = []
    for section, queries in parse_sections(md):
        expect_notfound = "not in kb" in section.lower()
        print(f"\n=== {section} ===")
        for q in queries:
            total += 1
            t0 = time.time()
            resp = agent.answer(q)
            ms = (time.time() - t0) * 1000
            rtype = resp["type"]

            if expect_notfound:
                passed = rtype == "notfound"
            else:
                passed = rtype in ("spec", "compare", "filter", "vendors")

            if rtype == "spec":
                detail = f'{resp["result"]["vendor"]} {resp["result"]["model"]} ({resp["confidence"]})'
            elif rtype == "compare":
                detail = " vs ".join(r["model"] for r in resp["results"])
            elif rtype == "filter":
                detail = f'{len(resp["results"])} match — {resp["message"]}'
            elif rtype == "vendors":
                detail = f'{len(resp["vendors"])} vendors'
            else:
                detail = resp["message"][:60]

            mark = "PASS" if passed else "FAIL"
            if passed:
                ok += 1
            else:
                failures.append((q, rtype, detail))
            print(f"  [{mark}] {q:<48} -> {rtype:<9} {ms:5.0f}ms  {detail}")
            if VERBOSE and rtype == "spec":
                print(agent.format_spec(resp["result"]))

    print(f"\n{'-'*60}\n{ok}/{total} passed")
    if failures:
        print("\nFailures:")
        for q, rt, d in failures:
            print(f"  - {q}  ->  {rt}: {d}")
        sys.exit(1)
    print("All good.")


if __name__ == "__main__":
    main()

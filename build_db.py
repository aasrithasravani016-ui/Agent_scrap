"""
Build the switch specifications database from seed_data.json.
Run this once to initialize, and again any time seed_data.json changes.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "switches.db"
SCHEMA_PATH = ROOT / "schema.sql"
SEED_PATH = ROOT / "seed_data.json"


def build():
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # rebuild fresh

    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA_PATH.read_text())

    seed = json.loads(SEED_PATH.read_text())
    now = datetime.now(timezone.utc).isoformat()
    rows = 0
    for rec in seed:
        rec = {**rec}
        # features list -> JSON string
        if isinstance(rec.get("features"), list):
            rec["features"] = json.dumps(rec["features"])
        rec["last_updated"] = now
        keys = ",".join(rec.keys())
        qs = ",".join("?" * len(rec))
        con.execute(f"INSERT INTO switches ({keys}) VALUES ({qs})", list(rec.values()))
        rows += 1
    con.commit()

    # Quick stats
    by_vendor = con.execute(
        "SELECT vendor, COUNT(*) FROM switches GROUP BY vendor ORDER BY vendor"
    ).fetchall()
    con.close()

    print(f"Built {DB_PATH}")
    print(f"Inserted {rows} switches across {len(by_vendor)} vendors:")
    for v, c in by_vendor:
        print(f"  {v:20s} {c}")


if __name__ == "__main__":
    build()

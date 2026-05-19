"""
Switch Spec Agent - answers spec questions about network switches.

Works in two modes:
- Free mode (no LLM): rule-based query parsing + SQL/fuzzy lookup. Always available.
- Enhanced mode (optional Claude API): better natural language understanding.

Designed for sub-second responses on a local SQLite DB.
"""
import json
import logging
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent")

DB_PATH = Path(__file__).parent / "data" / "switches.db"

# Known vendor aliases - extends what the user can type
VENDOR_ALIASES = {
    "cisco": "Cisco",
    "arista": "Arista",
    "juniper": "Juniper",
    "jnpr": "Juniper",
    "hpe": "HPE Aruba",
    "aruba": "HPE Aruba",
    "hp": "HPE Aruba",
    "dell": "Dell",
    "dell emc": "Dell",
    "nvidia": "NVIDIA",
    "mellanox": "NVIDIA",
    "ubnt": "Ubiquiti",
    "ubiquiti": "Ubiquiti",
    "unifi": "Ubiquiti",
    "mikrotik": "MikroTik",
    "mt": "MikroTik",
    "tp-link": "TP-Link",
    "tplink": "TP-Link",
    "tp link": "TP-Link",
    "omada": "TP-Link",
    "netgear": "Netgear",
}

# Spec field labels for pretty output
LABELS = {
    "vendor": "Vendor",
    "family": "Family",
    "model": "Model",
    "sku": "SKU",
    "port_count": "Ports",
    "port_config": "Port config",
    "uplink_config": "Uplinks",
    "port_speed_max_gbps": "Max port speed (Gbps)",
    "switching_capacity_gbps": "Switching capacity (Gbps)",
    "forwarding_rate_mpps": "Forwarding rate (Mpps)",
    "buffer_mb": "Buffer (MB)",
    "latency_ns": "Latency (ns)",
    "mac_table_size": "MAC table",
    "poe_standard": "PoE",
    "poe_budget_w": "PoE budget (W)",
    "power_typical_w": "Power typical (W)",
    "power_max_w": "Power max (W)",
    "layer": "Layer",
    "features": "Features",
    "rack_units": "Rack units",
    "nos": "Network OS",
    "status": "Status",
    "use_case": "Typical use",
    "datasheet_url": "Datasheet",
    "image_url": "Image",
}


def _norm(s) -> str:
    """Lowercase, keep only alphanumerics — for robust token matching."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def hay_core(hay: str, nt: str) -> bool:
    """True if the digit-anchored core of token `nt` appears in `hay`.

    Lets 'c9300' match '9300' and vice-versa, while still rejecting
    unrelated models. Both args are already _norm()'d.
    """
    m = re.search(r"\d.*", nt)
    core = m.group(0) if m else nt
    return len(core) >= 3 and (core in hay or hay in core)


class SpecAgent:
    def __init__(self, db_path: Path = DB_PATH, live: bool = True,
                 enable_live: bool | None = None):
        # live=True: on a DB miss, fall back to a free multi-engine web
        # lookup (+ multi-source extraction, ~4-9 s, then cached).
        # Set live=False for fully-offline / deterministic behaviour.
        # `enable_live` is a backward-compatible alias for `live`.
        if enable_live is not None:
            live = enable_live
        self.live = live
        if not db_path.exists():
            if db_path == DB_PATH:
                # Default DB missing: auto-build from seed so `streamlit
                # run app.py` / `cli.py` work with no manual build step.
                try:
                    import build_db
                    build_db.build()
                except Exception as e:
                    raise FileNotFoundError(
                        f"DB not found at {db_path} and auto-build failed "
                        f"({e}). Run `python3 build_db.py` first."
                    ) from e
            else:
                # Explicit custom path that doesn't exist -> clear error.
                raise FileNotFoundError(
                    f"DB not found at {db_path}. Run `python3 build_db.py` "
                    f"first, or pass a valid db_path."
                )
        # check_same_thread=False: Streamlit caches this agent via
        # @st.cache_resource and reruns the script on different threads
        # when widgets change (Filter/Browse). The agent is read-only,
        # so sharing the connection across threads is safe here.
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    # ---------- Query parsing ----------

    def _extract_vendor(self, q: str) -> Optional[str]:
        q_low = q.lower()
        # Longest alias wins (so "tp-link" beats "tp")
        for alias in sorted(VENDOR_ALIASES, key=len, reverse=True):
            if alias in q_low:
                return VENDOR_ALIASES[alias]
        return None

    def _extract_model_candidates(self, q: str) -> list[str]:
        """Pull out tokens that look like model/SKU identifiers."""
        # Match alphanumeric tokens with at least one digit and length >= 3
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\+\._/]{2,}", q)
        return [t for t in tokens if any(c.isdigit() for c in t)]

    # ---------- Lookup ----------

    def lookup(self, query: str, limit: int = 5) -> list[dict]:
        """
        Find switches matching the query.
        Strategy: exact SKU match -> exact model -> fuzzy on model+SKU+family.
        """
        vendor = self._extract_vendor(query)
        candidates = self._extract_model_candidates(query)

        # 1) Exact SKU or model match
        for tok in candidates:
            rows = self._exact(tok, vendor)
            if rows:
                return [self._row_to_dict(r) for r in rows[:limit]]

        # 2) Substring match (case-insensitive)
        for tok in candidates:
            rows = self._substring(tok, vendor)
            if rows:
                return [self._row_to_dict(r) for r in rows[:limit]]

        # 3) Fuzzy ranked match across all rows
        rows = self._fuzzy(query, vendor)
        return [self._row_to_dict(r) for r in rows[:limit]]

    def _exact(self, token: str, vendor: Optional[str]):
        sql = """SELECT * FROM switches
                 WHERE (UPPER(sku)=UPPER(?) OR UPPER(model)=UPPER(?))"""
        args = [token, token]
        if vendor:
            sql += " AND vendor=?"
            args.append(vendor)
        return self.con.execute(sql, args).fetchall()

    def _substring(self, token: str, vendor: Optional[str]):
        like = f"%{token}%"
        sql = """SELECT * FROM switches
                 WHERE (sku LIKE ? OR model LIKE ? OR family LIKE ?)"""
        args = [like, like, like]
        if vendor:
            sql += " AND vendor=?"
            args.append(vendor)
        return self.con.execute(sql, args).fetchall()

    def _fuzzy(self, query: str, vendor: Optional[str], top: int = 5):
        sql = "SELECT * FROM switches"
        args: list = []
        if vendor:
            sql += " WHERE vendor=?"
            args.append(vendor)
        rows = self.con.execute(sql, args).fetchall()
        q = query.lower()

        def score(row):
            haystack = " ".join(
                str(row[k] or "") for k in ("vendor", "family", "model", "sku")
            ).lower()
            return SequenceMatcher(None, q, haystack).ratio()

        ranked = sorted(rows, key=score, reverse=True)
        return ranked[:top]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("features"):
            try:
                d["features"] = json.loads(d["features"])
            except json.JSONDecodeError:
                pass
        return d

    # ---------- High-level operations ----------

    def list_vendors(self) -> list[tuple[str, int]]:
        return [
            (r[0], r[1]) for r in self.con.execute(
                "SELECT vendor, COUNT(*) FROM switches "
                "GROUP BY vendor ORDER BY vendor"
            ).fetchall()
        ]

    def list_models(self, vendor: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT * FROM switches WHERE vendor=? ORDER BY family, model", (vendor,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def filter(
        self,
        *,
        vendor: Optional[str] = None,
        min_port_speed: Optional[int] = None,
        min_ports: Optional[int] = None,
        poe: Optional[bool] = None,
        min_poe_w: Optional[int] = None,
        layer: Optional[str] = None,
        use_case: Optional[str] = None,
        feature: Optional[str] = None,
    ) -> list[dict]:
        clauses, args = [], []
        if vendor:
            clauses.append("vendor=?")
            args.append(vendor)
        if min_port_speed is not None:
            clauses.append("port_speed_max_gbps >= ?")
            args.append(min_port_speed)
        if min_ports is not None:
            clauses.append("port_count >= ?")
            args.append(min_ports)
        if poe is True:
            clauses.append("poe_standard IS NOT NULL AND poe_standard != 'None'")
        if poe is False:
            clauses.append("(poe_standard IS NULL OR poe_standard='None')")
        if min_poe_w is not None:
            clauses.append("poe_budget_w >= ?")
            args.append(min_poe_w)
        if layer:
            clauses.append("layer=?")
            args.append(layer)
        if use_case:
            clauses.append("use_case=?")
            args.append(use_case)
        if feature:
            clauses.append("features LIKE ?")
            args.append(f"%{feature}%")

        sql = "SELECT * FROM switches"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY vendor, model"
        rows = self.con.execute(sql, args).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def compare(self, query_a: str, query_b: str) -> dict:
        a = self.lookup(query_a, limit=1)
        b = self.lookup(query_b, limit=1)
        return {
            "a": a[0] if a else None,
            "b": b[0] if b else None,
        }

    # ---------- Natural-language router ----------

    def _token_in_record(self, rec: dict, tokens: list[str]) -> bool:
        """True if any model-token actually overlaps this record's id fields."""
        hay = _norm(f"{rec.get('model','')} {rec.get('sku','')} {rec.get('family','')}")
        for t in tokens:
            nt = _norm(t)
            if nt and (nt in hay or hay_core(hay, nt)):
                return True
        return False

    def answer(self, query: str) -> dict:
        """Parse intent from free text and dispatch. Returns a typed dict.

        Types: spec | compare | filter | vendors | notfound | empty
        The notfound case is the honest one: when the user names a specific
        model that isn't in the KB, we say so and flag the web-fallback hook
        rather than returning a misleading fuzzy match.
        """
        query = (query or "").strip()
        if not query:
            return {"type": "empty",
                    "message": "Ask about a switch, e.g. 'Cisco C9300-48P', "
                               "'compare C9300-48P vs EX4400-48P', "
                               "'which switches support 400G'."}

        ql = query.lower()
        if ql in ("vendors", "list vendors", "what vendors", "which vendors"):
            return {"type": "vendors",
                    "message": "Vendors in the knowledge base:",
                    "vendors": self.list_vendors()}

        # Comparison: "A vs B", "compare A and B", "A versus B"
        if " vs " in ql or " versus " in ql or ql.startswith("compare "):
            body = re.sub(r"^\s*compare\s+", "", ql, count=1)
            parts = [p.strip() for p in re.split(r"\bvs\b|\bversus\b|\band\b|,", body)
                     if p.strip()]
            if len(parts) >= 2:
                picked = []
                for p in parts[:4]:
                    res = self._gated_lookup(p)
                    if res.get("type") == "spec":
                        picked.append(res["result"])
                if len(picked) >= 2:
                    return {"type": "compare",
                            "message": "Side-by-side comparison:",
                            "results": picked}

        # Spec filters ("which/with/all ... 400G / PoE over 600W / spine / EVPN")
        filt = self._parse_filter(query)
        if filt:
            results = self.filter(**filt[1])
            return {"type": "filter", "message": filt[0], "results": results}

        # Otherwise: single-model spec lookup, gated.
        return self._gated_lookup(query)

    def _parse_filter(self, query: str):
        q = query.lower()
        listy = any(w in q for w in ("which", "with ", "have ", "support",
                                     "list ", "show ", "all ", "that do"))

        m = re.search(r"(\d{2,4})\s*g\b", q)
        if listy and m:
            spd = int(m.group(1))
            return (f"Switches with port speed >= {spd}G",
                    {"min_port_speed": spd})

        poe = re.search(r"poe[^0-9]{0,12}(\d{2,4})\s*w", q) or \
            re.search(r"(\d{2,4})\s*w[^0-9]{0,12}poe", q)
        if "poe" in q and poe:
            w = int(poe.group(1))
            return (f"Switches with PoE budget >= {w} W", {"min_poe_w": w})

        # Role keywords trigger on "which/list ..." OR a bare
        # "<role> switch(es)" OR just the role word on its own.
        role_ctx = listy or "switch" in q
        for kw, uc in (("spine", "spine"), ("leaf", "leaf"),
                       ("aggregation", "aggregation"), ("core", "core"),
                       ("tor", "ToR"), ("top of rack", "ToR"),
                       ("access", "access"), ("campus", "access")):
            if re.search(rf"\b{re.escape(kw)}\b", q) and (
                role_ctx or q.strip() in (kw, kw + "s")
            ):
                return (f"Switches for role: {uc}", {"use_case": uc})

        if listy and ("evpn" in q or "vxlan" in q):
            return ("Switches with EVPN-VXLAN", {"feature": "VXLAN"})
        if listy and "macsec" in q:
            return ("Switches with MACsec", {"feature": "MACsec"})
        if listy and re.search(r"\bl3\b|layer 3|layer3", q):
            return ("Layer-3 switches", {"layer": "L3"})
        return None

    def _gated_lookup(self, query: str) -> dict:
        """lookup(), but refuse to return a junk fuzzy match for a model
        the user named explicitly that isn't actually in the KB."""
        vendor = self._extract_vendor(query)
        tokens = self._extract_model_candidates(query)
        results = self.lookup(query, limit=5)

        if not results:
            return self._notfound(query, vendor)

        # If the user typed specific model/SKU tokens, at least one result
        # must really contain one of them. Pure fuzzy noise -> not found.
        if tokens and not any(self._token_in_record(r, tokens) for r in results):
            return self._notfound(query, vendor)

        ranked = results
        if tokens:
            ranked = sorted(
                results,
                key=lambda r: self._token_in_record(r, tokens),
                reverse=True,
            )
        top = ranked[0]
        conf = "high" if (tokens and self._token_in_record(top, tokens)) \
            else "medium" if not tokens else "low"
        alts = [{"vendor": r["vendor"], "model": r["model"]}
                for r in ranked[1:4]]
        return {"type": "spec",
                "message": f"Best match ({conf} confidence):",
                "result": top, "confidence": conf, "alternates": alts}

    def _notfound(self, query: str, vendor: Optional[str]) -> dict:
        # Live web fallback: not in the local DB -> search the web for
        # free, extract specs, cache into the DB, and return. This is
        # what makes the agent answer for ANY vendor/model, not just
        # the ~54 seeded ones.
        if self.live:
            live = self._live_lookup(query)
            if live is not None:
                return live

        if vendor:
            sugg = [m["model"] for m in self.list_models(vendor)][:10]
        else:
            sugg = [r["model"] for r in self.con.execute(
                "SELECT model FROM switches ORDER BY vendor LIMIT 10")]
        why = ("the live web lookup found nothing usable in time"
               if self.live else "live lookup is disabled")
        return {"type": "notfound",
                "message": f"'{query}' is not in the local database and "
                           f"{why}. Try a more specific model number, or add "
                           "it to seed_data.json / run the scrapers.",
                "suggestions": sugg}

    def _live_lookup(self, query: str) -> Optional[dict]:
        """Free web fallback. Returns a spec-shaped dict or None."""
        try:
            from dataclasses import asdict
            from live_extract import live_lookup
            rec = live_lookup(query, deadline_sec=8.5, persist=True)
        except Exception as e:
            logger.warning("live lookup failed: %s", e)
            return None
        if rec is None:
            return None
        # Refresh the fuzzy index so the freshly-cached model is found
        # instantly next time.
        try:
            self.con.commit()
        except Exception:
            pass
        result = {k: v for k, v in asdict(rec).items()}
        field_conf = getattr(rec, "confidence", {}) or {}
        return {"type": "spec",
                "message": "Not in the local DB — fetched live from the web "
                           "(now cached for instant future lookups):",
                "result": result,
                "confidence": "live-web",
                "source": "live",
                "field_confidence": field_conf,
                "alternates": []}

    @staticmethod
    def format_compare(records: list[dict]) -> str:
        keys = [k for k in LABELS if k != "datasheet_url"]
        headers = [r["model"] for r in records]
        wl = max(28, max((len(LABELS[k]) for k in keys), default=28))
        wc = max(20, max((len(h) for h in headers), default=20)) + 2
        out = [" " * wl + "".join(h.ljust(wc) for h in headers)]
        for k in keys:
            row = LABELS[k].ljust(wl)
            for r in records:
                v = r.get(k)
                if v is None or v == "":
                    v = "—"
                elif isinstance(v, list):
                    v = ", ".join(map(str, v))
                row += str(v).ljust(wc)
            out.append(row)
        return "\n".join(out)

    # ---------- Firmware advisor ----------

    def firmware_advise(self, query: str, current_version: str):
        """Look up the switch to determine vendor + NOS, then return a
        FirmwareAdvice (see firmware.py). Always returns an object."""
        from firmware import advise as _advise, FirmwareAdvice
        spec = self.lookup(query, limit=1)
        if not spec:
            return FirmwareAdvice(
                vendor="Unknown", nos=None,
                current_version=current_version,
                has_data=False,
                message=f"Switch not found: {query!r}",
            )
        s = spec[0]
        return _advise(
            vendor=s.get("vendor", ""),
            nos=s.get("nos"),
            current_version=current_version,
            model=s.get("model"),
        )

    # ---------- Formatting ----------

    @staticmethod
    def format_spec(spec: dict) -> str:
        """Pretty-print a single switch spec as plain text."""
        if not spec:
            return "No matching switch found."
        lines = []
        title = f"{spec.get('vendor', '')} {spec.get('model', '')}".strip()
        lines.append(title)
        lines.append("=" * len(title))
        for key, label in LABELS.items():
            val = spec.get(key)
            if val is None or val == "":
                continue
            if isinstance(val, list):
                val = ", ".join(val)
            lines.append(f"  {label:30s} {val}")
        return "\n".join(lines)

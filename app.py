"""
Streamlit web UI for the switch spec agent.

Two focused tools only:
  • Search specifications  (model lookup / comparison, live-fetch fallback)
  • Firmware advisor

Run:
    streamlit run app.py
"""
import time

import streamlit as st

from agent import SpecAgent, LABELS

st.set_page_config(
    page_title="Switch Spec Agent",
    page_icon="🔌",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "About": "Network Switch Spec Agent — switch specifications and "
        "firmware guidance.",
    },
)


def _inject_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"], .stApp {
            font-family: 'Inter', system-ui, sans-serif;
        }
        .stApp {
            background:
              radial-gradient(1200px 600px at 50% -10%, #E8EEFF 0%, rgba(232,238,255,0) 60%),
              linear-gradient(180deg, #F6F8FD 0%, #FFFFFF 40%);
        }
        section[data-testid="stSidebar"],
        [data-testid="collapsedControl"] { display: none; }

        .block-container {
            padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1000px;
        }
        h1, h2, h3 { letter-spacing: -0.02em; color: #0F1B33; }

        /* ---------- Hero ---------- */
        .hero {
            background: linear-gradient(135deg, #2F6FED 0%, #1E40AF 100%);
            border-radius: 22px; padding: 2.3rem 2.4rem;
            color: #fff; box-shadow: 0 18px 40px -18px rgba(31,64,175,.55);
            margin-bottom: 1.6rem;
        }
        .hero h1 {
            color: #fff; font-size: 2.05rem; font-weight: 800;
            margin: 0 0 .35rem;
        }
        .hero p { color: #DCE6FF; font-size: 1rem; margin: 0; max-width: 640px; }
        .hero .pill {
            display: inline-block; background: rgba(255,255,255,.16);
            color: #fff; font-size: .74rem; font-weight: 600;
            letter-spacing: .04em; text-transform: uppercase;
            padding: .28rem .7rem; border-radius: 999px; margin-bottom: .9rem;
        }

        /* ---------- Segmented nav (radio) ---------- */
        div[role="radiogroup"] {
            display: flex; gap: .4rem; background: #EEF2FB;
            padding: .35rem; border-radius: 14px; width: fit-content;
            margin: 0 auto 1.8rem; border: 1px solid #E3E8F0;
        }
        div[role="radiogroup"] > label {
            border-radius: 10px; padding: .55rem 1.25rem !important;
            margin: 0 !important; cursor: pointer; font-weight: 600;
            color: #5B6573; transition: all .15s ease;
        }
        div[role="radiogroup"] > label:has(input:checked) {
            background: #fff; color: #1E40AF;
            box-shadow: 0 4px 12px -4px rgba(31,64,175,.35);
        }
        div[role="radiogroup"] > label > div:first-child { display: none; }

        /* ---------- Cards ---------- */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #fff; border: 1px solid #E6EAF2 !important;
            border-radius: 18px !important; padding: 1.6rem 1.7rem !important;
            box-shadow: 0 14px 34px -22px rgba(15,27,51,.25);
        }
        .stImage img { border-radius: 14px; background: #F7F9FC;
            border: 1px solid #EDF1F7; padding: 8px; }

        /* ---------- Metric tiles ---------- */
        [data-testid="stMetric"] {
            background: linear-gradient(180deg,#F8FAFF 0%,#F2F5FC 100%);
            border: 1px solid #E6EAF2; border-radius: 14px;
            padding: 14px 16px;
        }
        [data-testid="stMetricLabel"] {
            color: #6B7488; font-weight: 600;
            text-transform: uppercase; font-size: .7rem; letter-spacing: .04em;
        }
        [data-testid="stMetricValue"] { color: #0F1B33; font-weight: 700; }

        /* ---------- Misc ---------- */
        .section-title {
            font-size: 1.05rem; font-weight: 700; color: #0F1B33;
            margin: .2rem 0 .15rem;
        }
        .section-desc { font-size: .9rem; color: #6B7488; margin: 0 0 1rem; }
        .chip {
            display:inline-block; background:#EEF2FB; color:#33415C;
            border:1px solid #E0E6F2; border-radius:999px;
            padding:.28rem .7rem; font-size:.8rem; margin:.15rem .3rem .15rem 0;
        }
        .vendor-badge {
            display:inline-block; background:#2F6FED; color:#fff;
            border-radius:8px; padding:.2rem .6rem; font-size:.8rem;
            font-weight:600; letter-spacing:.02em;
        }
        .src-tag {
            display:inline-block; margin-left:.55rem; font-size:.72rem;
            color:#6B7488; letter-spacing:.03em; vertical-align: middle;
        }
        .src-tag .dot { color:#22a06b; font-size:.85rem; }
        .ds-link a {
            display:inline-block; margin-top:.6rem; background:#2F6FED;
            color:#fff !important; text-decoration:none; font-weight:600;
            padding:.5rem 1rem; border-radius:10px; font-size:.88rem;
        }
        .stButton > button {
            border-radius: 999px; border: 1px solid #D6DEEC;
            background: #fff; color: #33415C; font-weight: 600;
            font-size: .82rem; padding: .35rem .9rem;
        }
        .stButton > button:hover {
            border-color: #2F6FED; color: #2F6FED;
        }
        [data-testid="stTextInput"] input {
            height: 3.2rem; font-size: 1.05rem; border-radius: 14px;
            border: 1px solid #D9E0EC; padding-left: 1rem;
            background: #fff;
        }
        [data-testid="stTextInput"] input:focus {
            border-color: #2F6FED;
            box-shadow: 0 0 0 4px rgba(47,111,237,.15);
        }
        [data-testid="stDeployButton"], footer, #MainMenu { display: none; }
        .app-footer {
            margin-top: 2.6rem; text-align: center;
            font-size: .78rem; color: #9AA3B2;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_agent():
    return SpecAgent()


agent = get_agent()
_inject_css()

if "q" not in st.session_state:
    st.session_state.q = ""


def _set_q(value: str):
    st.session_state.q = value


# ---------- Hero ----------
st.markdown(
    '<div class="hero">'
    '<span class="pill">Network Engineering</span>'
    '<h1>Switch Spec Agent</h1>'
    '<p>Instant specifications and firmware guidance for enterprise '
    'network switches — search any model or compare two side by side.</p>'
    '</div>',
    unsafe_allow_html=True,
)

# ---------- Segmented nav ----------
mode = st.radio(
    "Tool",
    ["🔍  Search specifications", "🛠  Firmware advisor"],
    label_visibility="collapsed",
    horizontal=True,
)


def _chips(features, limit=24):
    if not features:
        return
    html = "".join(
        f'<span class="chip">{f}</span>' for f in features[:limit]
    )
    st.markdown(html, unsafe_allow_html=True)


# ---- Meaningful sectioning -------------------------------------------------
# Group schema fields and route the free-form `extra_specs` into the section
# they actually belong to, so the user sees a structured product page instead
# of either 8 em-dash metric cards or a 73-row dump.
_SECTIONS = [
    ("Ports & connectivity",
     ["port_count", "port_speed_max_gbps", "port_config", "uplink_config"],
     ["device interfaces", "data transfer rates", "interfaces",
      "sfp", "qsfp", "copper", "fiber", "10/100", "gigabit"]),
    ("Performance",
     ["switching_capacity_gbps", "forwarding_rate_mpps", "buffer_mb",
      "latency_ns", "mac_table_size"],
     ["switching capacity", "switching bandwidth", "switching fabric",
      "forwarding", "throughput", "mac address table", "mac table",
      "buffer", "ram buffer", "packet filtering", "latency", "jumbo",
      "transmission method", "queue", "store-and-forward"]),
    ("PoE & power",
     ["poe_standard", "poe_budget_w", "power_typical_w", "power_max_w"],
     ["poe ", "poe+", "poe-", "voltage", "current", "wattage",
      "psu", "consumption", "input power", "power supply"]),
    ("Layer & features",
     ["layer", "features", "use_case"],
     ["routing", "vlan", "stp", "spanning tree", "protocols",
      "sdn", "controller", "advanced features"]),
    ("Software & lifecycle",
     ["nos", "status", "family", "sku"],
     ["network os", "operating system", "management", "license",
      "support", "warranty", "eos", "eol"]),
    ("Physical & environment",
     ["rack_units"],
     ["dimensions", "weight", "size", "mounting", "form factor",
      "temperature", "humidity", "airflow", "cooling", "fans",
      "mtbf", "altitude", "operating", "storage", "led", "indicator"]),
    ("Standards & compliance",
     [],
     ["standards", "ieee 802", "802.3", "802.1", "certification",
      "compliance", "emi", "emc", "safety", "fcc", "rohs", " ce ", "vcci"]),
]


def _route_extras(extras: dict) -> tuple[dict, list]:
    """Assign each extra key to the first section that matches it."""
    claimed = {name: [] for name, _, _ in _SECTIONS}
    unclaimed = []
    for k, v in extras.items():
        kl = (k or "").lower()
        for name, _, kws in _SECTIONS:
            if any(kw in kl for kw in kws):
                claimed[name].append((k, v))
                break
        else:
            unclaimed.append((k, v))
    return claimed, unclaimed


def _format_schema_value(k: str, v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else None
    if k == "switching_capacity_gbps" and v:
        try:
            v = float(v)
            return f"{v/1000:.2f} Tbps" if v >= 1000 else f"{v:g} Gbps"
        except (TypeError, ValueError):
            pass
    if k == "forwarding_rate_mpps" and v:
        try:
            return f"{float(v):g} Mpps"
        except (TypeError, ValueError):
            pass
    if k == "buffer_mb" and v:
        try:
            return f"{float(v):g} MB"
        except (TypeError, ValueError):
            pass
    if k == "poe_budget_w" and v:
        return f"{v} W"
    if k == "rack_units" and v:
        return f"{v}U"
    return str(v) if v not in (None, "") else None


def _section_rows(top: dict, schema_keys: list, extra_pairs: list) -> list:
    rows = []
    for k in schema_keys:
        v = top.get(k)
        if v in (None, "", "[]", []):
            continue
        formatted = _format_schema_value(k, v)
        if not formatted:
            continue
        rows.append({"Spec": LABELS.get(k, k.replace("_", " ").title()),
                     "Value": formatted})
    for k, v in extra_pairs:
        rows.append({"Spec": k, "Value": v})
    return rows


def _build_summary(top: dict) -> str:
    parts = []
    pc = top.get("port_count")
    ms = top.get("port_speed_max_gbps")
    if pc:
        parts.append(f"{pc} × {ms}G" if ms else f"{pc}-port")
    if top.get("use_case"):
        parts.append(top["use_case"])
    if not parts:  # nothing to anchor "switch" to — skip the lonely word
        return ""
    parts.append("switch")
    if top.get("layer"):
        parts.append(top["layer"])
    if top.get("poe_standard"):
        p = top["poe_standard"]
        if top.get("poe_budget_w"):
            p = f"{p} {top['poe_budget_w']} W"
        parts.append(p)
    sc = top.get("switching_capacity_gbps")
    if sc:
        try:
            sc = float(sc)
            cap = f"{sc/1000:.1f} Tbps" if sc >= 1000 else f"{sc:g} Gbps"
            parts.append(f"{cap} switching")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)


def _headline_metrics(top: dict) -> list:
    out = []
    if top.get("port_count"):
        out.append(("Ports", str(top["port_count"])))
    sc = top.get("switching_capacity_gbps")
    if sc:
        try:
            sc = float(sc)
            out.append(("Capacity",
                        f"{sc/1000:.1f} Tbps" if sc >= 1000 else f"{sc:g} Gbps"))
        except (TypeError, ValueError):
            pass
    if top.get("poe_standard"):
        v = top["poe_standard"]
        if top.get("poe_budget_w"):
            v = f"{v} · {top['poe_budget_w']} W"
        out.append(("PoE", v))
    if top.get("layer"):
        out.append(("Layer", top["layer"]))
    if len(out) < 4 and top.get("nos"):
        out.append(("Network OS", top["nos"]))
    if len(out) < 4 and top.get("use_case"):
        out.append(("Role", top["use_case"]))
    return out[:4]


def _render_spec_sections(top: dict):
    """Render every populated section as its own panel; route extras into
    them; anything left goes in a collapsed catch-all."""
    extras = top.get("extra_specs") or {}
    if not isinstance(extras, dict):
        extras = {}
    claimed, unclaimed = _route_extras(extras)
    rendered = 0
    for name, schema_keys, _ in _SECTIONS:
        rows = _section_rows(top, schema_keys, claimed[name])
        if not rows:
            continue
        st.markdown(f'<div class="section-title">{name}</div>',
                    unsafe_allow_html=True)
        st.table(rows)
        rendered += 1
    if unclaimed:
        with st.expander(f"Other datasheet details ({len(unclaimed)})"):
            st.table([{"Spec": k, "Value": v} for k, v in unclaimed])
    if rendered == 0 and not unclaimed:
        st.caption("No structured specifications captured for this model "
                   "— see the datasheet link above.")


def _render_spec_detail(top: dict, source: str = ""):
    with st.container(border=True):
        has_img = bool(top.get("image_url"))
        if has_img:
            icol, hcol = st.columns([1, 2.4])
            with icol:
                try:
                    st.image(top["image_url"], width="stretch")
                except Exception:
                    pass
            head = hcol
        else:
            head = st

        tag = ""
        if source == "live":
            tag = ('<span class="src-tag"><span class="dot">●</span> '
                   'live · cached</span>')
        head.markdown(
            f'<span class="vendor-badge">{top.get("vendor","")}</span>{tag}',
            unsafe_allow_html=True,
        )
        head.markdown(f"### {top.get('model','')}")
        # One-line plain-English summary built from real data only.
        summary = _build_summary(top)
        if summary:
            head.caption(summary)

        st.write("")

        # Headline metrics — only the 3-4 most-important populated ones,
        # never a row of em-dashes.
        metrics = _headline_metrics(top)
        if metrics:
            cols = st.columns(len(metrics))
            for col, (label, value) in zip(cols, metrics):
                col.metric(label, value)

        if top.get("features"):
            st.markdown('<div class="section-title">Features</div>',
                        unsafe_allow_html=True)
            _chips(top["features"])

        if top.get("datasheet_url"):
            st.markdown(
                f'<div class="ds-link"><a href="{top["datasheet_url"]}" '
                f'target="_blank">View datasheet ↗</a></div>',
                unsafe_allow_html=True,
            )

        # Sectioned rendering — each panel shown only if it has content.
        # Free-form datasheet extras are routed into the section they
        # belong to; the rest go in a collapsed "Other details".
        _render_spec_sections(top)


# ============================================================
#  SEARCH SPECIFICATIONS
# ============================================================
if mode.endswith("Search specifications"):
    st.text_input(
        "Search",
        key="q",
        label_visibility="collapsed",
        placeholder="Search a switch model · or compare A vs B",
    )
    q = st.session_state.q.strip()

    if not q:
        st.write("")
        st.caption("Try one of these:")
        ex = ["Cisco Catalyst 9300-48P", "Juniper EX4400-48P",
              "Arista 7060CX-32S", "compare C9300-48P vs EX4400-48P"]
        cols = st.columns(len(ex))
        for col, e in zip(cols, ex):
            col.button(e, on_click=_set_q, args=(e,),
                       use_container_width=True)
    else:
        t0 = time.time()
        resp = agent.answer(q)
        elapsed_ms = (time.time() - t0) * 1000

        if resp["type"] == "spec":
            _render_spec_detail(resp["result"], source=resp.get("source", ""))
            if resp.get("alternates"):
                with st.expander(
                        f"Other matches ({len(resp['alternates'])})"):
                    for a in resp["alternates"]:
                        st.write(f"- **{a['vendor']}** {a['model']}")
            st.caption(f"Answered in {elapsed_ms:.0f} ms")

        elif resp["type"] == "compare":
            recs = resp["results"]
            fields = [k for k in LABELS
                      if k not in ("datasheet_url", "image_url")]
            with st.container(border=True):
                cols = st.columns(len(recs))
                for col, r in zip(cols, recs):
                    col.markdown(
                        f'<span class="vendor-badge">{r.get("vendor","")}'
                        f'</span>', unsafe_allow_html=True)
                    col.markdown(f"#### {r.get('model','')}")
                table = []
                for k in fields:
                    row = {"Spec": LABELS[k]}
                    for r in recs:
                        v = r.get(k)
                        row[f"{r['vendor']} {r['model']}"] = (
                            ", ".join(v) if isinstance(v, list)
                            else (v if v not in (None, "") else "—"))
                    table.append(row)
                st.dataframe(table, width="stretch", hide_index=True)
            st.caption(f"Answered in {elapsed_ms:.0f} ms")

        else:
            st.caption("Try a specific model — e.g. *Cisco Catalyst 9300-48P*.")

# ============================================================
#  FIRMWARE ADVISOR
# ============================================================
else:
    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        with c1:
            fw_model = st.text_input(
                "Switch model",
                placeholder="e.g. MikroTik CRS326-24G-2S+RM")
        with c2:
            fw_version = st.text_input(
                "Current firmware version", placeholder="e.g. 7.10.2")

    if fw_model and fw_version:
        advice = agent.firmware_advise(fw_model, fw_version)

        if not advice.has_data:
            st.info(advice.message)
            if advice.portal_url:
                st.markdown(
                    f'<div class="ds-link"><a href="{advice.portal_url}" '
                    f'target="_blank">Vendor portal ↗</a></div>',
                    unsafe_allow_html=True)
        elif not advice.diff:
            st.success(advice.message)
        else:
            d = advice.diff
            cur, tgt = d.current, d.target
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Your version", cur.version)
                    if cur.release_date:
                        st.caption(f"Released {cur.release_date}")
                with c2:
                    st.metric("Latest", tgt.version)
                    if tgt.release_date:
                        st.caption(f"Released {tgt.release_date}")
                with c3:
                    st.metric("Releases behind", d.releases_behind)

                if d.security_fixes:
                    st.markdown(
                        '<div class="section-title">🔒 Security fixes '
                        f'({len(d.security_fixes)})</div>',
                        unsafe_allow_html=True)
                    for fix in d.security_fixes[:20]:
                        st.write(f"- {fix}")
                if d.new_features:
                    st.markdown(
                        '<div class="section-title">✨ New features '
                        f'({len(d.new_features)})</div>',
                        unsafe_allow_html=True)
                    for feat in d.new_features[:20]:
                        st.write(f"- {feat}")
                if d.bug_fixes:
                    with st.expander(f"Bug fixes ({len(d.bug_fixes)})"):
                        for fix in d.bug_fixes[:50]:
                            st.write(f"- {fix}")
                if d.deprecations:
                    st.markdown(
                        '<div class="section-title">⚠️ Removed / '
                        'deprecated</div>', unsafe_allow_html=True)
                    for dep in d.deprecations:
                        st.write(f"- {dep}")
                if tgt.release_notes_url:
                    st.markdown(
                        f'<div class="ds-link"><a '
                        f'href="{tgt.release_notes_url}" target="_blank">'
                        f'Full release notes ↗</a></div>',
                        unsafe_allow_html=True)

# ---------- Footer ----------
st.markdown(
    '<div class="app-footer">Network Switch Spec Agent · '
    'For planning reference only</div>',
    unsafe_allow_html=True,
)

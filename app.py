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


def _render_spec_detail(top: dict):
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

        head.markdown(
            f'<span class="vendor-badge">{top.get("vendor","")}</span>',
            unsafe_allow_html=True,
        )
        head.markdown(f"### {top.get('model','')}")
        if top.get("use_case"):
            head.caption(f"Typical use · {top['use_case']}")

        st.write("")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ports", top.get("port_count") or "—")
        c2.metric("Max speed",
                  f"{top.get('port_speed_max_gbps')} G"
                  if top.get("port_speed_max_gbps") else "—")
        sc = top.get("switching_capacity_gbps")
        c3.metric("Capacity", f"{sc:g} G" if sc else "—")
        c4.metric("PoE", top.get("poe_standard") or "None")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Layer", top.get("layer") or "—")
        c6.metric("Rack U", top.get("rack_units") or "—")
        fr = top.get("forwarding_rate_mpps")
        c7.metric("Fwd rate", f"{fr:g} M" if fr else "—")
        c8.metric("Network OS", top.get("nos") or "—")

        if top.get("port_config"):
            st.write(f"**Port configuration** · {top['port_config']}")
        if top.get("uplink_config"):
            st.write(f"**Uplinks** · {top['uplink_config']}")
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
        with st.expander("Full specification"):
            rows = [
                {"Spec": lbl,
                 "Value": (", ".join(top[k]) if isinstance(top.get(k), list)
                           else top.get(k))}
                for k, lbl in LABELS.items()
                if k != "image_url" and top.get(k) not in (None, "")
            ]
            st.table(rows)


# ============================================================
#  SEARCH SPECIFICATIONS
# ============================================================
if mode.endswith("Search specifications"):
    st.markdown('<div class="section-title">Search specifications</div>'
                '<div class="section-desc">Type a switch model, or '
                '“compare A vs B”. Not in our records? We fetch it live.</div>',
                unsafe_allow_html=True)

    st.text_input(
        "Search",
        key="q",
        label_visibility="collapsed",
        placeholder="e.g.  Cisco Catalyst 9300-48P   ·   "
        "compare C9300-48P vs EX4400-48P",
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
            st.success(resp["message"])
            _render_spec_detail(resp["result"])
            if resp.get("alternates"):
                with st.expander(
                        f"Other matches ({len(resp['alternates'])})"):
                    for a in resp["alternates"]:
                        st.write(f"- **{a['vendor']}** {a['model']}")
            st.caption(f"Answered in {elapsed_ms:.0f} ms")

        elif resp["type"] == "compare":
            st.success(resp["message"])
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
            # Filter / vendor / not-found: never expose the catalog.
            st.info(
                "Enter a specific switch model (e.g. *Cisco Catalyst "
                "9300-48P*) or compare two models with "
                "*compare A vs B*."
            )

# ============================================================
#  FIRMWARE ADVISOR
# ============================================================
else:
    st.markdown('<div class="section-title">Firmware advisor</div>'
                '<div class="section-desc">See what changed since your '
                'current firmware — security fixes, features and '
                'deprecations.</div>',
                unsafe_allow_html=True)

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

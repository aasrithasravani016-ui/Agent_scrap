"""
Streamlit web UI for the switch spec agent.

Run:
    streamlit run app.py
"""
import time

import streamlit as st

from agent import SpecAgent, LABELS

st.set_page_config(page_title="Switch Spec Agent", page_icon="🔌", layout="wide")


@st.cache_resource
def get_agent():
    return SpecAgent()


agent = get_agent()

st.title("🔌 Network Switch Spec Agent")
st.caption("Ask about any switch from the 10 supported vendors.")

mode = st.radio(
    "Mode",
    ["Ask", "Search", "Filter", "Compare", "Browse by vendor",
     "Firmware advisor"],
    horizontal=True,
)


def _show_switch_image(rec):
    """Render the product image if we have one (broken links are silently
    skipped)."""
    if rec.get("image_url"):
        try:
            st.image(rec["image_url"], width="stretch")
            return True
        except Exception:
            pass
    return False

# ---------- Ask (natural language router) ----------
if mode == "Ask":
    q = st.text_input(
        "Ask anything",
        placeholder="'Cisco C9300-48P' · 'compare C9300-48P vs EX4400-48P' · "
        "'which switches support 400G' · 'switches with PoE over 600W'",
    )
    if q:
        t0 = time.time()
        resp = agent.answer(q)
        elapsed_ms = (time.time() - t0) * 1000
        st.caption(f"Answered in {elapsed_ms:.0f} ms")

        if resp["type"] == "spec":
            st.success(resp["message"])
            top = resp["result"]
            with st.container(border=True):
                if top.get("image_url"):
                    icol, hcol = st.columns([1, 3])
                    with icol:
                        _show_switch_image(top)
                    with hcol:
                        st.subheader(f"{top['vendor']} {top['model']}")
                else:
                    st.subheader(f"{top['vendor']} {top['model']}")
                rows = [
                    {"Spec": lbl,
                     "Value": (", ".join(top[k]) if isinstance(top.get(k), list)
                               else top.get(k))}
                    for k, lbl in LABELS.items()
                    if top.get(k) not in (None, "")
                ]
                st.table(rows)
                if top.get("datasheet_url"):
                    st.markdown(f"[Datasheet]({top['datasheet_url']})")
            if resp.get("alternates"):
                with st.expander("Other candidates"):
                    for a in resp["alternates"]:
                        st.write(f"- **{a['vendor']}** {a['model']}")
        elif resp["type"] == "compare":
            st.success(resp["message"])
            recs = resp["results"]
            fields = [k for k in LABELS if k != "datasheet_url"]
            table = []
            for k in fields:
                row = {"": LABELS[k]}
                for r in recs:
                    v = r.get(k)
                    row[f"{r['vendor']} {r['model']}"] = (
                        ", ".join(v) if isinstance(v, list)
                        else (v if v not in (None, "") else "—")
                    )
                table.append(row)
            st.dataframe(table, width="stretch", hide_index=True)
        elif resp["type"] == "filter":
            st.success(f"{resp['message']} — {len(resp['results'])} match")
            st.dataframe(
                [
                    {
                        "Vendor": r["vendor"], "Model": r["model"],
                        "Port config": r.get("port_config"),
                        "Capacity Gbps": r.get("switching_capacity_gbps"),
                        "PoE (W)": r.get("poe_budget_w"),
                        "NOS": r.get("nos"), "Use case": r.get("use_case"),
                    }
                    for r in resp["results"]
                ],
                width="stretch", hide_index=True,
            )
        elif resp["type"] == "vendors":
            st.success(resp["message"])
            st.dataframe(
                [{"Vendor": v, "Models": c} for v, c in resp["vendors"]],
                width="stretch", hide_index=True,
            )
        else:  # notfound / empty
            st.warning(resp["message"])
            if resp.get("suggestions"):
                st.write("**Known models include:**")
                st.write(resp["suggestions"])

# ---------- Search ----------
if mode == "Search":
    q = st.text_input(
        "Query",
        placeholder="e.g. 'Cisco Catalyst 9300-48P' or 'arista 7050' or 'C9300-48P'",
    )
    if q:
        t0 = time.time()
        results = agent.lookup(q, limit=10)
        elapsed_ms = (time.time() - t0) * 1000

        if not results:
            st.warning("No matches.")
        else:
            st.caption(f"Found {len(results)} result(s) in {elapsed_ms:.0f} ms")
            top = results[0]
            with st.container(border=True):
                if top.get("image_url"):
                    icol, hcol = st.columns([1, 3])
                    with icol:
                        _show_switch_image(top)
                    with hcol:
                        st.subheader(f"{top['vendor']} {top['model']}")
                else:
                    st.subheader(f"{top['vendor']} {top['model']}")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Ports", top.get("port_count") or "—")
                    st.metric("Max speed", f"{top.get('port_speed_max_gbps', '—')} Gbps")
                    st.metric("Layer", top.get("layer") or "—")
                with c2:
                    sc = top.get("switching_capacity_gbps")
                    st.metric(
                        "Switching capacity",
                        f"{sc:g} Gbps" if sc else "—",
                    )
                    fr = top.get("forwarding_rate_mpps")
                    st.metric("Forwarding rate", f"{fr:g} Mpps" if fr else "—")
                    st.metric("PoE", top.get("poe_standard") or "None")
                with c3:
                    st.metric("Rack units", top.get("rack_units") or "—")
                    st.metric("NOS", top.get("nos") or "—")
                    st.metric("Use case", top.get("use_case") or "—")

                st.write(f"**Port config:** {top.get('port_config', '—')}")
                if top.get("uplink_config"):
                    st.write(f"**Uplinks:** {top['uplink_config']}")
                features = top.get("features") or []
                if features:
                    st.write("**Features:** " + ", ".join(features))
                if top.get("datasheet_url"):
                    st.markdown(f"[Datasheet]({top['datasheet_url']})")

            if len(results) > 1:
                with st.expander(f"Other candidates ({len(results) - 1})"):
                    for r in results[1:]:
                        st.write(f"- **{r['vendor']}** {r['model']} — {r.get('port_config', '')}")

# ---------- Filter ----------
elif mode == "Filter":
    c1, c2, c3 = st.columns(3)
    vendors = [v for v, _ in agent.list_vendors()]
    with c1:
        vendor = st.selectbox("Vendor", ["Any"] + vendors)
        use_case = st.selectbox(
            "Use case", ["Any", "access", "aggregation", "leaf", "spine", "core"]
        )
    with c2:
        min_speed = st.select_slider(
            "Min port speed (Gbps)", options=[1, 10, 25, 40, 100, 200, 400, 800], value=1
        )
        layer = st.selectbox("Layer", ["Any", "L2", "L2+", "L3"])
    with c3:
        min_ports = st.number_input("Min ports", min_value=0, value=0)
        poe = st.checkbox("Requires PoE")

    feature = st.text_input("Required feature (substring, e.g. 'EVPN-VXLAN')")

    results = agent.filter(
        vendor=None if vendor == "Any" else vendor,
        min_port_speed=min_speed if min_speed > 1 else None,
        min_ports=min_ports if min_ports > 0 else None,
        poe=True if poe else None,
        layer=None if layer == "Any" else layer,
        use_case=None if use_case == "Any" else use_case,
        feature=feature or None,
    )
    st.caption(f"{len(results)} matches")
    if results:
        table = [
            {
                "Vendor": r["vendor"],
                "Model": r["model"],
                "Ports": r.get("port_count"),
                "Max Gbps": r.get("port_speed_max_gbps"),
                "Capacity Gbps": r.get("switching_capacity_gbps"),
                "PoE": r.get("poe_standard") or "—",
                "Layer": r.get("layer") or "—",
                "NOS": r.get("nos") or "—",
            }
            for r in results
        ]
        st.dataframe(table, width="stretch", hide_index=True)

# ---------- Compare ----------
elif mode == "Compare":
    c1, c2 = st.columns(2)
    with c1:
        q1 = st.text_input("Switch A", placeholder="e.g. C9300-48P")
    with c2:
        q2 = st.text_input("Switch B", placeholder="e.g. EX4400-48P")

    if q1 and q2:
        result = agent.compare(q1, q2)
        a, b = result["a"], result["b"]

        if not a or not b:
            if not a:
                st.warning(f"No match for: {q1}")
            if not b:
                st.warning(f"No match for: {q2}")
        else:
            fields = [
                ("Vendor", "vendor"),
                ("Family", "family"),
                ("Model", "model"),
                ("Ports", "port_count"),
                ("Port config", "port_config"),
                ("Max speed (Gbps)", "port_speed_max_gbps"),
                ("Switching capacity (Gbps)", "switching_capacity_gbps"),
                ("Forwarding rate (Mpps)", "forwarding_rate_mpps"),
                ("Buffer (MB)", "buffer_mb"),
                ("Latency (ns)", "latency_ns"),
                ("PoE", "poe_standard"),
                ("PoE budget (W)", "poe_budget_w"),
                ("Layer", "layer"),
                ("Rack units", "rack_units"),
                ("NOS", "nos"),
                ("Use case", "use_case"),
            ]
            table = []
            for label, key in fields:
                row = {
                    "": label,
                    f"{a['vendor']} {a['model']}": a.get(key) or "—",
                    f"{b['vendor']} {b['model']}": b.get(key) or "—",
                }
                table.append(row)
            st.dataframe(table, width="stretch", hide_index=True)

            c1, c2 = st.columns(2)
            with c1:
                st.write("**Features**")
                st.write(", ".join(a.get("features") or []) or "—")
            with c2:
                st.write("**Features**")
                st.write(", ".join(b.get("features") or []) or "—")

# ---------- Browse ----------
elif mode == "Browse by vendor":
    vendors = [v for v, _ in agent.list_vendors()]
    vendor = st.selectbox("Vendor", vendors)
    models = agent.list_models(vendor)
    st.caption(f"{len(models)} models")
    table = [
        {
            "Family": m.get("family") or "—",
            "Model": m["model"],
            "Ports": m.get("port_count"),
            "Port config": m.get("port_config"),
            "Capacity Gbps": m.get("switching_capacity_gbps"),
            "PoE": m.get("poe_standard") or "—",
            "Use case": m.get("use_case") or "—",
        }
        for m in models
    ]
    st.dataframe(table, width="stretch", hide_index=True)

# ---------- Firmware advisor ----------
elif mode == "Firmware advisor":
    st.write(
        "Enter your switch model and the firmware version you're currently "
        "running. We'll show what changed in newer releases (where the data "
        "is publicly available)."
    )
    c1, c2 = st.columns([2, 1])
    with c1:
        fw_model = st.text_input(
            "Switch model", placeholder="e.g. MikroTik CRS326-24G-2S+RM")
    with c2:
        fw_version = st.text_input(
            "Current firmware version", placeholder="e.g. 7.10.2")

    if fw_model and fw_version:
        advice = agent.firmware_advise(fw_model, fw_version)

        if not advice.has_data:
            st.info(advice.message)
            if advice.portal_url:
                st.markdown(f"[Vendor portal]({advice.portal_url})")
        elif not advice.diff:
            st.success(advice.message)
        else:
            d = advice.diff
            cur, tgt = d.current, d.target
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
                st.subheader(f"Security fixes ({len(d.security_fixes)})")
                for fix in d.security_fixes[:20]:
                    st.write(f"- {fix}")
            if d.new_features:
                st.subheader(f"New features ({len(d.new_features)})")
                for feat in d.new_features[:20]:
                    st.write(f"- {feat}")
            if d.bug_fixes:
                with st.expander(f"Bug fixes ({len(d.bug_fixes)})"):
                    for fix in d.bug_fixes[:50]:
                        st.write(f"- {fix}")
            if d.deprecations:
                st.subheader("Removed / deprecated")
                for dep in d.deprecations:
                    st.write(f"- {dep}")
            if tgt.release_notes_url:
                st.markdown(f"[Full release notes]({tgt.release_notes_url})")

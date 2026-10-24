"""Simple SMART scholarship export box for Finals Closeout."""

import pandas as pd
import streamlit as st

from modules.divisions import get_divisions
from modules.smart_export import (COLUMNS, build_smart_export, header_csv, recipients_csv,
                                  save_header_fields, save_place_amounts)
from modules.standings import get_tournament


def render_smart_export_box(t_id: int) -> None:
    st.markdown("##### 🎓 SMART Scholarship Upload")
    t = get_tournament(t_id) or {}

    c1, c2 = st.columns(2)
    end = c1.text_input("Date event ended", value=t.get("event_end_date") or (t.get("event_start") or "")[:10],
                        key=f"smart_end_{t_id}", help="YYYY-MM-DD")
    cert = c2.text_input("Tournament cert #", value=t.get("cert_number") or "", key=f"smart_cert_{t_id}")
    if end != (t.get("event_end_date") or "") or cert != (t.get("cert_number") or ""):
        if c1.button("Save date and cert #", key=f"smart_save_{t_id}"):
            save_header_fields(t_id, end, cert)
            st.rerun()

    divs = get_divisions(t)
    if divs:
        with st.expander("Scholarship amounts by place"):
            st.caption("1st place comes from the flyer. Type amounts for the other places when the committee decides. "
                       "Leave a place blank if it has no amount yet.")
            for d in divs:
                cur = list(d.get("place_amounts") or [d.get("first_place")])
                txt = st.text_input(f"{d['name']} (1st, 2nd, 3rd, ...)", value=", ".join("" if v in (None, "") else f"{float(v):g}" for v in cur),
                                    key=f"smart_amt_{t_id}_{d['name']}")
                if st.button(f"Save {d['name']} amounts", key=f"smart_amt_save_{t_id}_{d['name']}"):
                    vals = []
                    for part in txt.split(","):
                        part = part.strip().lstrip("$")
                        try:
                            vals.append(float(part) if part else None)
                        except ValueError:
                            vals.append(None)
                    save_place_amounts(t_id, d["name"], vals)
                    st.rerun()

    data = build_smart_export(t_id)
    h = data["header"]
    st.markdown(f"**SMART portal header** — Event: {h['Event Name']} · Total: ${float(h['Total Amount']):,.2f} · "
                f"Ended: {h['Date Event Ended'] or '—'} · Center: {h['Center Name']} · Cert #: {h['Tournament Cert #'] or '—'}")
    if data["rows"]:
        st.dataframe(pd.DataFrame(data["rows"])[COLUMNS], hide_index=True, use_container_width=True)
    for w in data["warnings"]:
        st.warning(w)
    st.caption("For the SMART upload, keep USBC ID, Last Name, First Name and Scholarship Amount. "
               "Division/Group and Place are for your review — check the '?' screen in the SMART portal for its exact columns.")
    d1, d2 = st.columns(2)
    d1.download_button("📥 Recipients CSV", recipients_csv(data), file_name=f"smart_recipients_{t_id}.csv",
                       mime="text/csv", use_container_width=True)
    d2.download_button("📥 Header CSV", header_csv(data), file_name=f"smart_header_{t_id}.csv",
                       mime="text/csv", use_container_width=True)

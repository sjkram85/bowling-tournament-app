# --- CONCOURSE CHECK-IN & FLOOR ACCESS STATION ---
    st.markdown("---")
    st.markdown("### 📲 Concourse Check-In & Floor Scorer Access Station")
    st.caption("Display or share these QR codes with bowlers upon arrival and floor score assistants prior to launching the squad.")

    qr_col1, qr_col2 = st.columns(2)

    bowler_checkin_url = "https://chusbc-desk.streamlit.app/?mode=bowler"
    scorer_url = "https://chusbc-desk.streamlit.app/?mode=score"

    with qr_col1:
        st.markdown(
            """
            <div style="background:#1E293B; border:1px solid #10B981; border-radius:10px; padding:12px; text-align:center;">
                <span style="background:#064E3B; color:#6EE7B7; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                    BOWLER ARRIVAL GATE
                </span>
                <h4 style="color:#F8FAFC; margin:6px 0 4px 0;">🎳 Bowler Self Check-In</h4>
                <p style="color:#94A3B8; font-size:12px; margin-bottom:8px;">Scan to confirm arrival, verify payment & get lane assignment</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        buf_b = _generate_qr_buffer(bowler_checkin_url)
        st.image(buf_b.getvalue(), caption="Scan to Check In & Reveal Starting Lane", width=220)
        st.markdown(f"[🔗 Open Bowler Check-In Directly]({bowler_checkin_url})")

    with qr_col2:
        st.markdown(
            f"""
            <div style="background:#1E293B; border:1px solid #334155; border-radius:10px; padding:12px; text-align:center;">
                <span style="background:#1E3A8A; color:#93C5FD; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                    STAFF / FLOOR ONLY
                </span>
                <h4 style="color:#F8FAFC; margin:6px 0 4px 0;">Floor Verifier Portal</h4>
                <p style="color:#10B981; font-weight:700; font-size:13px; margin-bottom:8px;">🔑 Active PIN: {pin}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        buf_s = _generate_qr_buffer(scorer_url)
        st.image(buf_s.getvalue(), caption="Floor Assistant 10-Key Pad QR", width=220)
        st.markdown(f"[🔗 Open Mobile Scorer Directly]({scorer_url})")

    with st.expander("🖨️ Concourse Display / Printable Placard Mode", expanded=False):
        st.markdown(
            f"""
            <div style="background:#0F172A; border:2px dashed #475569; border-radius:12px; padding:20px; text-align:center;">
                <h2 style="color:#F8FAFC; margin-bottom:4px;">CECIL HARFORD USBC TOURNAMENT ACCESS</h2>
                <p style="color:#94A3B8; font-size:14px; margin-bottom:16px;">Scan either code below using your smartphone camera</p>
                <div style="display:flex; justify-content:space-around; align-items:center; flex-wrap:wrap; gap:20px;">
                    <div>
                        <h4 style="color:#34D399;">1. BOWLER SELF CHECK-IN</h4>
                        <p style="color:#CBD5E1; font-size:12px;">Confirm Entry, Verify Paid Status & Get Starting Lane</p>
                    </div>
                    <div>
                        <h4 style="color:#38BDF8;">2. FLOOR SCORING PAD</h4>
                        <p style="color:#CBD5E1; font-size:12px;">Authorized Verifiers Only (PIN: <strong>{pin}</strong>)</p>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
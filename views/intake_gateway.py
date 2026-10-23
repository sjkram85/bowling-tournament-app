# --- UNIFIED 3-PORTAL CONCOURSE ACCESS STATION ---
    st.markdown("---")
    st.markdown("### 📱 Concourse Check-In, Live Portal & Floor Scoring Station")
    st.caption("Display or share these direct portals with bowlers and floor score verifiers prior to launching the squad.")

    base = _get_base_url()
    checkin_url = f"{base}/?mode=bowler&action=checkin"
    portal_url = f"{base}/?mode=bowler"
    scorer_url = f"{base}/?mode=score"

    buf_checkin = _generate_qr_buffer(checkin_url)
    buf_portal = _generate_qr_buffer(portal_url)
    buf_scorer = _generate_qr_buffer(scorer_url)

    col1, col2, col3 = st.columns(3, gap="medium")

    with col1:
        with st.container(border=True):
            st.markdown(
                """
                <div style="text-align:center; min-height:85px;">
                    <span style="background:#064E3B; color:#6EE7B7; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                        ARRIVAL GATE
                    </span>
                    <h4 style="color:#F8FAFC; margin:6px 0 2px 0;">🎳 Bowler Check-In</h4>
                    <p style="color:#94A3B8; font-size:12px; margin-bottom:0;">Verify paid status & unlock lane</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Centered 190px QR code
            c_l, c_mid, c_r = st.columns([1, 4, 1])
            with c_mid:
                st.image(buf_checkin.getvalue(), width=190)
            st.markdown(
                f"<div style='text-align:center; margin-top:4px;'><a href='{checkin_url}' target='_blank' style='font-size:13px;'>🔗 Open Check-In</a></div>",
                unsafe_allow_html=True,
            )

    with col2:
        with st.container(border=True):
            st.markdown(
                """
                <div style="text-align:center; min-height:85px;">
                    <span style="background:#0284C7; color:#BAE6FD; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                        LIVE TRACKER
                    </span>
                    <h4 style="color:#F8FAFC; margin:6px 0 2px 0;">📊 Bowler Portal</h4>
                    <p style="color:#94A3B8; font-size:12px; margin-bottom:0;">Live standings, cut line & brackets</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c_l, c_mid, c_r = st.columns([1, 4, 1])
            with c_mid:
                st.image(buf_portal.getvalue(), width=190)
            st.markdown(
                f"<div style='text-align:center; margin-top:4px;'><a href='{portal_url}' target='_blank' style='font-size:13px;'>🔗 Open Bowler Portal</a></div>",
                unsafe_allow_html=True,
            )

    with col3:
        with st.container(border=True):
            st.markdown(
                f"""
                <div style="text-align:center; min-height:85px;">
                    <span style="background:#1E3A8A; color:#93C5FD; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;">
                        STAFF / VERIFIERS
                    </span>
                    <h4 style="color:#F8FAFC; margin:6px 0 2px 0;">📱 Floor Scoring</h4>
                    <p style="color:#10B981; font-weight:700; font-size:12px; margin-bottom:0;">🔑 Active PIN: {pin}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c_l, c_mid, c_r = st.columns([1, 4, 1])
            with c_mid:
                st.image(buf_scorer.getvalue(), width=190)
            st.markdown(
                f"<div style='text-align:center; margin-top:4px;'><a href='{scorer_url}' target='_blank' style='font-size:13px;'>🔗 Open Scorer Pad</a></div>",
                unsafe_allow_html=True,
            )
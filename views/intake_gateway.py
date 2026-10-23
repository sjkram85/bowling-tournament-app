def _run_with_bowling_animation(task_func, *args):
    """
    Executes an AI task in the background while rendering a live bowling ball
    animation and an advancing percentage progress bar (1-100%).
    """
    anim_box = st.empty()
    progress_bar = st.progress(0)

    stages = [
        (10, "🎳 ... Setting lane conditions & initializing Gemini ..."),
        (28, "🎳 ... Bowling ball on the approach ... reading roster ..."),
        (46, "🎳 ... Mid-lane roll ... identifying bowler names & USBC IDs ..."),
        (68, "🎳 ... Hitting the hook phase ... calculating averages & handicaps ..."),
        (88, "🎳 ... Entering the pocket ... structuring Rule 400 SMART tags ..."),
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(task_func, *args)
        current_pct = 1

        # Smooth roll up to 92%
        while not future.done():
            if current_pct < 92:
                increment = 3 if current_pct < 40 else (2 if current_pct < 75 else 1)
                current_pct = min(92, current_pct + increment)

            stage_text = stages[0][1]
            for threshold, desc in stages:
                if current_pct >= threshold:
                    stage_text = desc

            pins_gap = max(0, 30 - int(current_pct * 0.3))
            ball_trail = "=" * int(current_pct * 0.3)
            track_graphic = f"`|{ball_trail}🎳{' ' * pins_gap}🎳🎳🎳🎳|`"

            anim_box.markdown(
                f"""
                <div style="background:#0F172A; border:1px solid #1E293B; border-radius:8px; padding:12px 16px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span style="color:#38BDF8; font-weight:600; font-size:13px;">{stage_text}</span>
                        <span style="color:#F8FAFC; font-family:monospace; font-weight:700; font-size:14px;">{current_pct}%</span>
                    </div>
                    <div style="font-size:12px; margin-top:2px;">{track_graphic}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            progress_bar.progress(current_pct)
            time.sleep(0.12)

        try:
            # 30-second timeout guard to prevent infinite hanging
            result = future.result(timeout=30)
        except Exception as exc:
            anim_box.empty()
            progress_bar.empty()
            raise RuntimeError(f"Gemini API request failed: {exc}")

        # Strike confirmation
        anim_box.markdown(
            """
            <div style="background:#064E3B; border:1px solid #059669; border-radius:8px; padding:12px 16px; margin-bottom:8px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="color:#6EE7B7; font-weight:700; font-size:14px;">💥 STRIKE! 10 in the Pit — Roster extracted cleanly.</span>
                    <span style="color:#F8FAFC; font-family:monospace; font-weight:700; font-size:14px;">100%</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        progress_bar.progress(100)
        time.sleep(0.5)

        anim_box.empty()
        progress_bar.empty()
        return result
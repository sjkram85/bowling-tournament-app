# 3. Main Standings Table with Game-by-Game Columns
    story.append(Paragraph("OFFICIAL QUALIFYING & FINAL STANDINGS", sec_heading))

    headers = [
        Paragraph("<b>Rank</b>", th_style),
        Paragraph("<b>Bowler Name</b>", th_style),
        Paragraph("<b>USBC ID</b>", th_style),
        Paragraph("<b>Avg / HDCP</b>", th_style),
    ]
    for g in range(1, game_count + 1):
        headers.append(Paragraph(f"<b>Gm {g}</b>", th_style))
    headers.extend([
        Paragraph("<b>Scratch</b>", th_style),
        Paragraph("<b>HDCP Total</b>", th_style),
        Paragraph("<b>Award</b>", th_style),
        Paragraph("<b>Payout Type</b>", th_style),
    ])

    table_data = [headers]
    honor_scores = []

    for idx, b in enumerate(bowler_records, start=1):
        b_id = b["id"]
        g_scores = scores_by_bowler.get(b_id, {})
        prize = prize_template[idx - 1] if idx <= len(prize_template) else 0.0
        is_y = bool(b["is_youth"])

        if is_y and prize > 0:
            routing_txt = "SMART"
        elif prize > 0:
            routing_txt = "Cash"
        else:
            routing_txt = "—"

        hdcp_val = b["handicap"] or 0
        avg_hdcp_str = f"{b['entering_avg'] or '—'} / +{hdcp_val}" if hdcp_val > 0 else f"{b['entering_avg'] or '—'} (Scratch)"

        row_cells = [
            Paragraph(f"<b>#{idx}</b>", td_center),
            Paragraph(f"<b>{escape(b['name'])}</b>" + (" <i>(Youth)</i>" if is_y else ""), td_style),
            Paragraph(escape(str(b["usbc_id"] or "—")), td_center),
            Paragraph(avg_hdcp_str, td_center),
        ]

        for g in range(1, game_count + 1):
            score_val = g_scores.get(g, 0)
            if score_val == 300:
                honor_scores.append(f"<b>{b['name']}</b> bowled an official <b>300 Game</b> in Game {g}!")
                row_cells.append(Paragraph(f"<font color='#065F46'><b>{score_val}</b></font>", td_center))
            else:
                row_cells.append(Paragraph(str(score_val) if score_val > 0 else "—", td_center))

        row_cells.extend([
            Paragraph(f"<b>{b['total_scratch']}</b>", td_right),
            Paragraph(f"<b>{b['grand_total']}</b>", td_bold_right),
            Paragraph(f"${prize:.2f}" if prize > 0 else "—", td_right),
            Paragraph(routing_txt, td_center),
        ])
        table_data.append(row_cells)

    # 540 pt usable width: [36, 104, 44, 58] + [32, 32, 32] + [46, 54, 50, 52] = 540 pt
    col_widths = [36, 104, 44, 58] + [32] * game_count + [46, 54, 50, 52]
    diff = 540 - sum(col_widths)
    if diff != 0:
        col_widths[1] += diff

    standings_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    standings_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(standings_table)
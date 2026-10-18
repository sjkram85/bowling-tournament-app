import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

def create_sop_docx():
    doc = Document()

    # 1. Page Margins (Standard 1 inch all around)
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # 2. Association Color Palette
    PRIMARY = RGBColor(14, 58, 138)     # Deep Navy (#0E3A8A)
    SECONDARY = RGBColor(2, 132, 199)   # Sky Blue (#0284C7)
    TEXT_DARK = RGBColor(15, 23, 42)    # Slate 900 (#0F172A)
    MUTED = RGBColor(100, 116, 139)     # Slate 500 (#64748B)

    # Base Text Style
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(11)
    style_normal.font.color.rgb = TEXT_DARK
    style_normal.paragraph_format.line_spacing = 1.15
    style_normal.paragraph_format.space_after = Pt(6)

    def set_cell_background(cell, hex_color):
        tcPr = cell._tc.get_or_add_tcPr()
        tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>'))

    def set_cell_padding(cell, top=100, bottom=100, left=140, right=140):
        tcPr = cell._tc.get_or_add_tcPr()
        tcPr.append(parse_xml(
            f'<w:tcMar {nsdecls("w")}>'
            f'<w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/>'
            f'<w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/>'
            f'</w:tcMar>'
        ))

    # --- TITLE / HEADER BLOCK ---
    p_org = doc.add_paragraph()
    p_org.paragraph_format.space_after = Pt(2)
    r_org = p_org.add_run("CECIL HARFORD UNITED STATES BOWLING CONGRESS")
    r_org.font.size = Pt(11)
    r_org.font.bold = True
    r_org.font.color.rgb = SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_after = Pt(4)
    r_title = p_title.add_run("Standard Operating Procedure: Tournament Desk Operations Console")
    r_title.font.size = Pt(20)
    r_title.font.bold = True
    r_title.font.color.rgb = PRIMARY

    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(14)
    r_meta = p_meta.add_run(
        "Document Identifier: SOP-TD-2026-01 | Target Audience: Board of Directors & Tournament Assistants\n"
        "Effective Date: October 2026 | Console URL: https://chusbc-desk.streamlit.app"
    )
    r_meta.font.size = Pt(9.5)
    r_meta.font.color.rgb = MUTED

    # Header Accent Divider
    t_div = doc.add_table(rows=1, cols=1)
    t_div.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_div = t_div.cell(0, 0)
    c_div.width = Inches(6.5)
    set_cell_background(c_div, "0E3A8A")
    c_div.height = Pt(3)

    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_after = Pt(10)

    # --- SECTION 1 ---
    h1 = doc.add_heading(level=1)
    r1 = h1.add_run("1. Purpose & System Overview")
    r1.font.color.rgb = PRIMARY

    doc.add_paragraph(
        "This Standard Operating Procedure (SOP) standardizes tournament desk operations for all Cecil Harford USBC "
        "(CHUSBC) championship, youth, and open events. The CHUSBC Tournament Desk Ops platform is a cloud-based suite "
        "designed to replace manual paper sheets, automate handicap calculations, synchronize real-time dual-screen check-ins, "
        "manage brackets/pots, and permanently archive official records to Google Sheets."
    )

    doc.add_paragraph(
        "The system operates across three synchronized tiers:\n"
        "• Tournament Director (TD) Console: The master administrative workstation running on the desk laptop. Used by officials to establish tournament settings, ingest rosters, collect entry fees, update scores, adjudicate rules disputes, run stepladder finals, and archive results.\n"
        "• Customer Kiosk Monitor (?mode=kiosk): A dedicated, full-screen display facing the registration queue. Communicates via a local server file bridge (/tmp/chusbc_kiosk_state.json) to display association welcome boards and real-time bowler check-in cards with high-contrast QR codes.\n"
        "• Bowler Smartphone Portal (?mode=checkin): A lightweight web app accessed when a bowler scans their personalized QR code. Confirms on-lane arrival and locks their assigned lane pair without requiring account creation or mobile app installation."
    )

    # --- SECTION 2 ---
    h2 = doc.add_heading(level=1)
    r2 = h2.add_run("2. Hardware Configuration & Station Setup")
    r2.font.color.rgb = PRIMARY

    doc.add_paragraph(
        "Desk staff must arrive at the host facility (e.g., Forest Hill Lanes, Harford Lanes, Elk Lanes) at least 60 minutes "
        "prior to squad practice to configure equipment per the following matrix:"
    )

    t_hw = doc.add_table(rows=5, cols=3)
    t_hw.alignment = WD_TABLE_ALIGNMENT.CENTER
    hw_headers = ["Component", "Physical Position", "Operational Role"]
    hw_widths = [Inches(1.8), Inches(1.9), Inches(2.8)]

    for i, title in enumerate(hw_headers):
        cell = t_hw.cell(0, i)
        cell.width = hw_widths[i]
        set_cell_background(cell, "0E3A8A")
        set_cell_padding(cell, 120, 120, 140, 140)
        p = cell.paragraphs[0]
        r = p.add_run(title)
        r.bold = True
        r.font.color.rgb = RGBColor(255, 255, 255)
        r.font.size = Pt(10)

    hw_rows = [
        ("TD Laptop", "Behind desk, facing official only", "Main operational workstation. Keep browser logged into the TD Console."),
        ("External Monitor", "Facing bowler registration queue", "Connected via HDMI/USB-C as 'Extended Display'. Runs ?mode=kiosk in fullscreen (F11)."),
        ("Cash Box & Receipts", "Beside TD Laptop (secure)", "Holds cash entries, checks, and side pot pools. Must balance against console totals."),
        ("Network / Hotspot", "Pre-tested before queue opens", "Ensure connection stability. Keep a staff cellular hotspot on standby for failover.")
    ]
    for row_idx, row_data in enumerate(hw_rows, start=1):
        for col_idx, val in enumerate(row_data):
            cell = t_hw.cell(row_idx, col_idx)
            cell.width = hw_widths[col_idx]
            set_cell_background(cell, "F8FAFC" if row_idx % 2 == 1 else "FFFFFF")
            set_cell_padding(cell, 100, 100, 140, 140)
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.1
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(val)
            r.font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # --- SECTION 3 ---
    h3 = doc.add_heading(level=1)
    r3 = h3.add_run("3. Standard Tournament Day Operating Procedure")
    r3.font.color.rgb = PRIMARY

    phases = [
        ("Phase 1: Event Calibration & Rules Locking",
         "1. Sign in to the console using your administrative or staff credentials.\n"
         "2. Navigate to Module 1: 'Event & Roster Intake' -> Tab 1: '⚙️ Event Settings & Rules PDF'.\n"
         "3. Fill in: Tournament Name, Host Bowling Center, Total Lanes, Active Pair Range (e.g., 1-16), and Division.\n"
         "4. Upload the tournament flyer PDF or paste tournament rules (handicap base, cut lines, roll-off provisions).\n"
         "5. Click 'Save & Lock Tournament Configuration' to lock parameters and index rules context for the AI Arbiter."),

        ("Phase 2: Bowler Roster Ingestion",
         "Switch to Tab 2: '📝 Roster Ingestion & Editing'. Board members may ingest bowlers through any of four methods:\n"
         "• Method A (Camera/Photo OCR): Select '📸 Scan/Photo Clipboard (AI)'. Take a snapshot of the paper clipboard using the laptop or tablet camera. Click 'Extract Bowlers from Photo with Gemini'.\n"
         "• Method B (AI Text Parser): Select '🤖 Paste Signup Notes (Gemini AI)'. Paste unformatted text (e.g., '11-12345 Scott Kramer 218 avg lane 1') and click 'Extract Roster with Gemini'.\n"
         "• Method C (CSV Import): Select '📁 Upload CSV'. Upload a roster sheet containing USBC ID, Bowler, Average, and Starting Lane.\n"
         "• Method D (Master Grid Entry): Select '📋 Editable Master Grid' for direct walk-in registration. Type directly into the grid and click 'Save Roster Changes'."),

        ("Phase 3: Customer Kiosk Launch",
         "1. Switch to Tab 3: '💳 Desk Intake & Payment Terminal'.\n"
         "2. Click the link button: '🖥️ Open External Bowler Kiosk Window'.\n"
         "3. Drag the new window to the external monitor and press F11 for fullscreen.\n"
         "4. Confirm the kiosk displays the Cecil Harford USBC logo and idle welcome board with the live checked-in counter."),

        ("Phase 4: Bowler Intake & Payment Gate",
         "When a bowler arrives at the desk:\n"
         "1. Locate the bowler in the 'Search / Select Bowler at Desk' dropdown.\n"
         "2. Verify payment received (Cash, Check, or Venmo/Electronic).\n"
         "3. Click 'Mark Paid & Display on Customer Screen'.\n"
         "4. The customer monitor updates within 2 seconds to display the bowler's Welcome Card: Name, USBC ID, Verified Entering Average, Starting Lane Pair, and Check-In QR Code.\n"
         "5. The bowler scans the QR code with their phone camera to confirm check-in.\n"
         "6. Manual Override: If the bowler has no smartphone, click 'Manual TD Check-In Override (No Phone)'.\n"
         "7. Click '🔄 Reset External Display (Show Welcome)' when the bowler departs to ready the screen for the next participant."),

        ("Phase 5: Side Action Enrollment (Brackets & Side Pots)",
         "Navigate to Module 4: 'Side Action: Brackets & Pots 💰':\n"
         "• 8-Bowler Brackets Tab: Choose Division (Scratch or Handicap), select number of brackets to seed, and click '🎲 Generate & Seed Brackets'. The system seeds random 8-person single-elimination trees ($25 1st, $10 2nd, $5 expense) that auto-advance based on entered game scores.\n"
         "• High-Game & Series Pots Tab: Enter buy-in (standard $10: $3 G1, $3 G2, $3 G3, $1 Series). Check off enrolled bowlers in the multi-select box. Payout pools and tied pot splits calculate automatically as scores post."),

        ("Phase 6: Live Score Entry & Official Standings",
         "1. Navigate to Module 2: 'Scores & Standings'.\n"
         "2. Enter scores in the 'Official Scoring Grid', or expand '⚡ Gemini Live Score Recap Ingestion', paste the printed series recap, and click 'Apply Recap Scores'.\n"
         "3. Click 'Save Scores & Recalculate Standings'. The deterministic engine applies 90% of 220 handicap, calculates scratch and grand totals, and ranks the field.\n"
         "4. Click '📄 Download Current Official PDF Standings' for printouts or concourse boards."),

        ("Phase 7: Stepladder Finals & Google Sheets Archiving",
         "1. Once qualifying concludes, navigate to Module 3: 'Stepladder Finals'.\n"
         "2. The top 5 seeds populate into the championship ladder (Match 1: #4 vs #5 -> Match 2: #3 vs M1 Winner -> Semifinal: #2 vs M2 Winner -> Championship: #1 vs Semi Winner).\n"
         "3. Adjudicate each match in order until the champion is established.\n"
         "4. Click 'Lock Champion in Audit Log'.\n"
         "5. Click '📦 Archive Tournament & Save Official PDF' to permanently commit the ReportLab PDF and event metadata to Google Sheets.")
    ]

    for p_title, p_body in phases:
        h_phase = doc.add_heading(level=2)
        r_phase = h_phase.add_run(p_title)
        r_phase.font.color.rgb = SECONDARY
        p = doc.add_paragraph(p_body)
        p.paragraph_format.space_after = Pt(6)

    # --- SECTION 4 ---
    h4 = doc.add_heading(level=1)
    r4 = h4.add_run("4. Rules Arbitration & Youth Compliance Guidelines")
    r4.font.color.rgb = PRIMARY

    doc.add_paragraph(
        "Desk officials should consult Module 5 ('AI Rules Arbiter') for on-lane protests. The system adjudicates "
        "disputes strictly against the tournament flyer context and the following USBC statutory baseline:"
    )

    t_rules = doc.add_table(rows=5, cols=2)
    t_rules.alignment = WD_TABLE_ALIGNMENT.CENTER
    r_headers = ["USBC Statute", "Mandatory Desk Ruling & Enforcement"]
    r_widths = [Inches(2.2), Inches(4.3)]

    for i, title in enumerate(r_headers):
        cell = t_rules.cell(0, i)
        cell.width = r_widths[i]
        set_cell_background(cell, "0E3A8A")
        set_cell_padding(cell, 120, 120, 140, 140)
        p = cell.paragraphs[0]
        r = p.add_run(title)
        r.bold = True
        r.font.color.rgb = RGBColor(255, 255, 255)
        r.font.size = Pt(10)

    rules_data = [
        ("USBC Rule 17: Altering Ball Surface", "Surface adjustments via abrasive pads (Abralon/Siaair) or liquid cleaners are strictly prohibited once official competition has begun. The ball must be removed immediately from competition. Any frames delivered with an altered ball post-adjustment incur zero scores."),
        ("USBC Rule 18: Equipment Specifications", "Balance holes (weight holes) are illegal. All drilled holes must be occupied by a gripping finger on every delivery. Non-gripping finger holes cannot be present."),
        ("USBC Rule 10: Tardy Bowlers", "A tardy bowler begins competition in the current frame being bowled by their assigned pair, provided the frame has not been completed by all bowlers on that pair. No warm-up frames or practice deliveries are permitted. Missed frames are scored zero."),
        ("USBC Rule 400: Youth SMART Eligibility", "CRITICAL MANDATE: In youth divisions, all prize funds, brackets, and awards must be deposited into the USBC SMART scholarship program. Awarding cash, checks, or general merchandise vouchers is strictly prohibited and forfeits bowler youth eligibility.")
    ]

    for row_idx, data in enumerate(rules_data, start=1):
        for col_idx, text in enumerate(data):
            cell = t_rules.cell(row_idx, col_idx)
            cell.width = r_widths[col_idx]
            set_cell_background(cell, "F8FAFC" if row_idx % 2 == 1 else "FFFFFF")
            set_cell_padding(cell, 100, 100, 140, 140)
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.1
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            r.font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # --- SECTION 5 ---
    h5 = doc.add_heading(level=1)
    r5 = h5.add_run("5. Contingency Procedures & Troubleshooting")
    r5.font.color.rgb = PRIMARY

    doc.add_paragraph(
        "• Kiosk Screen Does Not Update: The external kiosk tab communicates with the TD Console via an automated local file bridge (/tmp/chusbc_kiosk_state.json) polling every 2 seconds. If the external screen does not change within 3 seconds, click '🔄 Reset External Display (Show Welcome)', re-select the bowler on the TD laptop, and click '📺 Push to Customer Screen'.\n"
        "• Bowler Phone Camera Cannot Read QR: In low-light bowling centers, increase the external monitor brightness. If the phone still fails to focus, click 'Manual TD Check-In Override (No Phone)' on the TD console to confirm check-in instantly.\n"
        "• Internet Outage / Connection Drop: The application maintains in-memory session persistence. Do not force-refresh the primary browser window. If internet disconnects, switch to a mobile phone cellular hotspot immediately to resume Google Sheets cloud archiving.\n"
        "• Staff Account Password Reset: Board administrators can reset official credentials directly in Module 8: 'TD User Management ⚙️'."
    )

    filename = "CHUSBC_Tournament_Desk_SOP.docx"
    doc.save(filename)
    print(f"File created successfully: {filename}")

if __name__ == "__main__":
    create_sop_docx()

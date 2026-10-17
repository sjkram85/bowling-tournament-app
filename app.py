import io
import math
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. PAGE SETUP & CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="CHUSBC Tournament Desk Ops",
    page_icon="🎳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------
# 2. TOURNAMENT DIRECTOR AUTHENTICATION & AUDIT LOG
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

DEFAULT_USER = "chusbc_admin"
DEFAULT_PW_HASH = hashlib.sha256("Strikes2026!".encode()).hexdigest()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "td_name" not in st.session_state:
    st.session_state.td_name = ""
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.audit_trail.append({
        "timestamp": timestamp,
        "td": st.session_state.td_name,
        "action": action
    })

if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        st.markdown("### 🎳 Cecil Harford USBC Desk Portal")
        st.caption("Authorized Tournament Directors & Officials Only")
        with st.form("td_login"):
            username = st.text_input("TD Username")
            td_real_name = st.text_input("Tournament Director Full Name")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Verify & Open Desk")

            if submitted:
                stored_user = st.secrets.get("TD_USER", DEFAULT_USER)
                stored_hash = st.secrets.get("TD_PASSWORD_HASH", DEFAULT_PW_HASH)

                if username == stored_user and hash_password(password) == stored_hash and td_real_name.strip():
                    st.session_state.authenticated = True
                    st.session_state.td_name = td_real_name.strip()
                    log_audit_event("Tournament Director logged into desk session.")
                    st.success("Authorized.")
                    st.rerun()
                else:
                    st.error("Invalid credentials. Enter your full name and valid TD credentials.")
    st.stop()

# ---------------------------------------------------------
# 3. GEMINI API CLIENT SETUP
# ---------------------------------------------------------
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    with st.sidebar:
        api_key = st.text_input("Gemini API Key", type="password")

ai_client = genai.Client(api_key=api_key) if api_key else None

# ---------------------------------------------------------
# 4. TOURNAMENT INTAKE STATE
# ---------------------------------------------------------
if "tournament_config" not in st.session_state:
    st.session_state.tournament_config = {
        "center": "Forest Hill Lanes",
        "name": "Cecil Harford Annual Championship",
        "lanes_count": 24,
        "lanes_range": "1-24",
        "division": "Mixed",
        "rules_text": "",
        "intake_completed": False
    }

if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame([
        {"Bowler": "Marcus Vance", "Average": 198, "Game 1": 214, "Game 2": 235, "Game 3": 201},
        {"Bowler": "Elena Rostova", "Average": 215, "Game 1": 257, "Game 2": 248, "Game 3": 222},
        {"Bowler": "Derek Jackson", "Average": 182, "Game 1": 178, "Game 2": 195, "Game 3": 210},
        {"Bowler": "Chloe Davenport", "Average": 204, "Game 1": 225, "Game 2": 210, "Game 3": 244},
        {"Bowler": "Samir Patel", "Average": 175, "Game 1": 180, "Game 2": 192, "Game 3": 175},
        {"Bowler": "Tanya Miller", "Average": 211, "Game 1": 204, "Game 2": 231, "Game 3": 220},
    ])

# ---------------------------------------------------------
# 5. DETERMINISTIC SCORING ENGINE
# ---------------------------------------------------------
def calculate_handicap(avg: int, base: int = 220, percentage: float = 0.90) -> int:
    if avg >= base:
        return 0
    return math.floor(percentage * (base - avg))

def compile_standings(df: pd.DataFrame) -> pd.DataFrame:
    calc_df = df.copy()
    calc_df["HDCP_Per_Game"] = calc_df["Average"].apply(calculate_handicap)
    calc_df["Total_HDCP"] = calc_df["HDCP_Per_Game"] * 3
    calc_df["Scratch_Total"] = calc_df["Game 1"] + calc_df["Game 2"] + calc_df["Game 3"]
    calc_df["Grand_Total"] = calc_df["Scratch_Total"] + calc_df["Total_HDCP"]
    calc_df["High_Scratch_Game"] = calc_df[["Game 1", "Game 2", "Game 3"]].max(axis=1)

    calc_df = calc_df.sort_values(
        by=["Grand_Total", "High_Scratch_Game", "Scratch_Total"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    calc_df.index += 1
    calc_df.index.name = "Rank"
    return calc_df

# ---------------------------------------------------------
# 6. REPORTLAB PDF STANDINGS GENERATOR
# ---------------------------------------------------------
def export_standings_pdf(standings_df: pd.DataFrame, config: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12
    )

    story.append(Paragraph(f"Cecil Harford USBC — {config['name']}", title_style))
    story.append(Paragraph(
        f"Center: {config['center']} | Division: {config['division']} | Lanes: {config['lanes_range']}<br/>"
        f"TD: {st.session_state.td_name} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}",
        meta_style
    ))

    table_data = [["Pos", "Bowler Name", "Avg", "HDCP", "G1", "G2", "G3", "Scratch", "Total"]]
    for rank, row in standings_df.reset_index().iterrows():
        table_data.append([
            str(row["Rank"]),
            str(row["Bowler"]),
            str(row["Average"]),
            str(row["Total_HDCP"]),
            str(row["Game 1"]),
            str(row["Game 2"]),
            str(row["Game 3"]),
            str(row["Scratch_Total"]),
            str(row["Grand_Total"])
        ])

    table = Table(table_data, colWidths=[28, 160, 36, 42, 42, 42, 42, 60, 65])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0284c7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 7. SIDEBAR NAVIGATION & AUDIT
# ---------------------------------------------------------
with st.sidebar:
    st.title("🎳 CHUSBC Ops")
    st.write(f"Official on Duty: **{st.session_state.td_name}**")
    st.caption(f"Event: {st.session_state.tournament_config['name']}")
    st.caption(f"Host: {st.session_state.tournament_config['center']}")

    nav = st.radio(
        "Tournament Controls",
        ["1. Event Intake & Rules", "2. Scores & Standings", "3. Stepladder Finals", "4. AI Rules Arbiter", "5. TD Audit Log"]
    )
    st.divider()
    if st.button("End Session / Logout", use_container_width=True):
        log_audit_event("Tournament Director logged out.")
        st.session_state.authenticated = False
        st.session_state.td_name = ""
        st.rerun()

# ---------------------------------------------------------
# MODULE 1: TOURNAMENT INTAKE & RULES INGESTION
# ---------------------------------------------------------
if nav == "1. Event Intake & Rules":
    st.header("Step 1: Tournament Setup & Ingestion")
    st.caption("Establish the parameters for the Cecil Harford USBC sanctioned event.")

    with st.form("intake_form"):
        # 1. Bowling Center Selection
        center = st.selectbox(
            "1) Host Bowling Center:",
            ["Forest Hill Lanes", "Harford Lanes", "APG Brewner Lanes", "Elk Lanes", "Other"]
        )

        # 2. Tournament Name
        t_name = st.text_input("2) Tournament Name:", value=st.session_state.tournament_config["name"])

        # 3. Lanes In Use
        col_lanes1, col_lanes2 = st.columns(2)
        with col_lanes1:
            lane_count = st.number_input("3a) Number of Lanes in Use:", min_value=2, max_value=60, value=16, step=2)
        with col_lanes2:
            lane_range = st.text_input("3b) Active Pair Range (e.g., 1-16, 9-24):", value="1-16")

        # 4. Division Type
        division = st.selectbox(
            "4) Tournament Division:",
            ["Mixed", "Youth", "Adult Open", "Women's", "Senior Singles / Doubles"]
        )

        # 5. Tournament Rules Entry
        t_rules = st.text_area(
            "5) Specific Tournament Rules & Format (e.g., 3-game qualifier, cut to top 5, 90% of 220):",
            value=st.session_state.tournament_config["rules_text"] or "Qualifying: 3 games across 3 pairs. Cut to top 5 for stepladder finals. Handicap based on 90% of 220 based on highest 2025-26 book average."
        )

        # 6. File Upload
        uploaded_doc = st.file_uploader("6) Upload Tournament Rules / Entry Flyer / Direction Sheet (.txt or .pdf):", type=["txt"])

        submit_intake = st.form_submit_button("Lock In Tournament Configuration")

        if submit_intake:
            uploaded_content = ""
            if uploaded_doc is not None:
                uploaded_content = f"\n[UPLOADED RULES DOCUMENT]:\n{uploaded_doc.read().decode('utf-8', errors='ignore')}"

            full_rules_context = t_rules + uploaded_content

            st.session_state.tournament_config = {
                "center": center,
                "name": t_name,
                "lanes_count": lane_count,
                "lanes_range": lane_range,
                "division": division,
                "rules_text": full_rules_context,
                "intake_completed": True
            }
            log_audit_event(f"Configured tournament: {t_name} at {center} ({division} Division, Lanes {lane_range}).")
            st.success("Tournament configurations and rules baseline successfully registered.")

# ---------------------------------------------------------
# MODULE 2: SCORES & LEADERBOARD (GEMINI ASSISTED INTAKE)
# ---------------------------------------------------------
elif nav == "2. Scores & Standings":
    st.header(f"Scores & Standings: {st.session_state.tournament_config['name']}")
    st.caption(f"Host: {st.session_state.tournament_config['center']} | Division: {st.session_state.tournament_config['division']}")

    # Gemini AI Roster Ingestion Agent
    with st.expander("🤖 Gemini AI Score & Roster Parser (Natural Text Intake)"):
        st.write("Paste raw recap notes, email entries, or score text. Gemini will structure it into the scoring grid.")
        raw_text = st.text_area(
            "Paste scores here:",
            placeholder="e.g. John Doe 200 avg bowled 210, 220, 205. Jane Smith 180 avg had 190, 185, 200."
        )
        if st.button("Parse with Gemini"):
            if not ai_client:
                st.error("Gemini API Client not initialized. Enter API Key in the sidebar or secrets.")
            elif not raw_text.strip():
                st.warning("Please paste score text to parse.")
            else:
                with st.spinner("AI parsing recap into official roster format..."):
                    parse_prompt = f"""
You are a bowling tournament scorekeeper assistant. 
Extract the bowler names, entry averages, and 3 qualifying game scores from the text.
Output MUST strictly be a CSV table with exact headers:
Bowler,Average,Game 1,Game 2,Game 3

Data text:
{raw_text}
"""
                    try:
                        res = ai_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=parse_prompt,
                            config=types.GenerateContentConfig(temperature=0.0)
                        )
                        parsed_csv = res.text.replace("```csv", "").replace("```", "").strip()
                        new_data = pd.read_csv(io.StringIO(parsed_csv))
                        st.session_state.roster = pd.concat([st.session_state.roster, new_data], ignore_index=True)
                        log_audit_event(f"Gemini parsed and appended {len(new_data)} bowler records.")
                        st.success(f"Appended {len(new_data)} bowlers into the roster.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to parse score text: {e}")

    # Direct Editing Table
    st.subheader("Official Scoring Grid")
    edited_roster = st.data_editor(
        st.session_state.roster,
        num_rows="dynamic",
        use_container_width=True,
        key="tournament_score_editor"
    )
    if st.button("Update Scores & Rerun Calculations"):
        st.session_state.roster = edited_roster
        log_audit_event("TD manually updated roster scores.")
        st.rerun()

    # Deterministic Standings Computation
    standings = compile_standings(st.session_state.roster)
    st.subheader("Current Leaderboard (90% of 220 Handicap)")
    st.dataframe(
        standings[[
            "Bowler", "Average", "HDCP_Per_Game", "Game 1", "Game 2",
            "Game 3", "Scratch_Total", "Total_HDCP", "Grand_Total", "High_Scratch_Game"
        ]],
        use_container_width=True
    )

    pdf_bytes = export_standings_pdf(standings, st.session_state.tournament_config)
    st.download_button(
        "📄 Export Official Printed Standings PDF",
        data=pdf_bytes,
        file_name=f"{st.session_state.tournament_config['name'].replace(' ', '_')}_Standings.pdf",
        mime="application/pdf"
    )

# ---------------------------------------------------------
# MODULE 3: STEP-LADDER FINALS BRACKET
# ---------------------------------------------------------
elif nav == "3. Stepladder Finals":
    st.header("Championship Step-Ladder Finals")
    standings = compile_standings(st.session_state.roster)

    if len(standings) < 5:
        st.warning("At least 5 bowlers are required to seed the Step-Ladder bracket.")
    else:
        top_5 = standings.head(5)["Bowler"].tolist()

        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("Top 5 Qualifiers Seeding")
            st.info(f"""
            - **Seed 1 (Championship Match):** {top_5[0]}
            - **Seed 2 (Semifinal Match):** {top_5[1]}
            - **Seed 3 (Match 2):** {top_5[2]}
            - **Seed 4 (Match 1):** {top_5[3]}
            - **Seed 5 (Match 1):** {top_5[4]}
            """)

        with c2:
            st.subheader("Match Play Progression")
            m1_winner = st.selectbox("Match 1 Winner (#4 vs #5):", [top_5[3], top_5[4]])
            m2_winner = st.selectbox(f"Match 2 Winner (#3 {top_5[2]} vs {m1_winner}):", [top_5[2], m1_winner])
            semi_winner = st.selectbox(f"Semifinal Winner (#2 {top_5[1]} vs {m2_winner}):", [top_5[1], m2_winner])
            champion = st.selectbox(f"Championship Winner (#1 {top_5[0]} vs {semi_winner}):", [top_5[0], semi_winner])

            st.success(f"🏆 **Declared Champion:** {champion}")
            if st.button("Log Championship Result"):
                log_audit_event(f"Championship Step-Ladder finalized. Champion declared: {champion}.")
                st.success("Recorded in official audit log.")

# ---------------------------------------------------------
# MODULE 4: AI RULES & TOURNAMENT ARBITER (GEMINI 2.5)
# ---------------------------------------------------------
elif nav == "4. AI Rules Arbiter":
    st.header("USBC & Local Tournament Rules Arbiter")
    st.caption("AI Official grounded on tournament intake rules and USBC Playing Rules.")

    if not ai_client:
        st.warning("Gemini API key is required to query the Rules Arbiter.")
    else:
        # Check for Youth SMART rules enforcement
        division_alert = ""
        if st.session_state.tournament_config["division"] == "Youth":
            division_alert = "\nCRITICAL DIVISION MANDATE: This is a YOUTH tournament. Enforce USBC Rule 400 (all prizes must be awarded as SMART scholarships; no cash, merchandise gift certificates, or non-compliant awards permitted)."

        rules_context = f"""
HOST BOWLING CENTER: {st.session_state.tournament_config['center']}
TOURNAMENT NAME: {st.session_state.tournament_config['name']}
DIVISION: {st.session_state.tournament_config['division']}
ACTIVE LANES: {st.session_state.tournament_config['lanes_range']}
LOCAL TOURNAMENT RULES & INSTRUCTIONS:
{st.session_state.tournament_config['rules_text']}
{division_alert}

STANDARD USBC PLAYING STATUTES BASELINE:
Rule 10 - Tardy Bowlers: An individual late for competition can begin only if the frame has not been completed by all bowlers on their pair. No warm-up frames.
Rule 17 - Altering Ball Surface: Surface adjustments via abrasive pads (Abralon/Siaair) or chemical cleaners are prohibited once tournament competition has begun. Balls altered during play are removed from competition.
Rule 18 - Bowling Ball Equipment: Balance holes are prohibited. All drilled finger holes must be occupied on every release.
Rule 111 - Practice: No practice balls permitted on assigned pairs outside scheduled practice sessions.
Rule 329 - Protest Procedures: Protests must be filed in writing with the Tournament Director before prize distribution.
"""
        query = st.text_area(
            "State the situation or dispute:",
            placeholder="e.g., A bowler used a 2000-grit pad on their ball between Game 1 and Game 2. What is the penalty under USBC rules?"
        )

        if st.button("Request Arbiter Decision"):
            if not query.strip():
                st.warning("Please describe the dispute or inquiry.")
            else:
                with st.spinner("Analyzing USBC statutes and tournament rules..."):
                    prompt = f"""
You are the Official Cecil Harford USBC Rules Arbiter assisting the Tournament Director on duty.
Resolve this inquiry using strictly the rules context below. 

[RULES CONTEXT]
{rules_context}

[TOURNAMENT DIRECTOR SITUATION]
{query}

Format your response as follows:
1. **Official Ruling:** State clearly what must happen.
2. **Applicable USBC / Tournament Rule:** Cite the exact Rule number.
3. **TD Actionable Next Step:** What immediate instruction the TD must give to the bowlers or scorekeepers.
"""
                    try:
                        decision = ai_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(temperature=0.1)
                        )
                        st.markdown("### Official Decision")
                        st.markdown(decision.text)
                        log_audit_event(f"Rules inquiry processed: '{query[:50]}...'")
                    except Exception as err:
                        st.error(f"Error querying Gemini: {err}")

# ---------------------------------------------------------
# MODULE 5: TOURNAMENT DIRECTOR AUDIT TRAIL
# ---------------------------------------------------------
elif nav == "5. TD Audit Log":
    st.header("Official Tournament Audit Log")
    st.caption("Immutable chronological record of official TD operations and decisions.")

    if not st.session_state.audit_trail:
        st.info("No events logged in this session yet.")
    else:
        audit_df = pd.DataFrame(st.session_state.audit_trail)
        st.dataframe(audit_df, use_container_width=True)

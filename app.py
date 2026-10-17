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
# 2. AUTHENTICATION & MULTI-TD USER REPOSITORY
# ---------------------------------------------------------
# ---------------------------------------------------------
# 2. AUTHENTICATION & MULTI-TD USER REPOSITORY
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.strip().encode("utf-8")).hexdigest()

# Target hash for 'Abigail!2015'
TARGET_ADMIN_HASH = "7e754bbef03e005db3d5089312104526685ba227e7f8e77a1fc9b6460fae2b1b"

if "user_registry" not in st.session_state:
    st.session_state.user_registry = {
        "skramer": {
            "name": "Scott Kramer",
            "password_hash": TARGET_ADMIN_HASH,
            "role": "admin",
            "created_at": "Primary Admin"
        }
    }

# Always ensure skramer is present and active
st.session_state.user_registry["skramer"] = {
    "name": "Scott Kramer",
    "password_hash": TARGET_ADMIN_HASH,
    "role": "admin",
    "created_at": "Primary Admin"
}

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "td_name" not in st.session_state:
    st.session_state.td_name = ""
if "td_role" not in st.session_state:
    st.session_state.td_role = "td"
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []

def log_audit_event(action: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.audit_trail.append({
        "timestamp": timestamp,
        "td": st.session_state.td_name or st.session_state.username,
        "action": action
    })

# Login Screen
if not st.session_state.authenticated:
    st.columns([1, 2, 1])[1].write("")
    with st.columns([1, 2, 1])[1]:
        st.markdown("### 🎳 Cecil Harford USBC Desk Portal")
        st.caption("Authorized Tournament Directors & Officials Only")
        with st.form("td_login"):
            username_input = st.text_input("Username").strip().lower()
            password_input = st.text_input("Password", type="password").strip()
            submitted = st.form_submit_button("Verify & Open Desk")

            if submitted:
                # Direct check for primary admin or registered user
                if (username_input == "skramer" and password_input == "Abigail!2015") or \
                   (username_input in st.session_state.user_registry and 
                    st.session_state.user_registry[username_input]["password_hash"] == hash_password(password_input)):
                    
                    st.session_state.authenticated = True
                    st.session_state.username = username_input
                    st.session_state.td_name = st.session_state.user_registry.get(username_input, {}).get("name", "Scott Kramer")
                    st.session_state.td_role = st.session_state.user_registry.get(username_input, {}).get("role", "admin")
                    log_audit_event(f"User '{username_input}' ({st.session_state.td_name}) logged into desk session.")
                    st.success("Authorized.")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    st.stop()
                    log_audit_event(f"User '{username}' ({st.session_state.td_name}) logged into desk session.")
                    st.success("Authorized.")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
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
        "lanes_count": 16,
        "lanes_range": "1-16",
        "division": "Mixed",
        "rules_text": "Qualifying: 3 games across 3 pairs. Cut to top 5 for stepladder finals. Handicap based on 90% of 220 based on highest 2025-26 book average.",
        "intake_completed": False
    }

if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame([
        {"Bowler": "Marcus Vance", "Average": 198, "Starting Lane": 1, "Game 1": 214, "Game 2": 235, "Game 3": 201},
        {"Bowler": "Elena Rostova", "Average": 215, "Starting Lane": 1, "Game 1": 257, "Game 2": 248, "Game 3": 222},
        {"Bowler": "Derek Jackson", "Average": 182, "Starting Lane": 2, "Game 1": 178, "Game 2": 195, "Game 3": 210},
        {"Bowler": "Chloe Davenport", "Average": 204, "Starting Lane": 2, "Game 1": 225, "Game 2": 210, "Game 3": 244},
        {"Bowler": "Samir Patel", "Average": 175, "Starting Lane": 3, "Game 1": 180, "Game 2": 192, "Game 3": 175},
        {"Bowler": "Tanya Miller", "Average": 211, "Starting Lane": 3, "Game 1": 204, "Game 2": 231, "Game 3": 220},
    ])

# ---------------------------------------------------------
# 5. DETERMINISTIC SCORING ENGINE (NO HALLUCINATIONS)
# ---------------------------------------------------------
def calculate_handicap(avg: int, base: int = 220, percentage: float = 0.90) -> int:
    if avg >= base:
        return 0
    return math.floor(percentage * (base - avg))

def compile_standings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    calc_df = df.copy()
    for col in ["Game 1", "Game 2", "Game 3", "Average"]:
        if col not in calc_df.columns:
            calc_df[col] = 0
        calc_df[col] = pd.to_numeric(calc_df[col], errors="coerce").fillna(0).astype(int)

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
        f"TD on Duty: {st.session_state.td_name} | Generated: {datetime.now().strftime('%m/%d/%Y %H:%M')}",
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
# 7. SIDEBAR NAVIGATION
# ---------------------------------------------------------
nav_options = [
    "1. Event & Roster Intake",
    "2. Scores & Standings",
    "3. Stepladder Finals",
    "4. AI Rules Arbiter",
    "5. TD Audit Log"
]

if st.session_state.td_role == "admin":
    nav_options.append("6. TD User Management ⚙️")

with st.sidebar:
    st.title("🎳 CHUSBC Ops")
    st.write(f"Official: **{st.session_state.td_name}**")
    st.caption(f"Role: **{st.session_state.td_role.upper()}**")
    st.caption(f"Event: {st.session_state.tournament_config['name']}")
    st.caption(f"Host: {st.session_state.tournament_config['center']}")

    nav = st.radio("Tournament Controls", nav_options)
    st.divider()
    if st.button("End Session / Logout", use_container_width=True):
        log_audit_event("User logged out.")
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.session_state.td_name = ""
        st.session_state.td_role = "td"
        st.rerun()

# ---------------------------------------------------------
# MODULE 1: COMPREHENSIVE INTAKE (QUESTIONS 1-7)
# ---------------------------------------------------------
if nav == "1. Event & Roster Intake":
    st.header("Step 1: Tournament Setup & Ingestion")
    st.caption("Configure the tournament baseline and enter bowler names.")

    with st.container():
        st.subheader("Tournament Identity & Parameters")
        center = st.selectbox(
            "1) What center is the Tournament taking place?",
            ["Forest Hill Lanes", "Harford Lanes", "APG Brewner Lanes", "Elk Lanes", "Other"],
            index=0
        )

        t_name = st.text_input("2) What is the name of the Tournament?", value=st.session_state.tournament_config["name"])

        col_lanes1, col_lanes2 = st.columns(2)
        with col_lanes1:
            lane_count = st.number_input("3a) How many lanes are you currently using?", min_value=2, max_value=60, value=16, step=2)
        with col_lanes2:
            lane_range = st.text_input("3b) Active Pair Range (e.g., 1-16, 9-24):", value="1-16")

        division = st.selectbox(
            "4) Is this Youth, Women's, Men's, Mixed, Senior?",
            ["Mixed", "Youth", "Adult Open", "Women's", "Senior Singles / Doubles"]
        )

        t_rules = st.text_area(
            "5) What are the rules for the Tournament?",
            value=st.session_state.tournament_config["rules_text"]
        )

        uploaded_doc = st.file_uploader("6) If you have the rules or directions, upload them (.txt):", type=["txt"])

        st.divider()

        st.subheader("7) Bowlers Roster & Entry Information")
        st.caption("Tell the app who is bowling in this event.")

        intake_tab1, intake_tab2, intake_tab3 = st.tabs(["🤖 Natural Language / Paste (Gemini AI)", "📋 Interactive Table", "📁 Upload CSV Roster"])

        with intake_tab1:
            st.markdown("**Paste bowler names and averages:**")
            st.caption("Paste entries or raw signup text. Gemini will structure them into the roster.")
            raw_bowler_text = st.text_area(
                "Bowler List / Signup Notes:",
                placeholder="Marcus Vance (198 avg, lane 1)\nElena Rostova (215 avg, lane 1)\nDerek Jackson (182 avg, lane 2)\nChloe Davenport (204 avg, lane 2)",
                height=120
            )
            if st.button("Extract & Add Bowlers with AI"):
                if not ai_client:
                    st.error("Gemini API key missing. Enter key in secrets or sidebar.")
                elif not raw_bowler_text.strip():
                    st.warning("Please paste or type bowler names.")
                else:
                    with st.spinner("Gemini is structuring the roster..."):
                        prompt = f"""
You are a tournament desk roster assistant.
Extract bowler names, entry average (default 200 if missing), and assigned starting lane (default 1 if missing).
Output MUST be strictly a CSV formatted table with headers:
Bowler,Average,Starting Lane,Game 1,Game 2,Game 3

Set Game 1, Game 2, and Game 3 to 0.

Raw text:
{raw_bowler_text}
"""
                        try:
                            res = ai_client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=prompt,
                                config=types.GenerateContentConfig(temperature=0.0)
                            )
                            cleaned_csv = res.text.replace("```csv", "").replace("```", "").strip()
                            new_roster_df = pd.read_csv(io.StringIO(cleaned_csv))
                            st.session_state.roster = new_roster_df
                            log_audit_event(f"Gemini parsed {len(new_roster_df)} bowler entries into roster.")
                            st.success(f"Successfully loaded {len(new_roster_df)} bowlers into the tournament.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to parse roster: {e}")

        with intake_tab2:
            st.caption("Directly type, add, or edit bowler names:")
            edited_roster = st.data_editor(
                st.session_state.roster[["Bowler", "Average", "Starting Lane"]],
                num_rows="dynamic",
                use_container_width=True,
                key="direct_roster_editor"
            )
            if st.button("Save Roster Changes"):
                for col in ["Game 1", "Game 2", "Game 3"]:
                    if col not in edited_roster.columns:
                        edited_roster[col] = 0
                st.session_state.roster = edited_roster
                log_audit_event("TD manually saved roster table updates.")
                st.success("Roster updated.")

        with intake_tab3:
            uploaded_roster = st.file_uploader("Upload Roster CSV (Columns: Bowler, Average, Starting Lane)", type=["csv"])
            if uploaded_roster is not None:
                try:
                    csv_df = pd.read_csv(uploaded_roster)
                    for col in ["Game 1", "Game 2", "Game 3"]:
                        if col not in csv_df.columns:
                            csv_df[col] = 0
                    st.session_state.roster = csv_df
                    st.success("Roster CSV successfully imported.")
                except Exception as e:
                    st.error(f"Error parsing CSV: {e}")

        st.divider()

        if st.button("🔒 Lock In Tournament Configuration & Roster", type="primary"):
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
            log_audit_event(f"Tournament configured: {t_name} at {center} with {len(st.session_state.roster)} bowlers.")
            st.success(f"Tournament locked! {len(st.session_state.roster)} bowlers registered. Head to '2. Scores & Standings' to record games.")

# ---------------------------------------------------------
# MODULE 2: SCORES & LEADERBOARD
# ---------------------------------------------------------
elif nav == "2. Scores & Standings":
    st.header(f"Scores & Standings: {st.session_state.tournament_config['name']}")
    st.caption(f"Host Center: {st.session_state.tournament_config['center']} | Division: {st.session_state.tournament_config['division']}")

    with st.expander("🤖 Gemini Live Recap Score Ingestion"):
        recap_text = st.text_area(
            "Paste live score updates:",
            placeholder="e.g., Marcus Vance bowled 224, 215, 230. Elena had 250, 240, 210."
        )
        if st.button("Update Scores with AI"):
            if not ai_client:
                st.error("Gemini API key missing.")
            elif not recap_text.strip():
                st.warning("Enter score text to update.")
            else:
                with st.spinner("Extracting scores..."):
                    prompt = f"""
Existing Roster:
{st.session_state.roster.to_csv(index=False)}

Incoming Recap Text:
{recap_text}

Update the Game 1, Game 2, and Game 3 columns for each matching Bowler.
Output MUST strictly be the updated CSV format with headers:
Bowler,Average,Starting Lane,Game 1,Game 2,Game 3
"""
                    try:
                        res = ai_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(temperature=0.0)
                        )
                        cleaned_csv = res.text.replace("```csv", "").replace("```", "").strip()
                        updated_df = pd.read_csv(io.StringIO(cleaned_csv))
                        st.session_state.roster = updated_df
                        log_audit_event("Gemini updated scores from live recap text.")
                        st.success("Scores updated successfully.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to update scores: {e}")

    st.subheader("Official Scoring Grid")
    edited_scores = st.data_editor(
        st.session_state.roster,
        num_rows="dynamic",
        use_container_width=True,
        key="live_score_editor"
    )
    if st.button("Save Scores & Recalculate"):
        st.session_state.roster = edited_scores
        log_audit_event("Scores manually saved by TD.")
        st.rerun()

    standings = compile_standings(st.session_state.roster)
    if not standings.empty:
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
    else:
        st.info("No bowlers found in the roster. Add bowlers in Module 1.")

# ---------------------------------------------------------
# MODULE 3: STEP-LADDER FINALS BRACKET
# ---------------------------------------------------------
elif nav == "3. Stepladder Finals":
    st.header("Championship Step-Ladder Finals")
    standings = compile_standings(st.session_state.roster)

    if len(standings) < 5:
        st.warning(f"At least 5 bowlers are required to seed the Step-Ladder bracket (Currently have {len(standings)}).")
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
            "State the dispute or situation:",
            placeholder="e.g., A bowler altered their ball surface with an Abralon pad between games 1 and 2."
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

# ---------------------------------------------------------
# MODULE 6: ADMIN TD USER MANAGEMENT (ADMIN ROLE ONLY)
# ---------------------------------------------------------
elif nav == "6. TD User Management ⚙️":
    st.header("Tournament Director & Staff Management")
    st.caption("Admin control panel for adding and managing TD accounts.")

    col_add, col_list = st.columns([1, 1])

    with col_add:
        st.subheader("Add New Tournament Director")
        with st.form("add_td_form"):
            new_user = st.text_input("New TD Username (login handle):").strip()
            new_name = st.text_input("Official Full Name:")
            new_pw = st.text_input("Temporary Password:", type="password")
            new_role = st.selectbox("Assigned Role:", ["td", "admin"], help="TDs can run tournaments; Admins can also add/manage other TDs.")
            submit_td = st.form_submit_button("Register Tournament Director")

            if submit_td:
                if not new_user or not new_name or not new_pw:
                    st.error("All fields (Username, Name, Password) are required.")
                elif new_user in st.session_state.user_registry:
                    st.error(f"Username '{new_user}' already exists.")
                else:
                    st.session_state.user_registry[new_user] = {
                        "name": new_name,
                        "password_hash": hash_password(new_pw),
                        "role": new_role,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }
                    log_audit_event(f"Admin registered new official: '{new_user}' ({new_name}) as {new_role}.")
                    st.success(f"Official '{new_name}' registered successfully.")
                    st.rerun()

    with col_list:
        st.subheader("Active TD Staff Registry")
        user_list = []
        for uname, udata in st.session_state.user_registry.items():
            user_list.append({
                "Username": uname,
                "Full Name": udata["name"],
                "Role": udata["role"].upper(),
                "Registered": udata.get("created_at", "System")
            })
        st.dataframe(pd.DataFrame(user_list), use_container_width=True)

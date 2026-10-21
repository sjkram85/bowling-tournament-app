import os
import time
import json
import streamlit as st

# Active Google GenAI Production Flash Endpoints
PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.5-flash-lite"]


def get_ai_client(api_key: str = None):
    """Initializes and returns the Google GenAI client instance."""
    key = api_key or st.secrets.get("GEMINI_API_KEY", None) or os.environ.get("GEMINI_API_KEY", None)
    if not key:
        return None
    try:
        from google import genai

        return genai.Client(api_key=key)
    except Exception:
        return None


def classify_intent(query_text: str) -> str:
    """
    Distinguishes whether the user inquiry is asking for UI navigation/workflow
    guidance versus a formal USBC playing rule dispute arbitration.
    """
    q = query_text.lower().strip()

    rule_keywords = [
        "rule", "usbc", "penalty", "dispute", "illegal", "protest", "surface",
        "sand", "abralon", "polish", "balance hole", "weight hole", "tardy", "late",
        "dead ball", "foul", "blind", "absentee", "smart", "scholarship", "cash",
        "dry towel", "alcohol", "cleaner", "practice", "re-rack", "out of turn"
    ]

    workflow_keywords = [
        "next", "what do i do", "how do i", "where do i", "button", "tab",
        "step", "screen", "mode", "check in", "assign", "seed", "print",
        "export", "balance", "roster", "save", "download", "enter scores"
    ]

    is_rule = any(k in q for k in rule_keywords)
    is_workflow = any(k in q for k in workflow_keywords)

    if is_rule and not is_workflow:
        return "RULE_DISPUTE"
    elif is_workflow and not is_rule:
        return "WORKFLOW_GUIDE"
    return "HYBRID_OR_GENERAL"


def stream_prism_ai(query_text: str, runtime_context: dict, client=None):
    """
    Fast streaming generator yielding response tokens in real-time
    with model failover cascading for high-availability desk operations.
    """
    ai_client = client or get_ai_client()
    if not ai_client:
        yield "Prism AI is offline. Please configure a valid Gemini API key in secrets or the sidebar."
        return

    from google.genai import types

    intent = classify_intent(query_text)

    # 1. Specialized prompt routing for UI & step-by-step tournament operations
    if intent == "WORKFLOW_GUIDE":
        instructions = f"""
INTENT DETECTED: WORKFLOW / NEXT STEPS
The user needs direct guidance on what action to take next in Prism Lane Control.
- DO NOT cite USBC rule numbers or quote rulebook sections unless specifically requested.
- Provide a clean, numbered, step-by-step action plan tailored strictly to their CURRENT screen: '{runtime_context.get('screen')}' in {runtime_context.get('mode')} mode.
- Explicitly name the exact tabs, buttons, or input cards they should click.
- Tone: Direct, concise, and focused on immediate desk execution.
"""
    # 2. Specialized prompt routing for USBC rules disputes
    elif intent == "RULE_DISPUTE":
        instructions = """
INTENT DETECTED: USBC RULES DISPUTE
The user is arbitrating an on-lane competition dispute or eligibility rule question.
Structure your response strictly into three clean sections:
1. **Immediate Ruling:** State the exact verdict the Tournament Director must enforce on the pair right now.
2. **USBC Rule Citation:** State the official USBC Rule # (e.g., Rule 10, Rule 17, Rule 18, Rule 400) and summarize the statute clearly.
3. **Desk Action:** State what the TD must record or change on the screen in Prism Lane Control (e.g., score entry, zero frame, substitution, bracket adjustment).
"""
    # 3. Hybrid routing for situational questions
    else:
        instructions = f"""
INTENT DETECTED: GENERAL / SITUATIONAL HYBRID
Answer the inquiry directly. If an on-lane issue requires both a ruling and a software step, state the quick ruling first, followed immediately by the exact software action to take on screen '{runtime_context.get('screen')}'.
"""

    prompt = f"""
You are "Prism AI", the specialized tournament desk assistant for the Cecil-Harford USBC (CHUSBC).
Assisting Tournament Director / Staff Member: '{runtime_context.get('user', 'Staff')}'.

ACTIVE TOURNAMENT RUNTIME PARAMETERS:
- Operating Mode: {runtime_context.get('mode', 'Advanced')}
- Active Screen / Module: {runtime_context.get('screen', 'Main')}
- Event Name: {runtime_context.get('event_name', 'CHUSBC Tournament')}
- Host Center: {runtime_context.get('center', 'Forest Hill Bowling Center')}
- Active Lane Range: {runtime_context.get('lane_range', '1-40')}
- Current Field: {runtime_context.get('total_bowlers', 0)} Bowlers ({runtime_context.get('paid_bowlers', 0)} Paid, {runtime_context.get('checked_bowlers', 0)} Checked In)

USER INQUIRY:
"{query_text}"

{instructions}
"""

    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_err = None

    for model_name in models_to_try:
        try:
            stream = ai_client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=700
                )
            )
            has_yielded = False
            for chunk in stream:
                if chunk.text:
                    has_yielded = True
                    yield chunk.text
            if has_yielded:
                return
        except Exception as e:
            last_err = e
            continue

    yield f"Prism AI is temporarily unavailable. Details: {last_err}"


def ask_prism_ai(query_text: str, runtime_context: dict, client=None, status_container=None) -> str:
    """Non-streaming fallback for batch background evaluation."""
    chunks = []
    for chunk in stream_prism_ai(query_text, runtime_context, client=client):
        chunks.append(chunk)
    return "".join(chunks)


def parse_roster_text_with_gemini(raw_text: str, client=None) -> str:
    """
    Parses messy unformatted bowler sign-up rosters into a clean CSV table
    for bulk ingestion into live_roster.
    """
    ai_client = client or get_ai_client()
    if not ai_client:
        return ""

    from google.genai import types

    prompt = f"""
You are an expert bowling tournament data ingest parser.
Parse the following unformatted bowler signups into valid, comma-separated values (CSV).

Required CSV Columns (in order):
USBC ID,Bowler,Average,Starting Lane,Division,Team_Name

Field Rules:
1. "USBC ID": If missing, generate a unique placeholder like "TBD-101", "TBD-102", etc.
2. "Bowler": Full name of the bowler.
3. "Average": Entering book average (integer). If not provided, default to 200.
4. "Starting Lane": Default to 1.
5. "Division": If not specified, default to "Open".
6. "Team_Name": If team or doubles group is specified, use that exact group name; otherwise default to "Singles".

Output strictly raw CSV text with the header row. Do NOT wrap output in markdown code blocks, backticks, or explanatory text.

Raw Roster Input:
{raw_text}
"""

    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
    for model_name in models_to_try:
        try:
            res = ai_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0)
            )
            if res and res.text:
                return res.text.replace("```csv", "").replace("```", "").strip()
        except Exception:
            continue

    return ""

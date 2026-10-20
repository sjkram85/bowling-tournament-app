import time
import json
import streamlit as st
from google import genai
from google.genai import types

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]

def get_ai_client(api_key: str = None):
    """Initializes or retrieves the Google GenAI client."""
    key = api_key or st.secrets.get("GEMINI_API_KEY", None)
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception:
        return None

def ask_prism_ai(query_text: str, runtime_context: dict, client=None, status_container=None) -> str:
    """
    Context-aware tournament desk assistant with automatic retry, 
    multi-model fallback cascading, and visual status feedback.
    """
    ai_client = client or get_ai_client()
    if not ai_client:
        return "Prism AI is offline. Please enter a valid Gemini API key in secrets or the sidebar."

    prompt = f"""
You are "Prism AI", the tournament desk assistant for Cecil-Harford USBC (CHUSBC).
Assisting TD/volunteer '{runtime_context.get('user', 'Staff')}'.
CONTEXT: Mode: {runtime_context.get('mode')} | Screen: {runtime_context.get('screen')} | Event: {runtime_context.get('event_name')} | Center: {runtime_context.get('center')}
Field: {runtime_context.get('total_bowlers', 0)} bowlers ({runtime_context.get('paid_bowlers', 0)} paid, {runtime_context.get('checked_bowlers', 0)} checked in)
USER ASKS: "{query_text}"
Provide screen-aware directions for their active screen, USBC rules citations if requested, and step-by-step next actions without technical database jargon.
"""

    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_err = None

    for model_name in models_to_try:
        if status_container:
            status_container.update(
                label=f"Consulting Prism AI ({model_name})...", 
                state="running"
            )
            
        for attempt in range(2):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if any(k in err_str for k in ["503", "unavailable", "429", "quota", "resource_exhausted"]):
                    time.sleep(1.2)
                    continue
                break

    return f"Prism AI temporarily unavailable due to high API network traffic. Details: {last_err}"

def parse_roster_text_with_gemini(raw_text: str, client=None) -> str:
    """Extracts raw pasted text into standard CSV format for roster ingestion."""
    ai_client = client or get_ai_client()
    if not ai_client:
        return ""
    prompt = f"""
Extract USBC ID (default 'TBD'), Bowler name, Average (default 200), Starting Lane (1), Division ('Open'), Team_Name ('Singles').
Output strictly raw valid CSV headers and rows with NO markdown formatting:
{raw_text}
"""
    try:
        res = ai_client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0)
        )
        return res.text.replace("```csv", "").replace("```", "").strip()
    except Exception:
        return ""

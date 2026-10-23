"""AI Roster Ingestion Engine with dynamic model auto-discovery."""

import json
import os
import re
import streamlit as st
from google import genai
from google.genai import types


def get_gemini_client():
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def get_best_available_model(client: genai.Client) -> str:
    """Queries the Gemini API for online models and picks the latest active Flash model."""
    # 1. Allow explicit override via secrets if specified
    override = st.secrets.get("GEMINI_MODEL")
    if override:
        return override

    # 2. Dynamic discovery via client.models.list()
    try:
        available_models = []
        for m in client.models.list():
            name = getattr(m, "name", "") or getattr(m, "id", "")
            # Clean model prefix (e.g. "models/gemini-..." -> "gemini-...")
            cleaned_name = name.split("/")[-1] if "/" in name else name

            # Only look for multimodal Flash models suitable for content generation
            if "flash" in cleaned_name.lower():
                supported = getattr(m, "supported_actions", []) or getattr(m, "supported_generation_methods", [])
                if not supported or "generateContent" in supported:
                    available_models.append(cleaned_name)

        if available_models:
            # Sort version numbers descending to pick the newest online release
            def extract_version_key(model_str: str):
                nums = re.findall(r"(\d+(?:\.\d+)?)", model_str)
                return [float(n) for n in nums] if nums else [0.0]

            available_models.sort(key=extract_version_key, reverse=True)
            return available_models[0]
    except Exception:
        pass

    # 3. Clean fallback
    return "gemini-2.5-flash"


def parse_roster_with_gemini(file_bytes: bytes, file_name: str) -> list[dict]:
    """Passes an uploaded roster document to the dynamically discovered online Gemini model."""
    client = get_gemini_client()
    if not client:
        raise ValueError(
            "GEMINI_API_KEY is missing. Please add GEMINI_API_KEY to your Streamlit secrets or environment variables."
        )

    # Dynamically select the newest online model
    active_model = get_best_available_model(client)

    # Determine MIME type based on file extension
    fn_lower = file_name.lower()
    if fn_lower.endswith(".pdf"):
        mime = "application/pdf"
    elif fn_lower.endswith(".xlsx"):
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fn_lower.endswith(".xls"):
        mime = "application/vnd.ms-excel"
    elif fn_lower.endswith(".docx"):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fn_lower.endswith(".csv"):
        mime = "text/csv"
    elif fn_lower.endswith(".png"):
        mime = "image/png"
    elif fn_lower.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    else:
        mime = "text/plain"

    prompt = (
        "You are an expert tournament director intake assistant for the Cecil Harford USBC. "
        "Extract all bowling competitors from the attached document. "
        "For each bowler found, extract:\n"
        "- name: Bowler Full Name (required string)\n"
        "- usbc_id: USBC Member ID (string or null)\n"
        "- entering_avg: Entering average (integer, default 200 if not listed)\n"
        "- handicap: Entering handicap (integer, default calculated as 90% of (220 - avg) if not listed, min 0)\n"
        "- lane_assignment: Starting lane number (integer, default 1 if not listed)\n"
        "- email: Bowler email address (string or null)\n"
        "- is_youth: Boolean true if labeled youth, junior, Rule 400, or has SMART account, else false\n"
        "- smart_account_id: SMART scholarship ID (string or null)\n"
        "- paid_status: 'paid' or 'unpaid' (default 'paid' unless noted as unpaid or owing)\n\n"
        "Return ONLY a valid JSON array of objects without markdown formatting or code blocks. Example:\n"
        '[{"name": "John Doe", "usbc_id": "1234-5678", "entering_avg": 210, "handicap": 9, '
        '"lane_assignment": 3, "email": "johndoe@example.com", "is_youth": false, "smart_account_id": null, "paid_status": "paid"}]'
    )

    part = types.Part.from_bytes(data=file_bytes, mime_type=mime)

    response = client.models.generate_content(
        model=active_model,
        contents=[prompt, part],
    )

    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("\n", 1)[0].strip()

    records = json.loads(raw_text)
    if isinstance(records, dict) and "bowlers" in records:
        records = records["bowlers"]

    return records
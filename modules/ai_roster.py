"""AI Roster Ingestion Engine targeting gemini-3.8-flash with auto-retry and 503 fallback."""

import io
import json
import os
import time
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-2.5-flash"


def get_gemini_client():
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def get_best_available_model(client: genai.Client = None) -> str:
    return st.secrets.get("GEMINI_MODEL", PRIMARY_MODEL)


EXTRACTION_PROMPT = (
    "You are an expert tournament director intake assistant for the Cecil Harford USBC. "
    "Extract all bowling competitors from the provided tournament roster data. "
    "For every bowler found, extract the following fields strictly:\n"
    "- name: Bowler Full Name (required string)\n"
    "- usbc_id: USBC Member ID (string or null)\n"
    "- entering_avg: Entering average (integer, default 200 if not listed)\n"
    "- handicap: Entering handicap (integer, default calculated as 90% of (220 - avg) if not listed, min 0)\n"
    "- lane_assignment: Starting lane number (integer, default 1 if not listed)\n"
    "- email: Bowler email address (string or null)\n"
    "- is_youth: Boolean true if explicitly labeled youth, junior, Rule 400, or has a SMART account, else false\n"
    "- smart_account_id: SMART scholarship ID (string or null)\n"
    "- paid_status: 'paid' or 'unpaid' (default 'paid' unless noted as unpaid, owing, or balance due)\n\n"
    "Return ONLY a clean JSON array of objects conforming to this schema."
)


def _extract_text_from_file(file_bytes: bytes, file_name: str) -> str | None:
    fn = file_name.lower()
    if fn.endswith((".xlsx", ".xls")):
        try:
            excel_file = io.BytesIO(file_bytes)
            xls = pd.ExcelFile(excel_file)
            sheets_text = []
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet)
                sheets_text.append(f"--- Sheet: {sheet} ---\n" + df.to_csv(index=False))
            return "\n\n".join(sheets_text)
        except Exception:
            return None

    if fn.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            table_rows = []
            for t in doc.tables:
                for row in t.rows:
                    table_rows.append(" | ".join(cell.text.strip() for cell in row.cells))
            return "\n".join(paragraphs + table_rows)
        except Exception:
            return None

    if fn.endswith(".csv"):
        try:
            return file_bytes.decode("utf-8-sig", errors="replace")
        except Exception:
            return None

    if fn.endswith(".txt"):
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception:
            return None

    return None


def _format_records(raw_text: str) -> list[dict]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("\n", 1)[0].strip()

    records = json.loads(cleaned)
    if isinstance(records, dict):
        for key in ("bowlers", "roster", "competitors", "players"):
            if key in records and isinstance(records[key], list):
                return records[key]
        return [records]
    return records


def _call_gemini_with_retry(client: genai.Client, model: str, contents, config) -> str:
    """Invokes generate_content with retry on 503 spikes."""
    models_to_try = [model, PRIMARY_MODEL, FALLBACK_MODEL]
    last_exc = None

    for mod in dict.fromkeys(models_to_try):
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=mod, contents=contents, config=config)
                return response.text
            except Exception as e:
                err_str = str(e)
                last_exc = e
                if "503" in err_str or "UNAVAILABLE" in err_str or "demand" in err_str:
                    time.sleep(1.5)
                    continue
                break

    raise last_exc


def parse_roster_with_gemini(file_bytes: bytes, file_name: str) -> list[dict]:
    client = get_gemini_client()
    if not client:
        raise ValueError("GEMINI_API_KEY is missing from Streamlit secrets or environment.")

    model_name = get_best_available_model(client)
    extracted_text = _extract_text_from_file(file_bytes, file_name)

    if extracted_text:
        contents = [EXTRACTION_PROMPT, f"--- DOCUMENT DATA ({file_name}) ---\n{extracted_text}"]
    else:
        fn_lower = file_name.lower()
        if fn_lower.endswith(".pdf"):
            mime = "application/pdf"
        elif fn_lower.endswith(".png"):
            mime = "image/png"
        elif fn_lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        else:
            mime = "application/octet-stream"

        part = types.Part.from_bytes(data=file_bytes, mime_type=mime)
        contents = [EXTRACTION_PROMPT, part]

    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
    text = _call_gemini_with_retry(client, model_name, contents, config)
    return _format_records(text)


def parse_roster_text_with_gemini(raw_text_input: str) -> list[dict]:
    client = get_gemini_client()
    if not client:
        raise ValueError("GEMINI_API_KEY is missing from Streamlit secrets or environment.")

    model_name = get_best_available_model(client)
    contents = [EXTRACTION_PROMPT, f"--- PASTED ROSTER TEXT ---\n{raw_text_input}"]
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)

    text = _call_gemini_with_retry(client, model_name, contents, config)
    return _format_records(text)
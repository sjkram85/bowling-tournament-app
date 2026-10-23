"""AI Roster Ingestion Engine targeting gemini-3.8-flash with strict HTTP timeouts and zero-hang fallback."""

import io
import json
import os
import re
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# Use gemini-3.8-flash as the primary engine
PRIMARY_MODEL = "gemini-3.8-flash"


def get_gemini_client() -> genai.Client | None:
    """Initialize GenAI client with strict 15-second timeout and no silent multi-minute backoff hangs."""
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=15_000,  # 15,000 ms (15 seconds) hard ceiling
            retry_options=types.HttpRetryOptions(
                attempts=2,
                initial_delay=1.0,
                http_status_codes=[408, 429, 500, 502, 503, 504],
            ),
        ),
    )


def get_best_available_model(client: genai.Client = None) -> str:
    """Return active model without blocking catalog enumeration."""
    return st.secrets.get("GEMINI_MODEL", PRIMARY_MODEL)


EXTRACTION_PROMPT = (
    "You are an expert tournament director intake assistant for the Cecil Harford USBC. "
    "Extract all bowling competitors from the provided tournament roster data into a JSON array. "
    "Each object in the JSON array must contain ONLY these keys:\n"
    "- name: string (Bowler Full Name)\n"
    "- usbc_id: string or null (USBC ID)\n"
    "- entering_avg: integer or null if not listed\n"
    "- handicap: integer or null if not listed\n"
    "- lane_assignment: integer or null if not listed (starting lane number)\n"
    "- email: string or null\n"
    "- is_youth: boolean (true if Youth, Junior, Rule 400, or SMART is noted)\n"
    "- smart_account_id: string or null (SMART ID number if present)\n"
    "- paid_status: 'paid', 'unpaid', or null if not stated\n\n"
    "Output raw valid JSON only."
)


def _extract_text_from_file(file_bytes: bytes, file_name: str) -> str | None:
    """Convert spreadsheets, Word docs, CSVs, and text files into raw text for fast processing."""
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
    """Clean markdown fences and normalize JSON output to a list of bowler dicts."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("\n", 1)[0].strip()

    records = json.loads(cleaned)
    if isinstance(records, dict):
        for key in ("bowlers", "roster", "competitors", "players", "data"):
            if key in records and isinstance(records[key], list):
                return records[key]
        return [records]
    return records if isinstance(records, list) else []


def _fast_structured_text_parser(text: str) -> list[dict]:
    """
    High-speed local parser for structured line/CSV rosters.
    Guarantees instant extraction if Gemini hits a high-demand spike.
    """
    bowlers = []
    for line in text.strip().splitlines():
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("---"):
            continue

        lane_m = re.search(r"Lane\s*(\d+)", line_clean, re.IGNORECASE)
        lane = int(lane_m.group(1)) if lane_m else None

        name_m = re.search(r"(?:Lane\s*\d+\s*[:\-]\s*)?([A-Za-z\s'\.\-]+?)(?:\s*[\(\-\|,]|$)", line_clean)
        name = name_m.group(1).strip() if name_m else ""
        if not name or name.lower() in ("lane", "name", "bowler"):
            continue

        usbc_m = re.search(r"USBC[:\s#]*([0-9\-]+)", line_clean, re.IGNORECASE)
        usbc_id = usbc_m.group(1).strip() if usbc_m else ""

        avg_m = re.search(r"Avg[:\s]*(\d+)", line_clean, re.IGNORECASE)
        avg = int(avg_m.group(1)) if avg_m else None

        hdcp_m = re.search(r"HDCP[:\s]*(\d+)", line_clean, re.IGNORECASE)
        hdcp = int(hdcp_m.group(1)) if hdcp_m else None

        email_m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", line_clean)
        email = email_m.group(0).strip() if email_m else ""

        is_youth = bool(re.search(r"\b(youth|junior|smart|rule\s*400)\b", line_clean, re.IGNORECASE))

        smart_m = re.search(r"SMART[:\s#]*([0-9A-Za-z\-]+)", line_clean, re.IGNORECASE)
        smart_id = smart_m.group(1).strip() if smart_m else ""
        if smart_id.lower() in ("email", "paid", "unpaid"):
            smart_id = ""

        if re.search(r"\b(unpaid|owing|due)\b", line_clean, re.IGNORECASE):
            paid = "unpaid"
        elif re.search(r"\bpaid\b", line_clean, re.IGNORECASE):
            paid = "paid"
        else:
            paid = None

        bowlers.append({
            "name": name,
            "usbc_id": usbc_id,
            "entering_avg": avg,
            "handicap": hdcp,
            "lane_assignment": lane,
            "email": email,
            "is_youth": is_youth,
            "smart_account_id": smart_id,
            "paid_status": paid,
        })
    return bowlers


def parse_roster_with_gemini(file_bytes: bytes, file_name: str) -> list[dict]:
    """Ingest uploaded document via Gemini with 15s timeout and local fallback."""
    client = get_gemini_client()
    extracted_text = _extract_text_from_file(file_bytes, file_name)

    if not client:
        if extracted_text:
            return _fast_structured_text_parser(extracted_text)
        raise ValueError("GEMINI_API_KEY is missing from Streamlit secrets.")

    model_name = get_best_available_model(client)

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

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )
        records = _format_records(response.text)
        if records:
            return records
    except Exception as exc:
        if extracted_text:
            fallback_records = _fast_structured_text_parser(extracted_text)
            if fallback_records:
                return fallback_records
        raise RuntimeError(f"Model {model_name} error: {exc}")

    return _fast_structured_text_parser(extracted_text) if extracted_text else []


def parse_roster_text_with_gemini(raw_text_input: str) -> list[dict]:
    """Ingest pasted text via Gemini with 15s timeout and instant fallback on errors."""
    client = get_gemini_client()
    if not client:
        return _fast_structured_text_parser(raw_text_input)

    model_name = get_best_available_model(client)
    contents = [EXTRACTION_PROMPT, f"--- PASTED ROSTER TEXT ---\n{raw_text_input}"]

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )
        records = _format_records(response.text)
        if records:
            return records
    except Exception:
        fallback_records = _fast_structured_text_parser(raw_text_input)
        if fallback_records:
            return fallback_records
        raise

    return _fast_structured_text_parser(raw_text_input)
"""Roster ingestion: Grok extraction (via modules.ai_provider) plus the built-in line reader."""

import io
import json
import re

import pandas as pd

from modules import ai_provider
from modules.ai_provider import AIError
from modules.settings import ai_available


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
    Guarantees instant extraction if Grok hits a high-demand spike.
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


def _as_records(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("bowlers", "roster", "competitors", "players", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return data if isinstance(data, list) else []


_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def parse_roster_with_grok(file_bytes: bytes, file_name: str) -> list[dict]:
    """Read an uploaded document with Prism A.I. Raises AIError (plain English) on any problem."""
    extracted_text = _extract_text_from_file(file_bytes, file_name)
    if extracted_text:
        data = ai_provider.extract_json(EXTRACTION_PROMPT, data=f"--- DOCUMENT DATA ({file_name}) ---\n{extracted_text}")
    else:
        ext = "." + file_name.lower().rsplit(".", 1)[-1]
        data = ai_provider.extract_json(EXTRACTION_PROMPT, file_bytes=file_bytes, mime_type=_MIME.get(ext, "application/octet-stream"))
    return _as_records(data)


def parse_roster_text_with_grok(raw_text_input: str) -> list[dict]:
    """Read pasted text. Uses Prism A.I. when it's set up; otherwise the built-in line reader."""
    if not ai_available():
        return _fast_structured_text_parser(raw_text_input)
    data = ai_provider.extract_json(EXTRACTION_PROMPT, data=f"--- PASTED ROSTER TEXT ---\n{raw_text_input}")
    return _as_records(data)

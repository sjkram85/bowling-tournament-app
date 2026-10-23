"""AI Roster Ingestion Engine targeting gemini-3.8-flash with structured schema output."""

import io
import json
import os
import pandas as pd
from pydantic import BaseModel, Field
import streamlit as st
from google import genai
from google.genai import types

PRIMARY_MODEL = "gemini-3.8-flash"


class BowlerSchema(BaseModel):
    name: str = Field(description="Full name of the bowler")
    usbc_id: str | None = Field(default=None, description="USBC sanction member ID")
    entering_avg: int = Field(default=200, description="Entering book or tournament average")
    handicap: int = Field(default=0, description="Handicap pins per game")
    lane_assignment: int = Field(default=1, description="Assigned starting lane number")
    email: str | None = Field(default=None, description="Email address for recaps")
    is_youth: bool = Field(default=False, description="True if marked youth, junior, or SMART")
    smart_account_id: str | None = Field(default=None, description="SMART scholarship account number")
    paid_status: str = Field(default="paid", description="'paid' or 'unpaid'")


class RosterSchema(BaseModel):
    bowlers: list[BowlerSchema]


def get_gemini_client():
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def get_best_available_model(client: genai.Client = None) -> str:
    return st.secrets.get("GEMINI_MODEL", PRIMARY_MODEL)


EXTRACTION_PROMPT = (
    "Extract all bowling competitors from the provided tournament roster data. "
    "Follow standard USBC guidelines: if handicap is not specified, calculate as 90% of (220 - avg) (minimum 0). "
    "Mark is_youth as true if the record contains SMART, youth, or junior tags."
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

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RosterSchema,
        temperature=0.0,
    )

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=config,
    )
    data = json.loads(response.text)
    return data.get("bowlers", [])


def parse_roster_text_with_gemini(raw_text_input: str) -> list[dict]:
    client = get_gemini_client()
    if not client:
        raise ValueError("GEMINI_API_KEY is missing from Streamlit secrets or environment.")

    model_name = get_best_available_model(client)
    contents = [EXTRACTION_PROMPT, f"--- PASTED ROSTER TEXT ---\n{raw_text_input}"]
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RosterSchema,
        temperature=0.0,
    )

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=config,
    )
    data = json.loads(response.text)
    return data.get("bowlers", [])
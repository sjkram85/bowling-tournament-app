"""AI Overhead Score OCR Ingestion Engine powered by Gemini Multimodal Vision."""

import io
import json
import os
import streamlit as st
from PIL import Image
from modules.settings import get_secret, ai_available, AI_OFF_MESSAGE

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


def extract_scores_from_overhead_photo(image_bytes: bytes) -> dict:
    """
    Submits a photo of a bowling overhead screen to Gemini Vision to parse bowler pinfall.
    Returns structured JSON containing names, scratch total, and frame scores.
    """
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key or not GENAI_AVAILABLE:
        # Never invent scores: report that A.I. is off instead.
        return {"status": "error", "message": AI_OFF_MESSAGE, "extracted_data": []}

    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "Analyze this bowling overhead scoring monitor display. Extract each bowler's name and their final "
            "scratch game score. Output ONLY raw JSON matching this format:\n"
            "{\"bowlers\": [{\"name\": \"string\", \"game_score\": integer}]}\n"
            "Do not include Markdown backticks or any conversational text."
        )

        image = Image.open(io.BytesIO(image_bytes))
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, image],
        )

        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned_text)
        return {"status": "success", "extracted_data": parsed.get("bowlers", [])}

    except Exception as exc:
        return {"status": "error", "message": f"Vision parsing failed: {str(exc)}", "extracted_data": []}
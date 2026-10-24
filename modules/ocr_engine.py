"""Overhead monitor photo reading, via modules.ai_provider."""

from modules import ai_provider
from modules.ai_provider import AIError

OCR_PROMPT = (
    "Analyze this bowling overhead scoring monitor display. Extract each bowler's name and their final "
    "scratch game score. Output JSON matching this format: "
    '{"bowlers": [{"name": "string", "game_score": integer, "confidence": number 0-1}]}. '
    "If a score is unreadable, use null for game_score. Never guess."
)


def extract_scores_from_overhead_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Read bowler names and scores from a monitor photo. Never invents scores."""
    try:
        parsed = ai_provider.read_image(OCR_PROMPT, image_bytes, mime_type)
    except AIError as exc:
        return {"status": "error", "message": str(exc), "extracted_data": []}
    bowlers = parsed.get("bowlers", []) if isinstance(parsed, dict) else parsed
    return {"status": "success", "extracted_data": bowlers if isinstance(bowlers, list) else []}

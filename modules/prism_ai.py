"""Dual-engine Gemini router: rulebook-grounded Pro for disputes, Flash for quick guidance."""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PRO_MODEL = "gemini-pro-latest"
FLASH_MODEL = "gemini-flash-latest"
RULEBOOK_PATH = Path(__file__).resolve().parent.parent / "assets" / "USBC-Playing-Rulebook-26-27.pdf"

RULE_KEYWORDS = re.compile(
    r"\b(rules?|disputes?|ruling|rulebook|usbc|legal|illegal|foul|protest|"
    r"penalty|violation|allowed|permitted|official|regulation|interference|"
    r"deadwood|dead\s*ball|out\s+of\s+order|re-?rate|rerate|319|misconduct|appeal)\b",
    re.IGNORECASE,
)

FLASH_INSTRUCTION = (
    "You are Prism, an assistant for bowling tournament directors. Observe the "
    "provided screen state and suggest the next logical tournament desk action in "
    "under two sentences. Do not cite or quote rulebooks."
)
PRO_INSTRUCTION = (
    "You are Prism, a USBC rules expert assisting a tournament director. Use the "
    "query_usbc_rulebook tool to ground every ruling in the USBC Playing Rulebook "
    "(dead ball, foul, out of order, Rule 319 average rerate and similar disputes), "
    "cite the relevant rule, and keep the answer brief."
)


def _get_client() -> genai.Client:
    key = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    if not key or key.startswith("YOUR_"):
        raise ValueError("GEMINI_API_KEY is missing or still a placeholder")
    return genai.Client(api_key=key)


@lru_cache(maxsize=1)
def _load_rulebook() -> bytes:
    return RULEBOOK_PATH.read_bytes()


def query_usbc_rulebook(query: str) -> str:
    """Look up the USBC Playing Rulebook and answer a rules question.

    Use for rule disputes such as dead ball, foul, out of order, or Rule 319 average rerate.

    Args:
        query: The rule or dispute question to research in the rulebook.
    """
    try:
        response = _get_client().models.generate_content(
            model=FLASH_MODEL,
            contents=[
                types.Part.from_bytes(data=_load_rulebook(), mime_type="application/pdf"),
                "Using only this rulebook, answer the question and cite the "
                f"rule number and page where possible.\n\nQuestion: {query}",
            ],
        )
    except Exception as e:
        logger.error("Rulebook lookup failed: %s", e)
        return "The rulebook lookup is unavailable right now. Please check the USBC Playing Rulebook directly."
    return response.text or "No relevant rule found."


def extract_scores_from_photo(image_bytes: bytes, bowler_names: list[str]) -> dict[str, int]:
    """OCR a photo of a score sheet; returns {bowler name: score} for recognized names only."""
    try:
        response = _get_client().models.generate_content(
            model=FLASH_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                "Read this bowling score sheet. Return a JSON object mapping each of these "
                f"bowler names to their final game score as an integer: {json.dumps(bowler_names)}. "
                "Omit any bowler whose score is not clearly legible.",
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        parsed = json.loads(response.text or "{}")
    except (KeyError, ValueError, genai.errors.APIError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        name: int(score)
        for name, score in parsed.items()
        if name in bowler_names and isinstance(score, (int, float)) and 0 <= score <= 300
    }


def _is_rules_query(user_prompt: str | None) -> bool:
    return bool(user_prompt and RULE_KEYWORDS.search(user_prompt))


def _fallback_guidance(screen_state: dict, user_prompt: str | None) -> str:
    """Friendly operational hint from the screen state when the AI is unavailable."""
    if _is_rules_query(user_prompt):
        return "💡 The rules assistant is unavailable. Check the USBC Playing Rulebook directly and note the ruling in the audit log."
    state = screen_state if isinstance(screen_state, dict) else {}
    game = state.get("game")
    reported, total = state.get("pairs_reported"), state.get("pairs_total")
    pending = state.get("pairs_pending") or []
    if isinstance(reported, int) and isinstance(total, int) and total:
        if reported >= total:
            label = f"Game {game}" if game else "the game"
            return f"💡 All pairs have reported {label}. Review the leaderboard, then move on to the next game or finals."
        if pending:
            listed = ", ".join(str(p) for p in pending[:6]) + ("…" if len(pending) > 6 else "")
            return f"💡 Waiting on lane reports (pairs {listed}). Tap Enter Scores or use the mobile verifier."
    return "💡 Waiting on lane reports for the active game. Tap Enter Scores or use mobile verifier."


def get_prism_ai_guidance(screen_state: dict, user_prompt: str | None = None) -> str:
    """Route to Pro (rules/disputes, rulebook tool) or Flash (screen-state guidance).

    Never raises: any failure is logged and replaced by a screen-state based fallback.
    """
    try:
        client = _get_client()
        state_text = json.dumps(screen_state, default=str)

        if _is_rules_query(user_prompt):
            response = client.models.generate_content(
                model=PRO_MODEL,
                contents=f"Screen state: {state_text}\n\nQuestion: {user_prompt}",
                config=types.GenerateContentConfig(
                    system_instruction=PRO_INSTRUCTION,
                    tools=[query_usbc_rulebook],
                ),
            )
        else:
            prompt = f"Screen state: {state_text}"
            if user_prompt:
                prompt += f"\n\nUser request: {user_prompt}"
            response = client.models.generate_content(
                model=FLASH_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=FLASH_INSTRUCTION),
            )
        text = (response.text or "").strip()
    except Exception as e:
        logger.error("Prism AI request failed: %s", e)
        return _fallback_guidance(screen_state, user_prompt)
    return text or _fallback_guidance(screen_state, user_prompt)

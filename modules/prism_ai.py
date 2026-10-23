"""Prism A.I Operational Assistant & Dedicated USBC Rule Arbitrator."""

import os
import streamlit as st
from google import genai
from google.genai import types

PRIMARY_MODEL = "gemini-3.8-flash"

USBC_SYSTEM_PROMPT = """
You are the official USBC Rules & Operational Assistant for the Cecil Harford USBC (CHUSBC) 
Tournament Control Center (PTCC). You assist Tournament Directors with:
1. USBC Playing Rules:
   - Rule 8 (Dead Ball situations, illegal pinfall, out of range pins)
   - Rule 9 (Bowler delivering ball on the wrong lane or out of turn)
   - Rule 10 (Foul detection, foul light failures, deliberate fouls)
   - Rule 18 (Bowling ball surface alterations: no cleaning/sanding once competition begins)
   - Rule 400 (Youth SMART scholarship compliance: no cash prizes to youth under any circumstances)
2. Lane movements, handicap calculations (standard 90% of 220), and side pot balancing.

Keep your answers authoritative, concise, objective, and directly grounded in the official USBC Playing Rules.
"""


def _get_gemini_client() -> genai.Client | None:
    """Retrieve Gemini client using google-genai with a strict 15s timeout."""
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=15_000,
                retry_options=types.HttpRetryOptions(
                    attempts=2,
                    initial_delay=1.0,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )
    except Exception:
        return None


def _local_fallback_guidance(view_name: str, user_prompt: str | None = None) -> str:
    """Instant rulebook guidance fallback if the Gemini API is unreachable or rate-limited."""
    if user_prompt:
        return (
            "⚠️ **USBC Quick Rule Reference:**\n"
            "• **Rule 8 (Dead Ball):** Call dead ball immediately and re-rack if a pin is missing or displaced prior to delivery.\n"
            "• **Rule 9 (Wrong Lane):** Count pinfall as dead ball; bowler must re-bowl on the correct lane.\n"
            "• **Rule 18 (Surface Alteration):** Modifying ball surface after squad competition begins is strictly prohibited.\n"
            "• **Rule 400 (Youth/SMART):** Cash or merchandise awards are prohibited; prize equity routes to SMART escrow."
        )
    return (
        f"• **Active Screen ({view_name}):** Verify entering averages and 90% of 220 handicaps before squad start.\n"
        "• **Rule 400 Compliance:** Ensure youth bowlers have the Youth/SMART toggle enabled prior to closing the gate.\n"
        "• **Floor Verification:** Check lane pairs and Floor Scorer PIN (`6199`) before releasing bowlers to the approach."
    )


def get_prism_ai_guidance(view_state: dict, user_prompt: str | None = None) -> str:
    """Generate operational guidance or arbitrate USBC tournament rules."""
    view_name = view_state.get("view", "Tournament Desk")

    if not user_prompt:
        context_prompt = (
            f"The tournament director is currently viewing the '{view_name}' screen in the PTCC. "
            "Provide 2-3 brief, helpful operational tips or reminders relevant to this stage of tournament desk operations. "
            "Keep it strictly under 60 words and formatted cleanly with bullet points."
        )
    else:
        context_prompt = (
            f"Context: Tournament Director is on the '{view_name}' screen.\n"
            f"Question / Dispute: {user_prompt}\n\n"
            "Cite the applicable USBC rule number (e.g. Rule 8, Rule 9, Rule 18, Rule 400) and provide the definitive rulebook ruling."
        )

    client = _get_gemini_client()
    if not client:
        return _local_fallback_guidance(view_name, user_prompt)

    # Sanitize model selection against stale cloud secrets
    configured_model = st.secrets.get("GEMINI_MODEL", PRIMARY_MODEL)
    if any(k in configured_model.lower() for k in ("2.5", "lite", "1.5")):
        model_name = PRIMARY_MODEL
    else:
        model_name = configured_model

    try:
        config = types.GenerateContentConfig(
            system_instruction=USBC_SYSTEM_PROMPT,
            temperature=0.2,
        )
        response = client.models.generate_content(
            model=model_name,
            contents=context_prompt,
            config=config,
        )
        if response and response.text:
            return response.text.strip()
        return _local_fallback_guidance(view_name, user_prompt)
    except Exception:
        # Fall back gracefully without printing ugly raw 404 JSON to the sidebar
        return _local_fallback_guidance(view_name, user_prompt)
"""Prism A.I Operational Assistant & Dedicated USBC Rule Arbitrator."""

import os
import streamlit as st

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


def _get_gemini_client():
    """Retrieve Gemini client using api key from st.secrets or environment variable."""
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except ImportError:
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            return legacy_genai
        except ImportError:
            return None


def get_prism_ai_guidance(view_state: dict, user_prompt: str | None = None) -> str:
    """Generate operational guidance or arbitrate USBC tournament rules."""
    view_name = view_state.get("view", "Tournament Desk")

    if not user_prompt:
        context_prompt = f"""
The tournament director is currently viewing the '{view_name}' screen in the PTCC.
Provide 2-3 brief, helpful operational tips or reminders relevant to this stage of tournament desk operations.
Keep it strictly under 60 words and formatted cleanly with bullet points.
"""
    else:
        context_prompt = f"""
Context: Tournament Director is on the '{view_name}' screen.
Question / Dispute: {user_prompt}

Cite the applicable USBC rule number (e.g. Rule 8, Rule 9, Rule 18, Rule 400) and provide the definitive rulebook ruling.
"""

    client = _get_gemini_client()
    if not client:
        if user_prompt:
            return (
                "⚠️ USBC Rules Engine is offline (GEMINI_API_KEY not configured). "
                "For common rulings: Rule 8 covers dead ball pinfall, Rule 9 covers wrong lane deliveries, "
                "Rule 18 forbids ball surface adjustments during squad play, and Rule 400 governs SMART scholarships."
            )
        return (
            f"• Ensure all entering averages and handicaps are audited for the {view_name} screen.\n"
            f"• Verify lane pairs and bowler lineup orders before competition begins."
        )

    try:
        # Check if using the official google-genai client
        if hasattr(client, "models"):
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=context_prompt,
                config={"system_instruction": USBC_SYSTEM_PROMPT},
            )
            return response.text.strip()
        else:
            # Fallback to legacy google.generativeai
            model = client.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=USBC_SYSTEM_PROMPT,
            )
            response = model.generate_content(context_prompt)
            return response.text.strip()
    except Exception as exc:
        return f"Operational guidance unavailable: {str(exc)}"
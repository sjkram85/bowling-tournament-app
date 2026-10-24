"""Prism A.I Operational Assistant & Dedicated USBC Rule Arbitrator."""

from modules import ai_provider
from modules.ai_provider import AIError

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


def _local_fallback_guidance(view_name: str, user_prompt: str | None = None) -> str:
    """Instant rulebook guidance fallback if the Gemini API is unreachable or rate-limited."""
    if user_prompt:
        return (
            "USBC Quick Rule Reference (built-in, not an A.I. answer; confirm in the rulebook):\n"
            "• Rule 8 (Dead Ball): Call dead ball immediately and re-rack if a pin is missing or displaced prior to delivery.\n"
            "• Rule 9 (Wrong Lane): Count pinfall as dead ball; bowler must re-bowl on the correct lane.\n"
            "• Rule 18 (Surface Alteration): Modifying ball surface after squad competition begins is strictly prohibited.\n"
            "• Rule 400 (Youth/SMART): Cash or merchandise awards are prohibited; prize equity routes to SMART escrow."
        )
    return (
        f"• Active Screen ({view_name}): Verify entering averages and 90% of 220 handicaps before squad start.\n"
        "• Rule 400 Compliance: Ensure youth bowlers have the Youth/SMART toggle enabled prior to closing the gate.\n"
        "• Floor Verification: Check lane pairs and Floor Scorer PIN (6199) before releasing bowlers to the approach."
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

    purpose = "rules" if view_name == "USBC Rules Engine" else "general"
    try:
        return ai_provider.ask_text(context_prompt, system=USBC_SYSTEM_PROMPT, purpose=purpose)
    except AIError as exc:
        return f"A.I. unavailable: {exc}\n\n" + _local_fallback_guidance(view_name, user_prompt)

"""Prism A.I.: everyday screen help and USBC rule answers.

Two modes:
1. Everyday help: a short summary of the current screen (counts and warnings) goes to the
   general model, which answers in plain English for tournament directors.
2. Rule questions: we look up the best-matching sections of the 2026-27 USBC Playing Rules
   (modules/rulebook.py) and send only those to the Grok rules model, which must answer from them
   and quote the rule numbers. If no section matches, we say so instead of guessing.
"""

from modules import ai_provider, rulebook
from modules.ai_provider import AIError
from modules.screen_context import context_to_text

PLAIN_STYLE = (
    "Write for an older, non-technical tournament director. "
    "Start with one short sentence that answers or sums up. Then give 1 or 2 next steps, each on its own line starting with '• '. "
    "Use short sentences and everyday words. No jargon, no code, no markdown headings, under 70 words."
)

EVERYDAY_SYSTEM = (
    "You are Prism, the helper inside the CHUSBC Prism Tournament Control Center. "
    "You help tournament directors run the desk: check-in, lanes, scores and payouts. "
    "Base your answer only on the screen summary you are given. If the summary shows no problems, say things look good "
    "and name the next normal step. Do not quote USBC rule numbers; for rule questions, point them to the Rule Arbitrator. "
    + PLAIN_STYLE
)

RULES_SYSTEM = (
    "You answer USBC rule questions for a tournament director, using ONLY the rulebook sections provided. "
    "Quote the rule number(s) you rely on, e.g. '(Rule 8)'. Do not use outside knowledge and do not invent rule numbers. "
    "If the sections do not answer the question, say: 'I couldn't find this in the rulebook sections I checked. "
    "Please check with the tournament manager.' "
    + PLAIN_STYLE
)

NO_MATCH_MESSAGE = (
    "I couldn't find a rule in the USBC Playing Rules that matches that question.\n"
    "• Try different words (for example: foul line, dead ball, wrong lane).\n"
    "• For anything unclear, check with the tournament manager."
)


def _local_fallback_guidance(view_name: str, user_prompt: str | None = None) -> str:
    """Built-in tips used when A.I. is off or unreachable. Contains no rule numbers on purpose."""
    if user_prompt:
        return (
            "Built-in tip (not an A.I. answer):\n"
            "• Look up the situation in the USBC Playing Rules, or use the Rule Arbitrator.\n"
            "• If it's still unclear, check with the tournament manager before play continues."
        )
    return (
        f"Built-in tips for {view_name} (not an A.I. answer):\n"
        "• Make sure every bowler is checked in, paid and has an entering average.\n"
        "• Check lane assignments and change the floor scorer PIN from the default before play starts."
    )


def _fallback_from_context(view_state: dict) -> str:
    warns = (view_state.get("screen_context") or {}).get("warnings") or []
    if not warns:
        return _local_fallback_guidance(view_state.get("view", "this screen"))
    return "Built-in check (not an A.I. answer):\n" + "\n".join(f"• {w}" for w in warns[:3])


def build_everyday_prompt(view_state: dict, user_prompt: str | None = None) -> str:
    ctx = view_state.get("screen_context") or {"page": view_state.get("view", "Tournament Desk")}
    prompt = "Screen summary:\n" + context_to_text(ctx) + "\n\n"
    if user_prompt:
        prompt += f"The director asks: {user_prompt.strip()[:500]}"
    else:
        prompt += "What should the director know or do next on this screen?"
    return prompt


def get_prism_ai_guidance(view_state: dict, user_prompt: str | None = None) -> str:
    """Everyday help for the current screen (no rulebook)."""
    if view_state.get("view") == "USBC Rules Engine" and user_prompt:
        return answer_rule_question(user_prompt)
    try:
        return ai_provider.ask_text(build_everyday_prompt(view_state, user_prompt), system=EVERYDAY_SYSTEM, purpose="general")
    except AIError as exc:
        fallback = _local_fallback_guidance(view_state.get("view", "this screen"), user_prompt) if user_prompt else _fallback_from_context(view_state)
        return f"A.I. unavailable: {exc}\n\n" + fallback


def build_rules_prompt(question: str, sections: list[dict]) -> str:
    return (
        "Rulebook sections (USBC Playing Rules 2026-27):\n\n"
        + rulebook.format_for_prompt(sections)
        + f"\n\nQuestion: {question.strip()[:500]}"
    )


def answer_rule_question(question: str) -> str:
    """Answer a rule question from the matching rulebook sections only."""
    sections = rulebook.search(question, k=3)
    if not sections:
        return NO_MATCH_MESSAGE
    cited = ", ".join(dict.fromkeys(f"Rule {s['rule']} ({s['title']})" for s in sections))
    try:
        answer = ai_provider.ask_text(build_rules_prompt(question, sections), system=RULES_SYSTEM, purpose="rules")
        return f"{answer}\n\nSections checked: {cited}"
    except AIError as exc:
        return (
            f"A.I. unavailable: {exc}\n\n"
            f"These rulebook sections look related: {cited}.\n"
            "• Read them in the USBC Playing Rules.\n"
            "• If it's still unclear, check with the tournament manager."
        )

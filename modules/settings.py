"""Safe access to app settings (Streamlit secrets or environment variables).

Never crashes when .streamlit/secrets.toml is missing.
"""

import os

import streamlit as st

AI_OFF_MESSAGE = (
    "Prism A.I. is turned off because no Gemini key has been set up. "
    "Everything else works normally. To turn A.I. on, add GEMINI_API_KEY to the app's secrets."
)


def get_secret(key: str, default=None):
    """Return a setting from the environment or Streamlit secrets, or default if not set."""
    value = os.environ.get(key)
    if value:
        return value
    try:
        return st.secrets.get(key, default)
    except Exception:  # no secrets.toml, or it can't be read
        return default


def ai_available() -> bool:
    """True when a Gemini API key is configured."""
    return bool(get_secret("GEMINI_API_KEY"))


DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_RULES_MODEL = "gemini-4-argon"
# Used once, automatically, when the main model is overloaded, too slow, or over its limit.
DEFAULT_BACKUP_MODEL = "gemini-3.6-flash"


def model_name(purpose: str = "general") -> str:
    """The one place the A.I. model is chosen. 'rules' is the USBC Rule Arbitrator."""
    if purpose == "backup":
        return str(get_secret("GEMINI_BACKUP_MODEL") or DEFAULT_BACKUP_MODEL).strip()
    if purpose == "rules":
        return str(get_secret("GEMINI_RULES_MODEL") or DEFAULT_RULES_MODEL).strip()
    return str(get_secret("GEMINI_MODEL") or DEFAULT_MODEL).strip()

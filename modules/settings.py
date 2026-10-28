"""Safe access to app settings (Streamlit secrets or environment variables).

Never crashes when .streamlit/secrets.toml is missing.
"""

import os

import streamlit as st

AI_OFF_MESSAGE = (
    "Prism A.I. is turned off because no Grok key has been set up. "
    "Everything else works normally. To turn A.I. on, add XAI_API_KEY to the app's secrets."
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
    """True when an xAI API key is configured."""
    return bool(get_secret("XAI_API_KEY"))


# Current Grok model for Co-Pilot and the Rule Arbitrator (xAI docs, Oct 2026).
# grok-4.7 accepts text and images and is the flagship chat model.
GROK_MODEL = "grok-4.7"
DEFAULT_MODEL = GROK_MODEL
DEFAULT_RULES_MODEL = GROK_MODEL
# Previous flagship, used once when the main model is busy, slow, or over its limit.
DEFAULT_BACKUP_MODEL = "grok-4.6"


def model_name(purpose: str = "general") -> str:
    """The one place the A.I. model is chosen. Co-Pilot and the Rule Arbitrator use Grok."""
    if purpose == "backup":
        return str(get_secret("XAI_BACKUP_MODEL") or DEFAULT_BACKUP_MODEL).strip()
    if purpose == "rules":
        return str(get_secret("XAI_RULES_MODEL") or DEFAULT_RULES_MODEL).strip()
    return str(get_secret("XAI_MODEL") or DEFAULT_MODEL).strip()

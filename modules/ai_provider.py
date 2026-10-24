"""The single place Prism talks to an A.I. service (currently Google Gemini).

Every A.I. feature calls ask_text(), extract_json() or read_image(). To switch
providers later, only this file needs to change.

There is no silent fallback: if the key is missing, the model is retired, or
Google refuses the request, AIError is raised with a plain-English message.
"""

from __future__ import annotations

import json
from datetime import datetime

from modules.settings import AI_OFF_MESSAGE, DEFAULT_MODEL, DEFAULT_RULES_MODEL, get_secret, model_name

TIMEOUT_MS = 15_000

# Model names Google has shut down or restricted (Gemini API deprecations page, Oct 2026).
RETIRED_PREFIXES = (
    "gemini-1.0", "gemini-1.5", "gemini-pro", "gemini-2.0", "gemini-2.5",
    "gemini-3-pro-preview", "gemini-3.1-flash-lite-preview", "gemini-exp",
)

# Last call result, shown in the About box.
LAST_STATUS: dict = {"model": None, "ok": None, "message": "No A.I. requests yet.", "at": None}


class AIError(Exception):
    """An A.I. problem described in plain English, safe to show on screen."""


def is_retired(name: str) -> bool:
    n = (name or "").lower().strip()
    return n.startswith(RETIRED_PREFIXES)


def retired_message(name: str, setting: str = "GEMINI_MODEL") -> str:
    return (
        f"Prism A.I. is set to an old model ({name}) that Google has retired. "
        f"Change {setting} to {DEFAULT_MODEL if setting == 'GEMINI_MODEL' else DEFAULT_RULES_MODEL}."
    )


def _record(model: str, ok: bool, message: str) -> None:
    LAST_STATUS.update(model=model, ok=ok, message=message, at=datetime.now().strftime("%b %d, %I:%M %p"))


def _client():
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise AIError(AI_OFF_MESSAGE)
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise AIError("Prism A.I. can't start because the Google A.I. package isn't installed.")
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(
                attempts=1, initial_delay=1.0, http_status_codes=[408, 429, 500, 502, 503, 504]
            ),
        ),
    )


def _friendly_error(exc: Exception, model: str) -> str:
    text = str(exc).lower()
    if "404" in text or "not found" in text or "not supported" in text or "no longer available" in text:
        return (f"Google says the model '{model}' isn't available to this account. "
                f"Change GEMINI_MODEL to {DEFAULT_MODEL}.")
    if "401" in text or "403" in text or "api key" in text or "permission" in text:
        return "Google refused the Gemini key. Check that GEMINI_API_KEY is correct and active."
    if "503" in text or "unavailable" in text or "high demand" in text or "overloaded" in text:
        return "Google's A.I. is very busy right now. Please try again in a minute."
    if "429" in text or "quota" in text or "resource_exhausted" in text:
        return "Prism A.I. is temporarily over its usage limit. Wait a minute and try again."
    if "timeout" in text or "timed out" in text or "deadline" in text:
        return "Prism A.I. took too long to answer (over 15 seconds). Please try again."
    return "Prism A.I. couldn't complete the request. Please try again in a moment."


def _is_busy(exc: Exception) -> bool:
    """Overloaded, too slow, or over the usage limit: worth one try on the backup model."""
    text = str(exc).lower()
    return any(k in text for k in ("503", "504", "429", "unavailable", "deadline", "timeout", "timed out",
                                   "resource_exhausted", "quota", "high demand", "overloaded"))


def _generate(contents, purpose: str, system: str | None = None, want_json: bool = False,
              temperature: float = 0.2, client=None) -> str:
    model = model_name(purpose)
    setting = "GEMINI_RULES_MODEL" if purpose == "rules" else "GEMINI_MODEL"
    if is_retired(model):
        msg = retired_message(model, setting)
        _record(model, False, msg)
        raise AIError(msg)
    try:
        client = client or _client()
    except AIError as exc:
        _record(model, False, str(exc))
        raise
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if want_json else None,
    )
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
        text = (getattr(response, "text", None) or "").strip()
    except Exception as exc:
        msg = _friendly_error(exc, model)
        backup = model_name("backup")
        if _is_busy(exc) and backup and backup != model and not is_retired(backup):
            try:
                response = client.models.generate_content(model=backup, contents=contents, config=config)
                text = (getattr(response, "text", None) or "").strip()
            except Exception as exc2:
                msg = _friendly_error(exc2, backup)
                _record(backup, False, msg)
                raise AIError(msg) from exc2
            if text:
                _record(backup, True, f"Last request succeeded using the backup model ({model} was busy or over its limit).")
                return text
        _record(model, False, msg)
        raise AIError(msg) from exc
    if not text:
        msg = "Prism A.I. returned an empty answer. Please try again."
        _record(model, False, msg)
        raise AIError(msg)
    _record(model, True, "Last request succeeded.")
    return text


def _parse_json(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        raise AIError("Prism A.I. sent back data Prism couldn't read. Please try again.")


def ask_text(prompt: str, system: str | None = None, purpose: str = "general", client=None) -> str:
    """Ask a question; returns plain text."""
    return _generate(prompt, purpose, system=system, client=client)


def extract_json(prompt: str, data: str | None = None, file_bytes: bytes | None = None,
                 mime_type: str | None = None, purpose: str = "general", client=None):
    """Extract structured data (JSON) from text or a document (PDF/image)."""
    contents = [prompt]
    if data:
        contents.append(data)
    if file_bytes is not None:
        from google.genai import types
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type or "application/octet-stream"))
    return _parse_json(_generate(contents, purpose, want_json=True, temperature=0.1, client=client))


def read_image(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg", client=None):
    """Read a photo and return JSON."""
    return extract_json(prompt, file_bytes=image_bytes, mime_type=mime_type, client=client)


def status_summary() -> dict:
    """Model names and last-call status for the About box."""
    return {
        "model": model_name("general"),
        "rules_model": model_name("rules"),
        "key_set": bool(get_secret("GEMINI_API_KEY")),
        **{f"last_{k}": v for k, v in LAST_STATUS.items()},
    }

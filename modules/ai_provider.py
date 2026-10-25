"""The single place Prism talks to an A.I. service (currently Google Gemini).

Every A.I. feature calls ask_text(), extract_json() or read_image(). To switch
providers later, only this file needs to change.

There is no silent fallback: if the key is missing, the model is retired, or
Google refuses the request, AIError is raised with a plain-English message.

Busy signals, timeouts, and other API errors are retried a couple of times.
A listener (see push_retry_listener) can show the gutter-ball / approach
feedback while those retries run. A bad key or a retired model is not retried.
"""

from __future__ import annotations

import contextvars
import json
import time
from datetime import datetime

from modules.settings import AI_OFF_MESSAGE, DEFAULT_MODEL, DEFAULT_RULES_MODEL, get_secret, model_name

TIMEOUT_MS = 15_000

# Extra shots after the first one fails because Gemini is busy, slow, or errors.
# Each retry holds the gutter ball, then "getting back on the approach", then calls again.
EXTRA_RETRIES = 2
# (seconds the gutter stays up, seconds the approach stays up) before that retry.
RETRY_BEATS = ((0.75, 0.55), (1.25, 0.7))
APPROACH_STATUS = "Getting back on the approach..."

# Model names Google has shut down or restricted (Gemini API deprecations page, Oct 2026).
RETIRED_PREFIXES = (
    "gemini-1.0", "gemini-1.5", "gemini-pro", "gemini-2.0", "gemini-2.5",
    "gemini-3-pro-preview", "gemini-3.1-flash-lite-preview", "gemini-exp",
)

# Last call result, shown in the About box.
LAST_STATUS: dict = {"model": None, "ok": None, "message": "No A.I. requests yet.", "at": None}

# UI hook for the gutter / approach animation. None when nothing is listening.
_retry_listener: contextvars.ContextVar = contextvars.ContextVar("prism_ai_retry_listener", default=None)

_TRANSIENT = {
    "busy": ("Google's A.I. is very busy right now.", "Please try again in a minute."),
    "limit": ("Prism A.I. is temporarily over its usage limit.", "Wait a minute and try again."),
    "timeout": ("Prism A.I. took too long to answer (over 15 seconds).", "Please try again."),
    "api": ("Prism A.I. couldn't complete the request.", "Please try again in a moment."),
}


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


def push_retry_listener(listener):
    """Call listener(phase, message) on gutter, approach, and give_up. Returns a reset token."""
    return _retry_listener.set(listener)


def pop_retry_listener(token) -> None:
    _retry_listener.reset(token)


def _notify(phase: str, message: str) -> None:
    listener = _retry_listener.get()
    if listener is None:
        return
    try:
        listener(phase, message)
    except Exception:
        return


def _pause(seconds: float) -> None:
    time.sleep(seconds)


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


def _error_kind(exc: Exception) -> str:
    """Classify a Gemini exception the same way the on-screen sentences do."""
    text = str(exc).lower()
    if any(k in text for k in ("404", "not found", "not supported", "no longer available")):
        return "model"
    if any(k in text for k in ("401", "403", "api key", "permission")):
        return "auth"
    if any(k in text for k in ("503", "unavailable", "high demand", "overloaded")):
        return "busy"
    if any(k in text for k in ("429", "quota", "resource_exhausted")):
        return "limit"
    if any(k in text for k in ("timeout", "timed out", "deadline")):
        return "timeout"
    return "api"


def _is_retryable(kind: str) -> bool:
    return kind in _TRANSIENT


def _is_busy(exc: Exception) -> bool:
    """Overloaded, too slow, or over the usage limit: worth one try on the backup model."""
    text = str(exc).lower()
    return any(k in text for k in ("503", "504", "429", "unavailable", "deadline", "timeout", "timed out",
                                   "resource_exhausted", "quota", "high demand", "overloaded"))


def _friendly_message(kind: str, model: str, *, exhausted: bool = False) -> str:
    if kind == "model":
        return (
            f"Google says the model '{model}' isn't available to this account. "
            f"Change GEMINI_MODEL to {DEFAULT_MODEL}."
        )
    if kind == "auth":
        return "Google refused the Gemini key. Check that GEMINI_API_KEY is correct and active."
    if kind == "empty":
        return "Prism A.I. returned an empty answer. Please try again."
    base, ending = _TRANSIENT.get(kind, _TRANSIENT["api"])
    if exhausted:
        return (
            f"Gutter ball. {base} Prism got back on the approach and tried again, "
            f"but the ball still went in the gutter. {ending}"
        )
    return f"{base} {ending}"


def _raise(kind: str, model: str, exc: Exception | None, *, exhausted: bool = False) -> None:
    msg = _friendly_message(kind, model, exhausted=exhausted)
    if exhausted:
        _notify("give_up", msg)
    _record(model, False, msg)
    if exc is not None:
        raise AIError(msg) from exc
    raise AIError(msg)


def _call_model(client, model: str, contents, config) -> str:
    response = client.models.generate_content(model=model, contents=contents, config=config)
    return (getattr(response, "text", None) or "").strip()


def _attempt(client, model: str, backup: str | None, contents, config):
    """One shot on the main model, then the backup model if that shot was busy or slow.

    Returns (text, kind, model_for_the_message, exception). text is empty on failure.
    """
    try:
        text = _call_model(client, model, contents, config)
    except Exception as exc:
        if not (backup and _is_busy(exc)):
            return "", _error_kind(exc), model, exc
        try:
            text = _call_model(client, backup, contents, config)
        except Exception as exc2:
            return "", _error_kind(exc2), backup, exc2
        if text:
            return text, None, backup, None
        # Backup came back empty. Keep the original busy/timeout reason, as before.
        return "", _error_kind(exc), model, exc
    if not text:
        return "", "empty", model, None
    return text, None, model, None


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
    backup_name = model_name("backup")
    backup = backup_name if backup_name and backup_name != model and not is_retired(backup_name) else None

    last_kind, last_model, last_exc = "api", model, None
    for attempt in range(EXTRA_RETRIES + 1):
        if attempt:
            gutter_beat, approach_beat = RETRY_BEATS[min(attempt - 1, len(RETRY_BEATS) - 1)]
            _notify("gutter", _friendly_message(last_kind, last_model))
            _pause(gutter_beat)
            _notify("approach", APPROACH_STATUS)
            _pause(approach_beat)
        text, kind, used, exc = _attempt(client, model, backup, contents, config)
        if text:
            if used != model:
                _record(used, True, f"Last request succeeded using the backup model ({model} was busy or over its limit).")
            elif attempt:
                _record(used, True, "Last request succeeded after getting back on the approach.")
            else:
                _record(used, True, "Last request succeeded.")
            return text
        last_kind, last_model, last_exc = kind, used, exc
        if not _is_retryable(kind):
            _raise(kind, used, exc)
    _raise(last_kind, last_model, last_exc, exhausted=True)


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

"""The single place Prism talks to an A.I. service (xAI Grok).

Every A.I. feature calls ask_text(), extract_json() or read_image(). To switch
providers later, only this file needs to change.

There is no silent fallback: if the key is missing, the model is retired, or
xAI refuses the request, AIError is raised with a plain-English message.

Busy signals, timeouts, and other API errors are retried a couple of times.
A listener (see push_retry_listener) can show the gutter-ball / approach
feedback while those retries run. A bad key or a retired model is not retried.

Calls use the OpenAI SDK against https://api.x.ai/v1 (Responses API). Reasoning
stays on "low" so a normal desk question can finish inside the 15 second limit.
"""

from __future__ import annotations

import base64
import contextvars
import io
import json
import time
from datetime import datetime

from modules.settings import (
    AI_OFF_MESSAGE,
    DEFAULT_BACKUP_MODEL,
    DEFAULT_MODEL,
    DEFAULT_RULES_MODEL,
    get_secret,
    model_name,
)

TIMEOUT_MS = 15_000
XAI_BASE_URL = "https://api.x.ai/v1"

# Extra shots after the first one fails because Grok is busy, slow, or errors.
# Each retry holds the gutter ball, then "getting back on the approach", then calls again.
EXTRA_RETRIES = 2
# (seconds the gutter stays up, seconds the approach stays up) before that retry.
RETRY_BEATS = ((0.75, 0.55), (1.25, 0.7))
APPROACH_STATUS = "Getting back on the approach..."

# Model names xAI has retired (May 15, 2026) plus leftover Gemini ids.
# Current ids such as grok-4.7, grok-4.6, grok-4.5, grok-4.3, and grok-4.20 stay allowed.
RETIRED_PREFIXES = (
    "gemini",
    "grok-2",
    "grok-3",
    "grok-beta",
    "grok-vision",
    "grok-4-0709",
    "grok-4-fast",
    "grok-4-1-fast",
    "grok-code-fast",
)

# Last call result, shown in the About box.
LAST_STATUS: dict = {"model": None, "ok": None, "message": "No A.I. requests yet.", "at": None}

# UI hook for the gutter / approach animation. None when nothing is listening.
_retry_listener: contextvars.ContextVar = contextvars.ContextVar("prism_ai_retry_listener", default=None)

_TRANSIENT = {
    "busy": ("xAI's A.I. is very busy right now.", "Please try again in a minute."),
    "limit": ("Prism A.I. is temporarily over its usage limit.", "Wait a minute and try again."),
    "timeout": ("Prism A.I. took too long to answer (over 15 seconds).", "Please try again."),
    "api": ("Prism A.I. couldn't complete the request.", "Please try again in a moment."),
}

_SETTING_DEFAULT = {
    "XAI_MODEL": DEFAULT_MODEL,
    "XAI_RULES_MODEL": DEFAULT_RULES_MODEL,
    "XAI_BACKUP_MODEL": DEFAULT_BACKUP_MODEL,
}


class AIError(Exception):
    """An A.I. problem described in plain English, safe to show on screen."""


def is_retired(name: str) -> bool:
    n = (name or "").lower().strip()
    return n.startswith(RETIRED_PREFIXES)


def retired_message(name: str, setting: str = "XAI_MODEL") -> str:
    fallback = _SETTING_DEFAULT.get(setting, DEFAULT_MODEL)
    return (
        f"Prism A.I. is set to an old model ({name}) that xAI has retired. "
        f"Change {setting} to {fallback}."
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
    api_key = get_secret("XAI_API_KEY")
    if not api_key:
        raise AIError(AI_OFF_MESSAGE)
    try:
        from openai import OpenAI
    except ImportError:
        raise AIError("Prism A.I. can't start because the xAI client package isn't installed.")
    return OpenAI(
        api_key=api_key,
        base_url=XAI_BASE_URL,
        timeout=TIMEOUT_MS / 1000,
        max_retries=0,
    )


def _status_code(exc: Exception):
    return getattr(exc, "status_code", None)


def _error_kind(exc: Exception) -> str:
    """Classify an xAI exception the same way the on-screen sentences do."""
    status = _status_code(exc)
    if status == 404:
        return "model"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "limit"
    if status in (408, 504) or "timeout" in type(exc).__name__.lower():
        return "timeout"
    if status == 503:
        return "busy"
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
    status = _status_code(exc)
    if status in (408, 429, 503, 504) or "timeout" in type(exc).__name__.lower():
        return True
    text = str(exc).lower()
    return any(k in text for k in ("503", "504", "429", "unavailable", "deadline", "timeout", "timed out",
                                   "resource_exhausted", "quota", "high demand", "overloaded"))


def _friendly_message(kind: str, model: str, *, exhausted: bool = False, setting: str = "XAI_MODEL") -> str:
    if kind == "model":
        fallback = _SETTING_DEFAULT.get(setting, DEFAULT_MODEL)
        return (
            f"xAI says the model '{model}' isn't available to this account. "
            f"Change {setting} to {fallback}."
        )
    if kind == "auth":
        return "xAI refused the Grok key. Check that XAI_API_KEY is correct and active."
    if kind == "empty":
        return "Prism A.I. returned an empty answer. Please try again."
    base, ending = _TRANSIENT.get(kind, _TRANSIENT["api"])
    if exhausted:
        return (
            f"Gutter ball. {base} Prism got back on the approach and tried again, "
            f"but the ball still went in the gutter. {ending}"
        )
    return f"{base} {ending}"


def _raise(kind: str, model: str, exc: Exception | None, *, exhausted: bool = False, setting: str = "XAI_MODEL") -> None:
    msg = _friendly_message(kind, model, exhausted=exhausted, setting=setting)
    if exhausted:
        _notify("give_up", msg)
    _record(model, False, msg)
    if exc is not None:
        raise AIError(msg) from exc
    raise AIError(msg)


def _messages(system: str | None, user_content) -> list:
    items = []
    if system:
        items.append({"role": "system", "content": system})
    items.append({"role": "user", "content": user_content})
    return items


def _with_file(messages: list, file_id: str) -> list:
    """Copy the conversation and attach an uploaded document to the user turn."""
    copied = [dict(item) for item in messages]
    last = copied[-1]
    content = last["content"]
    if isinstance(content, str):
        parts = [{"type": "input_text", "text": content}]
    else:
        parts = list(content)
    parts.append({"type": "input_file", "file_id": file_id})
    last["content"] = parts
    return copied


def _output_text(response) -> str:
    direct = getattr(response, "output_text", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks = []
    for item in getattr(response, "output", None) or []:
        content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
        for part in content or []:
            piece = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if piece:
                chunks.append(piece)
    return "\n".join(chunks).strip()


def _call_model(client, model: str, messages, *, want_json: bool, temperature: float) -> str:
    kwargs = {
        "model": model,
        "input": messages,
        "temperature": temperature,
        # grok-4.7 defaults to high reasoning, which often exceeds this desk's 15 second limit.
        "reasoning": {"effort": "low"},
        # One-shot desk calls (names, scores, photos). Do not keep them on xAI's server.
        "store": False,
    }
    if want_json:
        kwargs["text"] = {"format": {"type": "json_object"}}
    response = client.responses.create(**kwargs)
    return _output_text(response)


def _upload(client, filename: str, data: bytes, mime: str) -> str:
    created = client.files.create(
        file=(filename, io.BytesIO(data), mime),
        purpose="assistants",
    )
    file_id = getattr(created, "id", None)
    if not file_id and isinstance(created, dict):
        file_id = created.get("id")
    if not file_id:
        raise RuntimeError("xAI file upload returned no id")
    return file_id


def _delete_file(client, file_id: str) -> None:
    try:
        client.files.delete(file_id)
    except Exception:
        return


def _attempt(client, model: str, backup: str | None, messages, *, want_json: bool,
             temperature: float, attachment):
    """One shot on the main model, then the backup model if that shot was busy or slow.

    Returns (text, kind, model_for_the_message, exception). text is empty on failure.
    A document is uploaded for this shot and deleted before the function returns.
    """
    file_id = None
    try:
        if attachment:
            filename, data, mime = attachment
            file_id = _upload(client, filename, data, mime)
            messages = _with_file(messages, file_id)
        try:
            text = _call_model(client, model, messages, want_json=want_json, temperature=temperature)
        except Exception as exc:
            if not (backup and _is_busy(exc)):
                return "", _error_kind(exc), model, exc
            try:
                text = _call_model(client, backup, messages, want_json=want_json, temperature=temperature)
            except Exception as exc2:
                return "", _error_kind(exc2), backup, exc2
            if text:
                return text, None, backup, None
            # Backup came back empty. Keep the original busy/timeout reason, as before.
            return "", _error_kind(exc), model, exc
        if not text:
            return "", "empty", model, None
        return text, None, model, None
    except Exception as exc:
        return "", _error_kind(exc), model, exc
    finally:
        if file_id:
            _delete_file(client, file_id)


def _generate(user_content, purpose: str, system: str | None = None, want_json: bool = False,
              temperature: float = 0.2, client=None, attachment=None) -> str:
    model = model_name(purpose)
    setting = "XAI_RULES_MODEL" if purpose == "rules" else "XAI_MODEL"
    if is_retired(model):
        msg = retired_message(model, setting)
        _record(model, False, msg)
        raise AIError(msg)
    if want_json:
        note = "Respond with one JSON value and no other text."
        system = f"{system}\n{note}" if system else note
    try:
        client = client or _client()
    except AIError as exc:
        _record(model, False, str(exc))
        raise
    messages = _messages(system, user_content)
    backup_name = model_name("backup")
    backup = backup_name if backup_name and backup_name != model and not is_retired(backup_name) else None

    last_kind, last_model, last_exc = "api", model, None
    for attempt in range(EXTRA_RETRIES + 1):
        if attempt:
            gutter_beat, approach_beat = RETRY_BEATS[min(attempt - 1, len(RETRY_BEATS) - 1)]
            _notify("gutter", _friendly_message(last_kind, last_model, setting=setting))
            _pause(gutter_beat)
            _notify("approach", APPROACH_STATUS)
            _pause(approach_beat)
        text, kind, used, exc = _attempt(
            client, model, backup, messages,
            want_json=want_json, temperature=temperature, attachment=attachment,
        )
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
            _raise(kind, used, exc, setting=setting)
    _raise(last_kind, last_model, last_exc, exhausted=True, setting=setting)


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


def _document_name(mime: str) -> str:
    if mime == "application/pdf":
        return "roster.pdf"
    if mime.startswith("text/"):
        return "roster.txt"
    return "document.bin"


def extract_json(prompt: str, data: str | None = None, file_bytes: bytes | None = None,
                 mime_type: str | None = None, purpose: str = "general", client=None):
    """Extract structured data (JSON) from text or a document (PDF/image)."""
    text = prompt if not data else f"{prompt}\n\n{data}"
    attachment = None
    user_content = text
    if file_bytes is not None:
        mime = mime_type or "application/octet-stream"
        if mime.startswith("image/"):
            encoded = base64.b64encode(file_bytes).decode("ascii")
            user_content = [
                {"type": "input_text", "text": text},
                {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"},
            ]
        else:
            attachment = (_document_name(mime), file_bytes, mime)
    return _parse_json(_generate(
        user_content, purpose, want_json=True, temperature=0.1, client=client, attachment=attachment,
    ))


def read_image(prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg", client=None):
    """Read a photo and return JSON."""
    return extract_json(prompt, file_bytes=image_bytes, mime_type=mime_type, client=client)


def status_summary() -> dict:
    """Model names and last-call status for the About box."""
    return {
        "model": model_name("general"),
        "rules_model": model_name("rules"),
        "key_set": bool(get_secret("XAI_API_KEY")),
        **{f"last_{k}": v for k, v in LAST_STATUS.items()},
    }

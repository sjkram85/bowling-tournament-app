import re

import pytest
from modules import ai_provider as ap, prism_ai, ocr_engine, ai_roster
from modules.settings import ai_available


class FakeResponses:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return type("R", (), {"output_text": self.text})()


class FakeClient:
    def __init__(self, **kw):
        self.responses = FakeResponses(**kw)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in (
        "XAI_API_KEY", "XAI_MODEL", "XAI_RULES_MODEL", "XAI_BACKUP_MODEL",
        "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_RULES_MODEL", "GEMINI_BACKUP_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


def use(env, client):
    env.setenv("XAI_API_KEY", "test")
    env.setattr(ap, "_client", lambda: client)


def test_defaults():
    assert ap.model_name() == "grok-4.7"
    assert ap.model_name("rules") == "grok-4.7"
    assert ap.model_name("backup") == "grok-4.6"
    assert ap.is_retired("grok-3")
    assert ap.is_retired("grok-4-0709")
    assert ap.is_retired("gemini-2.0-flash")
    assert not ap.is_retired("grok-4.7")
    assert not ap.is_retired("grok-4.6")
    assert not ap.is_retired("grok-4.5")
    assert not ap.is_retired("grok-4.3")


def test_no_key_plain_message():
    with pytest.raises(ap.AIError, match="turned off"):
        ap.ask_text("hi")


def test_gemini_secrets_are_ignored(env):
    env.setenv("GEMINI_API_KEY", "still-here")
    env.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    assert ap.model_name() == "grok-4.7"
    assert ai_available() is False
    with pytest.raises(ap.AIError, match="XAI_API_KEY"):
        ap.ask_text("hi")


def test_client_points_at_xai(env, monkeypatch):
    env.setenv("XAI_API_KEY", "test-key")
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    ap._client()
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://api.x.ai/v1"
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 15


@pytest.mark.parametrize("old", ["grok-3", "grok-4-0709", "grok-2-vision-1212", "gemini-2.5-flash", "gemini-3.8-flash"])
def test_retired_model_blocked_no_call(env, old):
    c = FakeClient(text="x"); use(env, c); env.setenv("XAI_MODEL", old)
    with pytest.raises(ap.AIError, match=rf"old model \({re.escape(old)}\).*Change XAI_MODEL to grok-4\.7"):
        ap.ask_text("hi")
    assert c.responses.calls == [] and ap.LAST_STATUS["ok"] is False


def test_current_model_not_blocked(env):
    c = FakeClient(text="ok"); use(env, c); env.setenv("XAI_MODEL", "grok-4.5")
    assert ap.ask_text("hi") == "ok" and c.responses.calls[0]["model"] == "grok-4.5"
    assert c.responses.calls[0]["reasoning"] == {"effort": "low"}
    assert c.responses.calls[0]["store"] is False


def test_rules_uses_rules_model(env):
    c = FakeClient(text="Rule answer"); use(env, c)
    out = prism_ai.get_prism_ai_guidance({"view": "USBC Rules Engine"}, user_prompt="wrong lane?")
    assert out.startswith("Rule answer") and "Sections checked: Rule 9" in out and c.responses.calls[0]["model"] == "grok-4.7"
    assert ap.LAST_STATUS["ok"] is True


def test_api_refusal_labeled_unavailable(env):
    c = FakeClient(exc=RuntimeError("404 NOT_FOUND models/grok-4.7")); use(env, c)
    out = prism_ai.get_prism_ai_guidance({"view": "Intake"}, user_prompt="q")
    assert out.startswith("A.I. unavailable: xAI says the model 'grok-4.7' isn't available")
    assert "not an A.I. answer" in out


def test_extract_json_and_roster(env):
    c = FakeClient(text='```json\n{"bowlers":[{"name":"Al","entering_avg":200}]}\n```'); use(env, c)
    recs = ai_roster.parse_roster_with_grok(b"name\nAl\n", "r.csv")
    assert recs == [{"name": "Al", "entering_avg": 200}]
    assert c.responses.calls[0]["text"]["format"]["type"] == "json_object"


def test_roster_error_no_silent_fallback(env):
    c = FakeClient(exc=RuntimeError("timed out")); use(env, c)
    with pytest.raises(ap.AIError, match="took too long"):
        ai_roster.parse_roster_with_grok(b"Lane 1: Al (Avg 200) - Paid", "r.txt")


def test_ocr(env):
    c = FakeClient(text='{"bowlers":[{"name":"Al","game_score":201}]}'); use(env, c)
    assert ocr_engine.extract_scores_from_overhead_photo(b"img")["extracted_data"][0]["game_score"] == 201
    image = c.responses.calls[0]["input"][-1]["content"]
    assert image[1]["type"] == "input_image"
    assert image[1]["image_url"].startswith("data:image/jpeg;base64,")
    env.setenv("XAI_MODEL", "grok-2-vision-1212")
    r = ocr_engine.extract_scores_from_overhead_photo(b"img")
    assert r["status"] == "error" and r["extracted_data"] == [] and "retired" in r["message"]


class FakeFiles:
    def __init__(self):
        self.created, self.deleted = [], []

    def create(self, *, file, purpose):
        self.created.append((file[0], file[2], purpose, file[1].read()))
        return type("F", (), {"id": "file-roster"})()

    def delete(self, file_id):
        self.deleted.append(file_id)


def test_pdf_is_uploaded_then_deleted(env):
    files = FakeFiles()
    c = FakeClient(text='{"bowlers":[{"name":"Al"}]}')
    c.files = files
    use(env, c)
    recs = ai_roster.parse_roster_with_grok(b"%PDF-1.4 roster", "squad.pdf")
    assert recs == [{"name": "Al"}]
    assert files.created[0][0] == "roster.pdf"
    assert files.created[0][1] == "application/pdf"
    assert files.created[0][2] == "assistants"
    assert files.created[0][3] == b"%PDF-1.4 roster"
    parts = c.responses.calls[0]["input"][-1]["content"]
    assert parts[-1] == {"type": "input_file", "file_id": "file-roster"}
    assert files.deleted == ["file-roster"]


def test_bad_key_message(env):
    c = FakeClient(exc=RuntimeError("403 PERMISSION_DENIED")); use(env, c)
    with pytest.raises(ap.AIError, match="refused the Grok key"):
        ap.ask_text("hi")


class BusyThenOK:
    def __init__(self, err):
        self.err, self.calls = err, []

    def create(self, **kwargs):
        self.calls.append(kwargs["model"])
        if len(self.calls) == 1:
            raise RuntimeError(self.err)
        return type("R", (), {"output_text": "backup answer"})()


@pytest.mark.parametrize("err", ["503 UNAVAILABLE high demand", "504 DEADLINE_EXCEEDED", "429 RESOURCE_EXHAUSTED limit: 0"])
def test_busy_model_uses_backup_once(env, err):
    m = BusyThenOK(err); c = type("C", (), {"responses": m})(); use(env, c)
    assert ap.ask_text("hi", purpose="rules") == "backup answer"
    assert m.calls == ["grok-4.7", "grok-4.6"]
    assert "backup model" in ap.LAST_STATUS["message"]


def test_wrong_key_does_not_use_backup(env):
    m = BusyThenOK("403 PERMISSION_DENIED api key"); c = type("C", (), {"responses": m})(); use(env, c)
    with pytest.raises(ap.AIError, match="refused"):
        ap.ask_text("hi")
    assert m.calls == ["grok-4.7"]


def test_copilot_and_rules_use_grok(env):
    c = FakeClient(text="tips"); use(env, c)
    assert prism_ai.get_prism_ai_guidance({"view": "Active Squad Hub", "screen_context": {"page": "Desk"}}) == "tips"
    assert c.responses.calls[0]["model"] == "grok-4.7"


class FailThen:
    def __init__(self, n, err, text="ok"):
        self.n, self.err, self.text, self.calls = n, err, text, []

    def create(self, **kwargs):
        self.calls.append(kwargs["model"])
        if len(self.calls) <= self.n:
            raise RuntimeError(self.err)
        return type("R", (), {"output_text": self.text})()


def test_timeout_retries_with_gutter_then_approach(env, monkeypatch):
    pauses = []
    events = []
    monkeypatch.setattr(ap, "_pause", lambda seconds: pauses.append(seconds))
    token = ap.push_retry_listener(lambda phase, message: events.append((phase, message)))
    try:
        m = FailThen(99, "timed out")
        use(env, type("C", (), {"responses": m})())
        with pytest.raises(ap.AIError, match="Gutter ball") as raised:
            ap.ask_text("hi")
    finally:
        ap.pop_retry_listener(token)
    message = str(raised.value)
    assert "took too long" in message
    assert "got back on the approach" in message
    assert message.endswith("Please try again.")
    assert m.calls == ["grok-4.7", "grok-4.6"] * (ap.EXTRA_RETRIES + 1)
    assert pauses == [beat for pair in ap.RETRY_BEATS for beat in pair]
    assert [phase for phase, _ in events] == ["gutter", "approach", "gutter", "approach", "give_up"]
    assert events[1][1] == "Getting back on the approach..."


def test_busy_succeeds_on_the_approach(env, monkeypatch):
    monkeypatch.setattr(ap, "_pause", lambda seconds: None)
    m = FailThen(2, "503 UNAVAILABLE high demand", text="back on the lane")
    use(env, type("C", (), {"responses": m})())
    assert ap.ask_text("hi") == "back on the lane"
    assert m.calls == ["grok-4.7", "grok-4.6", "grok-4.7"]
    assert "getting back on the approach" in ap.LAST_STATUS["message"]


def test_generic_api_error_retries_same_model(env, monkeypatch):
    monkeypatch.setattr(ap, "_pause", lambda seconds: None)
    c = FakeClient(exc=RuntimeError("connection reset by peer")); use(env, c)
    with pytest.raises(ap.AIError, match="Gutter ball") as raised:
        ap.ask_text("hi")
    assert "couldn't complete" in str(raised.value)
    assert "Please try again in a moment." in str(raised.value)
    assert [call["model"] for call in c.responses.calls] == ["grok-4.7"] * (ap.EXTRA_RETRIES + 1)


def test_missing_model_does_not_retry(env, monkeypatch):
    def boom(_seconds):
        raise AssertionError("paused")

    monkeypatch.setattr(ap, "_pause", boom)
    c = FakeClient(exc=RuntimeError("404 NOT_FOUND")); use(env, c)
    with pytest.raises(ap.AIError, match="isn't available"):
        ap.ask_text("hi")
    assert len(c.responses.calls) == 1
    assert "Gutter ball" not in ap.LAST_STATUS["message"]


def test_empty_answer_is_not_retried(env, monkeypatch):
    def boom(_seconds):
        raise AssertionError("paused")

    monkeypatch.setattr(ap, "_pause", boom)
    c = FakeClient(text="  "); use(env, c)
    with pytest.raises(ap.AIError, match="empty answer"):
        ap.ask_text("hi")
    assert len(c.responses.calls) == 1


def test_retry_listener_errors_are_ignored(env, monkeypatch):
    monkeypatch.setattr(ap, "_pause", lambda seconds: None)
    token = ap.push_retry_listener(lambda *_args: (_ for _ in ()).throw(RuntimeError("ui")))
    try:
        c = FakeClient(exc=RuntimeError("503 UNAVAILABLE")); use(env, c)
        with pytest.raises(ap.AIError, match="Gutter ball"):
            ap.ask_text("hi")
    finally:
        ap.pop_retry_listener(token)
    assert len(c.responses.calls) == (ap.EXTRA_RETRIES + 1) * 2

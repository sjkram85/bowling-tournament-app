import pytest
from modules import ai_provider as ap, prism_ai, ocr_engine, ai_roster


class FakeModels:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []

    def generate_content(self, model, contents, config):
        self.calls.append((model, config))
        if self.exc:
            raise self.exc
        return type("R", (), {"text": self.text})()


class FakeClient:
    def __init__(self, **kw):
        self.models = FakeModels(**kw)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_RULES_MODEL", "GEMINI_BACKUP_MODEL"):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


def use(env, client):
    env.setenv("GEMINI_API_KEY", "test")
    env.setattr(ap, "_client", lambda: client)


def test_defaults():
    assert ap.model_name() == "gemini-3.8-flash"
    assert ap.model_name("rules") == "gemini-3.8-flash"
    assert ap.model_name("backup") == "gemini-3.6-flash"
    assert ap.is_retired("gemini-2.0-flash")


def test_no_key_plain_message():
    with pytest.raises(ap.AIError, match="turned off"):
        ap.ask_text("hi")


@pytest.mark.parametrize("old", ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"])
def test_retired_model_blocked_no_call(env, old):
    c = FakeClient(text="x"); use(env, c); env.setenv("GEMINI_MODEL", old)
    with pytest.raises(ap.AIError, match=f"old model \\({old}\\).*Change GEMINI_MODEL to gemini-3.8-flash"):
        ap.ask_text("hi")
    assert c.models.calls == [] and ap.LAST_STATUS["ok"] is False


def test_current_lite_not_blocked(env):
    c = FakeClient(text="ok"); use(env, c); env.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    assert ap.ask_text("hi") == "ok" and c.models.calls[0][0] == "gemini-3.5-flash-lite"


def test_rules_uses_rules_model(env):
    c = FakeClient(text="Rule answer"); use(env, c)
    out = prism_ai.get_prism_ai_guidance({"view": "USBC Rules Engine"}, user_prompt="wrong lane?")
    assert out.startswith("Rule answer") and "Sections checked: Rule 9" in out and c.models.calls[0][0] == "gemini-3.8-flash"
    assert ap.LAST_STATUS["ok"] is True


def test_api_refusal_labeled_unavailable(env):
    c = FakeClient(exc=RuntimeError("404 NOT_FOUND models/gemini-3.8-flash")); use(env, c)
    out = prism_ai.get_prism_ai_guidance({"view": "Intake"}, user_prompt="q")
    assert out.startswith("A.I. unavailable: Google says the model 'gemini-3.8-flash' isn't available")
    assert "not an A.I. answer" in out


def test_extract_json_and_roster(env):
    c = FakeClient(text='```json\n{"bowlers":[{"name":"Al","entering_avg":200}]}\n```'); use(env, c)
    recs = ai_roster.parse_roster_with_gemini(b"name\nAl\n", "r.csv")
    assert recs == [{"name": "Al", "entering_avg": 200}]
    assert c.models.calls[0][1].response_mime_type == "application/json"


def test_roster_error_no_silent_fallback(env):
    c = FakeClient(exc=RuntimeError("timed out")); use(env, c)
    with pytest.raises(ap.AIError, match="took too long"):
        ai_roster.parse_roster_with_gemini(b"Lane 1: Al (Avg 200) - Paid", "r.txt")


def test_ocr(env):
    c = FakeClient(text='{"bowlers":[{"name":"Al","game_score":201}]}'); use(env, c)
    assert ocr_engine.extract_scores_from_overhead_photo(b"img")["extracted_data"][0]["game_score"] == 201
    env.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    r = ocr_engine.extract_scores_from_overhead_photo(b"img")
    assert r["status"] == "error" and r["extracted_data"] == [] and "retired" in r["message"]


def test_bad_key_message(env):
    c = FakeClient(exc=RuntimeError("403 PERMISSION_DENIED")); use(env, c)
    with pytest.raises(ap.AIError, match="refused the Gemini key"):
        ap.ask_text("hi")


class BusyThenOK:
    def __init__(self, err):
        self.err, self.calls = err, []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        if len(self.calls) == 1:
            raise RuntimeError(self.err)
        return type("R", (), {"text": "backup answer"})()


@pytest.mark.parametrize("err", ["503 UNAVAILABLE high demand", "504 DEADLINE_EXCEEDED", "429 RESOURCE_EXHAUSTED limit: 0"])
def test_busy_model_uses_backup_once(env, err):
    m = BusyThenOK(err); c = type("C", (), {"models": m})(); use(env, c)
    assert ap.ask_text("hi", purpose="rules") == "backup answer"
    assert m.calls == ["gemini-3.8-flash", "gemini-3.6-flash"]
    assert "backup model" in ap.LAST_STATUS["message"]


def test_wrong_key_does_not_use_backup(env):
    m = BusyThenOK("403 PERMISSION_DENIED api key"); c = type("C", (), {"models": m})(); use(env, c)
    with pytest.raises(ap.AIError, match="refused"):
        ap.ask_text("hi")
    assert m.calls == ["gemini-3.8-flash"]


def test_copilot_and_rules_use_flash(env):
    c = FakeClient(text="tips"); use(env, c)
    assert prism_ai.get_prism_ai_guidance({"view": "Active Squad Hub", "screen_context": {"page": "Desk"}}) == "tips"
    assert c.models.calls[0][0] == "gemini-3.8-flash"


class FailThen:
    def __init__(self, n, err, text="ok"):
        self.n, self.err, self.text, self.calls = n, err, text, []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        if len(self.calls) <= self.n:
            raise RuntimeError(self.err)
        return type("R", (), {"text": self.text})()


def test_timeout_retries_with_gutter_then_approach(env, monkeypatch):
    pauses = []
    events = []
    monkeypatch.setattr(ap, "_pause", lambda seconds: pauses.append(seconds))
    token = ap.push_retry_listener(lambda phase, message: events.append((phase, message)))
    try:
        m = FailThen(99, "timed out")
        use(env, type("C", (), {"models": m})())
        with pytest.raises(ap.AIError, match="Gutter ball") as raised:
            ap.ask_text("hi")
    finally:
        ap.pop_retry_listener(token)
    message = str(raised.value)
    assert "took too long" in message
    assert "got back on the approach" in message
    assert message.endswith("Please try again.")
    assert m.calls == ["gemini-3.8-flash", "gemini-3.6-flash"] * (ap.EXTRA_RETRIES + 1)
    assert pauses == [beat for pair in ap.RETRY_BEATS for beat in pair]
    assert [phase for phase, _ in events] == ["gutter", "approach", "gutter", "approach", "give_up"]
    assert events[1][1] == "Getting back on the approach..."


def test_busy_succeeds_on_the_approach(env, monkeypatch):
    monkeypatch.setattr(ap, "_pause", lambda seconds: None)
    m = FailThen(2, "503 UNAVAILABLE high demand", text="back on the lane")
    use(env, type("C", (), {"models": m})())
    assert ap.ask_text("hi") == "back on the lane"
    assert m.calls == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.8-flash"]
    assert "getting back on the approach" in ap.LAST_STATUS["message"]


def test_generic_api_error_retries_same_model(env, monkeypatch):
    monkeypatch.setattr(ap, "_pause", lambda seconds: None)
    c = FakeClient(exc=RuntimeError("connection reset by peer")); use(env, c)
    with pytest.raises(ap.AIError, match="Gutter ball") as raised:
        ap.ask_text("hi")
    assert "couldn't complete" in str(raised.value)
    assert "Please try again in a moment." in str(raised.value)
    assert [call[0] for call in c.models.calls] == ["gemini-3.8-flash"] * (ap.EXTRA_RETRIES + 1)


def test_missing_model_does_not_retry(env, monkeypatch):
    def boom(_seconds):
        raise AssertionError("paused")

    monkeypatch.setattr(ap, "_pause", boom)
    c = FakeClient(exc=RuntimeError("404 NOT_FOUND")); use(env, c)
    with pytest.raises(ap.AIError, match="isn't available"):
        ap.ask_text("hi")
    assert len(c.models.calls) == 1
    assert "Gutter ball" not in ap.LAST_STATUS["message"]


def test_empty_answer_is_not_retried(env, monkeypatch):
    def boom(_seconds):
        raise AssertionError("paused")

    monkeypatch.setattr(ap, "_pause", boom)
    c = FakeClient(text="  "); use(env, c)
    with pytest.raises(ap.AIError, match="empty answer"):
        ap.ask_text("hi")
    assert len(c.models.calls) == 1


def test_retry_listener_errors_are_ignored(env, monkeypatch):
    monkeypatch.setattr(ap, "_pause", lambda seconds: None)
    token = ap.push_retry_listener(lambda *_args: (_ for _ in ()).throw(RuntimeError("ui")))
    try:
        c = FakeClient(exc=RuntimeError("503 UNAVAILABLE")); use(env, c)
        with pytest.raises(ap.AIError, match="Gutter ball"):
            ap.ask_text("hi")
    finally:
        ap.pop_retry_listener(token)
    assert len(c.models.calls) == (ap.EXTRA_RETRIES + 1) * 2

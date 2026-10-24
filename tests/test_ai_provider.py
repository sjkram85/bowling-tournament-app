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
    for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_RULES_MODEL"):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


def use(env, client):
    env.setenv("GEMINI_API_KEY", "test")
    env.setattr(ap, "_client", lambda: client)


def test_defaults():
    assert ap.model_name() == "gemini-3.8-flash" and ap.model_name("rules") == "gemini-4-argon"


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
    assert out.startswith("Rule answer") and "Sections checked: Rule 9" in out and c.models.calls[0][0] == "gemini-4-argon"
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

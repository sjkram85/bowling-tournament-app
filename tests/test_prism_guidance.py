import re
import json

import pytest

from modules import ai_provider, prism_ai, rulebook
from modules.ai_provider import AIError
from modules.screen_context import MAX_CONTEXT_CHARS, build_screen_context, context_to_text


def _rules(question):
    return [s["rule"] for s in rulebook.search(question)]


# ---------- parsing
def test_parser_splits_rules_and_skips_noise():
    text = (
        "Rule 8\tDead Ball\n"  # table of contents style line (no dash) is not a heading
        "Rule 8 – Dead Ball\nWhen a dead ball is called, the delivery does not count and pins are respotted.\n"
        "      11   USBC\n"
        "Commonly Asked Questions – Rule 8.\nCan a dead ball be called after the next delivery? No, it cannot be.\n"
        "Rule 9 – Bowling on the Wrong Lane\nWhen only one player bowls on the wrong lane the score counts.\n"
    )
    secs = rulebook.parse_rulebook_text(text)
    assert [(s["rule"], s["title"]) for s in secs] == [("8", "Dead Ball"), ("9", "Bowling on the Wrong Lane")]
    assert "next delivery" in secs[0]["text"]
    assert "USBC" not in secs[0]["text"].split()[-1]


def test_committed_index_has_core_rules():
    secs = rulebook.load_sections()
    titles = {s["rule"]: s["title"] for s in secs}
    assert titles["5"] == "Fouls"
    assert titles["8"] == "Dead Ball"
    assert titles["9"] == "Bowling on the Wrong Lane"
    assert titles["10"] == "Provisional Ball"
    assert all(len(s["text"]) <= rulebook.MAX_CHUNK_CHARS + 400 for s in secs)


# ---------- retrieval
@pytest.mark.parametrize("q", ["What counts as a foul?", "A bowler stepped over the foul line"])
def test_foul_questions(q):
    assert _rules(q)[0] == "5"


@pytest.mark.parametrize("q", ["When is it a dead ball?", "The pinsetter hit a pin before the ball got there, is that a dead ball?"])
def test_dead_ball_questions(q):
    assert "8" in _rules(q)[:2]


@pytest.mark.parametrize("q", ["Someone bowled on the wrong lane", "bowler threw on the wrong pair of lanes"])
def test_wrong_lane_questions(q):
    assert _rules(q)[0] == "9"


def test_explicit_rule_number():
    assert _rules("what does rule 10 say")[0] == "10"


def test_unrelated_question_returns_nothing():
    assert rulebook.search("pizza delivery recipes") == []
    assert prism_ai.answer_rule_question("pizza delivery recipes") == prism_ai.NO_MATCH_MESSAGE


# ---------- prompts
def test_rules_prompt_contains_only_retrieved_sections(monkeypatch):
    seen = {}

    def fake(prompt, system=None, purpose="general"):
        seen.update(prompt=prompt, system=system, purpose=purpose)
        return "It's a dead ball (Rule 8)."

    monkeypatch.setattr(ai_provider, "ask_text", fake)
    out = prism_ai.answer_rule_question("When is it a dead ball?")
    assert seen["purpose"] == "rules"
    assert "[Rule 8 – Dead Ball]" in seen["prompt"]
    assert len(seen["prompt"]) < 6000  # only a few sections, never the whole book
    assert "ONLY" in seen["system"]
    assert "Sections checked: Rule 8 (Dead Ball)" in out


def test_everyday_prompt_is_small_and_has_no_rulebook(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai_provider, "ask_text", lambda p, system=None, purpose="general": seen.update(p=p, purpose=purpose) or "ok")
    ctx = {"page": "Active Squad Hub", "bowlers": 40, "checked_in": "38 of 40", "current_game": 2,
           "warnings": ["2 bowler(s) not checked in.", "Lanes still missing game 2 scores: 3, 4."]}
    prism_ai.get_prism_ai_guidance({"view": "Active Squad Hub", "screen_context": ctx})
    assert seen["purpose"] == "general"
    assert "Lanes still missing game 2 scores" in seen["p"]
    assert "Rule" not in seen["p"]
    assert len(seen["p"]) < 1200


def test_fallback_has_no_rule_numbers(monkeypatch):
    def boom(*a, **k):
        raise AIError("A.I. is turned off.")

    monkeypatch.setattr(ai_provider, "ask_text", boom)
    for text in (prism_ai._local_fallback_guidance("Intake", None), prism_ai._local_fallback_guidance("Intake", "q")):
        assert not re.search(r"Rule \d", text) and "6199" not in text
    out = prism_ai.answer_rule_question("wrong lane")
    assert out.startswith("A.I. unavailable") and "Rule 9" in out


# ---------- screen context from a real DB
def test_screen_context_counts(tmp_path, monkeypatch):
    from modules import db_state
    monkeypatch.setattr(db_state, "DB_PATH", tmp_path / "t.db")
    db_state.init_db()
    conn = db_state.get_connection()
    conn.execute("INSERT INTO tournaments (name, host_center, game_count) VALUES ('Test Open','Center',3)")
    for i in range(4):
        conn.execute("INSERT INTO bowlers (tournament_id, name, lane_assignment, lineup_position, checked_in) VALUES (1, ?, ?, ?, ?)",
                     (f"B{i}", 1 + i // 2, 1 + i % 2, 1 if i < 3 else 0))
    conn.execute("INSERT INTO scores (tournament_id, bowler_id, game_number, scratch_score) VALUES (1,1,1,200),(1,2,1,190)")
    conn.commit(); conn.close()
    ctx = build_screen_context("Active Squad Hub", 1)
    assert ctx["checked_in"] == "3 of 4" and ctx["current_game"] == 1
    assert any("Lanes still missing game 1 scores: 2." == w for w in ctx["warnings"])
    assert any("not checked in" in w for w in ctx["warnings"])
    assert len(context_to_text(ctx)) <= MAX_CONTEXT_CHARS
    assert "B0" not in json.dumps(ctx)  # no bowler names sent

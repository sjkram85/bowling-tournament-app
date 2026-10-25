"""Gutter-ball and approach feedback for Prism A.I. retries."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from components.ai_lane_feedback import approach_html, gutter_ball_html, rolling_ball_html
from modules.ai_provider import AIError


def test_lane_cards_use_the_bowling_words_and_escape_html():
    gutter = gutter_ball_html("Gutter ball. Google's A.I. is very busy. <script>", settled=True)
    assert "Gutter ball" in gutter
    assert "very busy" in gutter
    assert "<script>" not in gutter
    assert "is-settled" in gutter
    approach = approach_html()
    assert "Getting back on the approach" in approach
    assert "approach-walker" in approach
    rolling = rolling_ball_html("Rolling <b>analyzer")
    assert "Rolling &lt;b&gt;analyzer" in rolling
    assert "bowling-ball-svg" in rolling


def test_theme_css_animates_the_gutter_and_the_approach():
    css = Path("components/styles.py").read_text()
    assert "@keyframes gutter-roll" in css
    assert "@keyframes back-to-approach" in css


def test_copilot_shows_gutter_card_when_gemini_fails(monkeypatch):
    monkeypatch.setattr("components.prism_dock.build_screen_context", lambda *_a, **_k: {"page": "Intake"})

    def boom(*_args, **_kwargs):
        raise AIError(
            "Gutter ball. Google's A.I. is very busy right now. "
            "Prism got back on the approach and tried again, but the ball still went in the gutter. "
            "Please try again in a minute."
        )

    monkeypatch.setattr("modules.prism_ai.ai_provider.ask_text", boom)
    script = """
from components.prism_dock import collect_view_state, render_prism_dock
render_prism_dock("Intake Gateway", collect_view_state("Intake Gateway"))
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception, app.exception
    analyze = next(button for button in app.button if "Analyze" in button.label)
    app = analyze.click().run()
    assert not app.exception, app.exception
    blob = "\n".join(item.value for item in app.markdown)
    assert "Gutter ball" in blob
    assert "very busy" in blob
    assert "Please try again in a minute." in blob
    assert "Built-in tips" in blob

"""Bowling-lane feedback when Prism A.I. has to retry Gemini.

CSS lives in components/styles.py (apply_clean_theme). This module is HTML plus
a small Streamlit placeholder so Co-Pilot, roster ingest, and photo read can
share one gutter-ball / approach animation. No extra packages.
"""

from __future__ import annotations

import html

import streamlit as st

from modules.ai_provider import pop_retry_listener, push_retry_listener

_BALL_SVG = (
    '<svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="16" cy="16" r="15" fill="#1E293B" stroke="#0EA5E9" stroke-width="2"/>'
    '<circle cx="12" cy="11" r="2.2" fill="#F8FAFC"/>'
    '<circle cx="18" cy="10" r="2.2" fill="#F8FAFC"/>'
    '<circle cx="16" cy="16" r="2.2" fill="#F8FAFC"/>'
    '</svg>'
)

_PINS_SVG = (
    '<svg viewBox="0 0 28 36" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M14 2C12 2 11 4 11 6C11 8 12 9 12 11C11.5 13 10 15 10 18C10 20 12 21 14 21C16 21 18 20 18 18C18 15 16.5 13 16 11C16 9 17 8 17 6C17 4 16 2 14 2Z" fill="#F8FAFC"/>'
    '<rect x="11.5" y="6.5" width="5" height="1.5" fill="#EF4444"/>'
    '<path d="M6 10C4.5 10 4 11.5 4 13C4 14.5 4.5 15.5 4.5 17C4 18.5 3 20 3 22.5C3 24 4.5 25 6 25C7.5 25 9 24 9 22.5C9 20 8 18.5 7.5 17C7.5 15.5 8 14.5 8 13C8 11.5 7.5 10 6 10Z" fill="#E2E8F0"/>'
    '<rect x="4.5" y="13.5" width="3.5" height="1.2" fill="#EF4444"/>'
    '<path d="M22 10C20.5 10 20 11.5 20 13C20 14.5 20.5 15.5 20.5 17C20 18.5 19 20 19 22.5C19 24 20.5 25 22 25C23.5 25 25 24 25 22.5C25 20 24 18.5 23.5 17C23.5 15.5 24 14.5 24 13C24 11.5 23.5 10 22 10Z" fill="#E2E8F0"/>'
    '<rect x="20.5" y="13.5" width="3.5" height="1.2" fill="#EF4444"/>'
    '</svg>'
)


def _lane_detail(detail: str) -> str:
    text = (detail or "").strip()
    lower = text.lower()
    for prefix in ("a.i. unavailable:", "gutter ball."):
        if lower.startswith(prefix):
            text = text[len(prefix):].strip()
            lower = text.lower()
    return text or "Please try again."


def rolling_ball_html(label: str) -> str:
    """The in-progress lane (ball toward the pins) already used by Co-Pilot."""
    safe = html.escape(label or "Analyzing operations...")
    return (
        '<div class="bowling-loading-container">'
        '<div class="bowling-lane-stage">'
        f'<div class="bowling-ball-svg">{_BALL_SVG}</div>'
        f'<div class="pins-cluster-svg">{_PINS_SVG}</div>'
        '</div>'
        f'<div class="loading-text-glow">{safe}</div>'
        '</div>'
    )


def gutter_ball_html(detail: str = "", *, settled: bool = False) -> str:
    """Ball in the channel, pins still standing."""
    ball_class = "gutter-ball-svg is-settled" if settled else "gutter-ball-svg"
    safe = html.escape(_lane_detail(detail))
    return (
        '<div class="ai-lane-card ai-lane-gutter" role="status">'
        '<div class="gutter-lane" aria-hidden="true">'
        '<div class="gutter-channel top"></div>'
        '<div class="gutter-channel bottom"></div>'
        f'<div class="{ball_class}">{_BALL_SVG}</div>'
        f'<div class="gutter-pins">{_PINS_SVG}</div>'
        '</div>'
        '<div class="ai-lane-copy">'
        '<div class="ai-lane-title">Gutter ball</div>'
        f'<div class="ai-lane-detail">{safe}</div>'
        '</div>'
        '</div>'
    )


def approach_html() -> str:
    """Bowler walking the ball back to the approach while Prism retries."""
    return (
        '<div class="ai-lane-card ai-lane-approach" role="status">'
        '<div class="approach-lane" aria-hidden="true">'
        '<div class="approach-foul"></div>'
        '<div class="approach-walker">'
        '<div class="approach-bowler"></div>'
        f'<div class="approach-ball">{_BALL_SVG}</div>'
        '</div>'
        '</div>'
        '<div class="ai-lane-copy">'
        '<div class="ai-lane-title">Getting back on the approach...</div>'
        '<div class="ai-lane-detail">Prism is sending the shot again.</div>'
        '</div>'
        '</div>'
    )


def bind_lane_placeholder(placeholder):
    """Point Gemini retries at a Streamlit placeholder. Returns a reset token."""

    def listener(phase: str, message: str) -> None:
        if phase == "approach":
            placeholder.markdown(approach_html(), unsafe_allow_html=True)
        elif phase in ("gutter", "give_up"):
            placeholder.markdown(
                gutter_ball_html(message, settled=(phase == "give_up")),
                unsafe_allow_html=True,
            )

    return push_retry_listener(listener)


def call_with_lane_feedback(fn, *, waiting_html: str):
    """Show the rolling ball, then gutter / approach if Gemini retries, then return fn()."""
    slot = st.empty()
    slot.markdown(waiting_html, unsafe_allow_html=True)
    token = bind_lane_placeholder(slot)
    try:
        return fn()
    finally:
        pop_retry_listener(token)
        slot.empty()

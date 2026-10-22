"""Slate dashboard styling."""

import streamlit as st

_CSS = """
<style>
input, select, textarea,
[data-baseweb="input"] input,
[data-baseweb="select"] input,
[data-baseweb="textarea"] textarea {
    font-size: 16px !important;
}

button,
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button,
[data-testid^="stBaseButton"] {
    min-height: 44px !important;
    border-radius: 8px;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}

[data-testid="stMetric"] {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 12px 16px;
}

.ptcc-header-title {
    color: #0F172A;
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.2;
    text-align: center;
}

[class*="st-key-tile_green"] {
    background: #ECFDF5;
    border: 1px solid #10B981;
    border-radius: 12px;
    padding: 12px;
}

[class*="st-key-tile_amber"] {
    background: #FFFBEB;
    border: 1px solid #F59E0B;
    border-radius: 12px;
    padding: 12px;
}

.ptcc-tile-title {
    color: #0F172A;
    font-weight: 700;
}

.ptcc-tile-stat {
    color: #334155;
    font-size: 0.9rem;
}

.ptcc-banner {
    background: #334155;
    border-radius: 12px;
    color: #FFFFFF;
    font-size: 1.4rem;
    font-weight: 700;
    padding: 16px 20px;
    text-align: center;
}

.ptcc-banner small {
    display: block;
    font-size: 0.9rem;
    font-weight: 400;
    margin-top: 4px;
}

.ptcc-game-badge {
    background: #334155;
    border-radius: 999px;
    color: #FFFFFF;
    display: inline-block;
    font-size: 0.85rem;
    font-weight: 600;
    padding: 2px 12px;
}
</style>
"""


def apply_clean_theme() -> None:
    """Inject the global CSS; safe to call more than once per script run."""
    st.markdown(_CSS, unsafe_allow_html=True)


inject_styles = apply_clean_theme

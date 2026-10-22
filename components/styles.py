"""Slate dashboard styling (dark palette)."""

import streamlit as st

_CSS = """
<style>
/* ---- layout: keep content readable on ultra-wide monitors ---- */
[data-testid="stMainBlockContainer"], .block-container {
    max-width: 1440px;
    margin-left: auto;
    margin-right: auto;
    padding: 2rem 2rem 4rem 2rem;
}
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"], .block-container { padding: 1rem 0.75rem 3rem 0.75rem; }
}

/* ---- touch / mobile Safari ---- */
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

/* ---- cards: one look for every bordered container ---- */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
    border-radius: 12px;
}
div[data-testid="stVerticalBlock"][class*="st-key-card"],
div[data-testid="stVerticalBlockBorderWrapper"][class*="st-key-card"],
.ptcc-card {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 18px;
    color: #F1F5F9;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 18px;
}
/* do not double-pad blocks nested in a card */
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlockBorderWrapper"] {
    background: #0F172A;
    padding: 14px;
}

[data-testid="stMetric"] {
    background: #0F172A;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 18px;
}
[data-testid="stMetricLabel"] { color: #94A3B8; }
[data-testid="stMetricValue"] { color: #F8FAFC; }

/* ---- login card ---- */
div[class*="st-key-auth_card"] {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 12px;
    max-width: 520px;
    margin: 0 auto;
    padding: 28px;
}
.ptcc-auth-title { color: #F8FAFC; font-size: 1.5rem; font-weight: 700; margin-top: 14px; }
div[class*="st-key-auth_card"] [data-testid="stForm"] {
    background: transparent;
    border: none;
    padding: 0;
}
div[class*="st-key-auth_card"] [data-testid="stTextInputRootElement"],
div[class*="st-key-auth_card"] [data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: #0F172A;
    border: 1px solid #475569;
    border-radius: 8px;
}
.ptcc-auth-subtitle { color: #94A3B8; font-size: 0.9rem; margin: 4px 0 12px 0; }

/* ---- top banner ---- */
div[class*="st-key-ptcc_header"] {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 12px;
}
.ptcc-logo-plate {
    background: #FFFFFF;
    border-radius: 8px;
    display: inline-block;
    padding: 4px;
    line-height: 0;
}
.ptcc-brand { color: #F8FAFC; font-weight: 700; line-height: 1.2; }
.ptcc-brand small { color: #94A3B8; display: block; font-weight: 400; }
.ptcc-header-title {
    color: #F8FAFC;
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.2;
    text-align: center;
}
.ptcc-header-meta {
    color: #94A3B8;
    font-size: 0.9rem;
    margin-top: 4px;
    text-align: center;
}
.ptcc-center-badge {
    background: #334155;
    border: 1px solid #475569;
    border-radius: 8px;
    color: #F8FAFC;
    display: inline-block;
    font-size: 1.1rem;
    font-weight: 700;
    padding: 10px 16px;
}

.ptcc-game-badge {
    background: #2563EB;
    border-radius: 999px;
    color: #FFFFFF;
    display: inline-block;
    font-size: 0.85rem;
    font-weight: 600;
    padding: 2px 12px;
}
.ptcc-pill {
    border-radius: 999px;
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 2px 10px;
}
.ptcc-pill-green { background: #14532D; color: #86EFAC; border: 1px solid #22C55E; }
.ptcc-pill-amber { background: #78350F; color: #FCD34D; border: 1px solid #F59E0B; }

/* ---- heatmap tiles ---- */
div[class*="st-key-tile_green"], div[class*="st-key-tile_amber"] {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 12px;
    color: #F1F5F9;
    padding: 18px;
}
div[class*="st-key-tile_green"] { border-left: 5px solid #22C55E; }
div[class*="st-key-tile_amber"] { border-left: 5px solid #F59E0B; }
.ptcc-tile-title { color: #F8FAFC; font-weight: 700; margin-bottom: 6px; }
.ptcc-tile-stat { color: #CBD5E1; font-size: 0.9rem; margin-top: 6px; }

/* ---- stepladder / bowler banner ---- */
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
</style>
"""


def apply_clean_theme() -> None:
    """Inject the global CSS; safe to call more than once per script run."""
    st.markdown(_CSS, unsafe_allow_html=True)


inject_styles = apply_clean_theme

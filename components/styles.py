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

/* ---- sidebar navigation rail ---- */
[data-testid="stSidebar"] { background: #0F172A; border-right: 1px solid #334155; }
.ptcc-side-brand {
    align-items: center;
    border-bottom: 1px solid #334155;
    display: flex;
    gap: 12px;
    margin-bottom: 8px;
    padding-bottom: 16px;
}
.ptcc-side-brand .ptcc-logo-plate { flex: 0 0 auto; }
.ptcc-side-text { flex: 1 1 0; min-width: 0; }
.ptcc-side-title {
    color: #F8FAFC !important;
    font-size: 15px;
    font-weight: 700;
    line-height: 1.25;
    overflow-wrap: break-word;
}
.ptcc-side-badge {
    color: #10B981;
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    margin-top: 4px;
    text-transform: uppercase;
}
.ptcc-nav-heading {
    color: #64748B;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    margin: 16px 0 4px 8px;
}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
    border-left: 3px solid transparent;
    border-radius: 8px;
    color: #CBD5E1;
    margin: 0;
    min-height: 40px;
    transition: background 0.15s ease, border-color 0.15s ease;
}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover { background: #1E293B80; }
div[class*="st-key-nav_active"] [data-testid="stPageLink-NavLink"] {
    background: #1E293B;
    border-left: 3px solid #E11D48;
    color: #FFFFFF;
    font-weight: 700;
}
div[class*="st-key-nav_active"] [data-testid="stPageLink-NavLink"] p { font-weight: 700; color: #FFFFFF; }

div[class*="st-key-side_identity"] {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 10px;
    margin-top: 24px;
    padding: 12px;
}
.ptcc-id-row { align-items: center; display: flex; gap: 10px; }
.ptcc-avatar {
    align-items: center;
    background: #2563EB;
    border-radius: 50%;
    color: #FFFFFF;
    display: flex;
    flex: 0 0 38px;
    font-size: 14px;
    font-weight: 700;
    height: 38px;
    justify-content: center;
    width: 38px;
}
.ptcc-id-name { color: #F8FAFC; font-weight: 700; line-height: 1.2; }
.ptcc-role-pill {
    border-radius: 999px;
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-top: 3px;
    padding: 1px 8px;
}
.ptcc-role-admin { background: #064E3B; border: 1px solid #10B981; color: #6EE7B7; }
.ptcc-role-td { background: #1E3A8A; border: 1px solid #3B82F6; color: #93C5FD; }
.ptcc-id-center { color: #94A3B8; font-size: 0.8rem; margin: 8px 0 10px 0; }
div[class*="st-key-side_about"] button { background: transparent; border: 1px solid #334155; color: #CBD5E1; }
div[class*="st-key-side_signout"] button { background: transparent; border: 1px solid #334155; color: #CBD5E1; }
div[class*="st-key-side_signout"] button:hover {
    background: #EF44441A;
    border-color: #EF4444;
    color: #FCA5A5;
}

/* ---- Prism A.I dock ---- */
div[class*="st-key-prism_dock"] {
    background: #1E293B;
    border: 1px solid #334155;
    border-radius: 12px;
    margin-top: 24px;
    max-height: 70vh;
    overflow-y: auto;
    padding: 14px 18px;
}
.ptcc-dock-title { color: #F8FAFC; font-weight: 700; }
.ptcc-dock-spark { color: #F59E0B; }
.ptcc-dock-view {
    background: #0F172A;
    border: 1px solid #334155;
    border-radius: 999px;
    color: #94A3B8;
    font-size: 0.75rem;
    margin-left: 10px;
    padding: 2px 10px;
}
.ptcc-dock-guidance {
    background: #0F172A;
    border-left: 4px solid #F59E0B;
    border-radius: 8px;
    color: #E2E8F0;
    margin: 6px 0 10px 0;
    padding: 10px 14px;
}

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

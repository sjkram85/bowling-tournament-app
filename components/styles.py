"""Application styling, themes, and CSS overrides for PTCC."""

import streamlit as st


def apply_clean_theme() -> None:
    """Inject core layout, Slate palette, responsive anti-dimming, and bowling lane animation."""
    st.markdown(
        """
        <style>
        /* =========================================================
           DISABLE STREAMLIT RUNNING / STALE SCREEN DIMMING
           ========================================================= */
        div[data-testid="stAppViewContainer"],
        div[data-testid="stMain"],
        div[data-testid="stSidebar"],
        section[data-testid="stSidebar"] ~ section,
        div[data-testid="stVerticalBlock"],
        .stApp {
            opacity: 1 !important;
            filter: none !important;
            transition: none !important;
        }

        div[data-testid="stMain"] > div {
            opacity: 1 !important;
        }

        /* =========================================================
           REALISTIC MINI BOWLING LANE LOADER
           ========================================================= */
        .bowling-loading-container {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            background: #0F172A;
            border: 1px solid #1E293B;
            border-left: 3px solid #F59E0B;
            border-radius: 8px;
            margin: 10px 0;
        }

        .bowling-lane-stage {
            position: relative;
            width: 72px;
            height: 28px;
            background: linear-gradient(180deg, #3E2723 0%, #5D4037 25%, #4E342E 100%);
            border-radius: 4px;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.6);
            overflow: hidden;
            display: flex;
            align-items: center;
        }

        /* Lane guide board lines */
        .bowling-lane-stage::after {
            content: "";
            position: absolute;
            left: 0;
            right: 0;
            top: 50%;
            height: 1px;
            background: rgba(255, 255, 255, 0.08);
        }

        /* Bowling Ball */
        .bowling-ball-svg {
            position: absolute;
            left: 4px;
            width: 16px;
            height: 16px;
            animation: roll-down-lane 1.4s infinite ease-in;
            z-index: 2;
        }

        /* Bowling Pin Triangle */
        .pins-cluster-svg {
            position: absolute;
            right: 5px;
            width: 14px;
            height: 20px;
            animation: pin-impact 1.4s infinite ease-in;
            z-index: 1;
        }

        .loading-text-glow {
            color: #F8FAFC;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }

        @keyframes roll-down-lane {
            0% {
                left: 2px;
                transform: rotate(0deg);
                opacity: 0.3;
            }
            15% {
                opacity: 1;
            }
            70% {
                left: 48px;
                transform: rotate(540deg);
                opacity: 1;
            }
            75% {
                left: 52px;
                transform: rotate(620deg);
                opacity: 0;
            }
            100% {
                left: 2px;
                transform: rotate(0deg);
                opacity: 0;
            }
        }

        @keyframes pin-impact {
            0%, 68% {
                transform: translate(0, 0) rotate(0deg) scale(1);
                opacity: 1;
            }
            73% {
                transform: translate(2px, -3px) rotate(18deg) scale(0.95);
                filter: brightness(1.4);
            }
            82% {
                transform: translate(5px, 2px) rotate(42deg) scale(0.85);
                opacity: 0.3;
            }
            92%, 100% {
                transform: translate(0, 0) rotate(0deg) scale(1);
                opacity: 1;
            }
        }

        /* Gutter ball + getting back on the approach (Gemini retry) */
        .ai-lane-card {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
            padding: 10px 14px;
            background: #0F172A;
            border: 1px solid #1E293B;
            border-radius: 8px;
            margin: 10px 0;
        }

        .ai-lane-gutter { border-left: 3px solid #EF4444; }
        .ai-lane-approach { border-left: 3px solid #F59E0B; }

        .ai-lane-copy { flex: 1; min-width: 140px; }

        .ai-lane-title {
            color: #F8FAFC;
            font-size: 13px;
            font-weight: 700;
        }

        .ai-lane-detail {
            color: #CBD5E1;
            font-size: 12px;
            line-height: 1.45;
            margin-top: 2px;
            white-space: pre-wrap;
        }

        .gutter-lane, .approach-lane {
            position: relative;
            width: 86px;
            height: 32px;
            flex: 0 0 86px;
            background: linear-gradient(180deg, #3E2723 0%, #5D4037 30%, #4E342E 100%);
            border-radius: 4px;
            overflow: hidden;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.6);
        }

        .gutter-channel {
            position: absolute;
            left: 0;
            right: 0;
            height: 6px;
            background: repeating-linear-gradient(90deg, #0B1220, #0B1220 4px, #1F2937 4px, #1F2937 8px);
            z-index: 2;
        }

        .gutter-channel.top { top: 0; }
        .gutter-channel.bottom { bottom: 0; }

        .gutter-ball-svg, .approach-ball {
            position: absolute;
            width: 14px;
            height: 14px;
            z-index: 3;
        }

        .gutter-ball-svg svg, .approach-ball svg, .gutter-pins svg {
            width: 100%;
            height: 100%;
            display: block;
        }

        .gutter-ball-svg {
            left: 2px;
            top: 9px;
            animation: gutter-roll 0.65s ease-in forwards;
        }

        .gutter-ball-svg.is-settled {
            animation: none;
            left: 62px;
            top: 17px;
        }

        .gutter-pins {
            position: absolute;
            right: 2px;
            top: 6px;
            width: 16px;
            height: 20px;
            z-index: 1;
        }

        .approach-foul {
            position: absolute;
            left: 8px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: #EF4444;
            z-index: 2;
        }

        .approach-walker {
            position: absolute;
            top: 5px;
            left: 56px;
            width: 24px;
            height: 22px;
            z-index: 3;
            animation: back-to-approach 1.15s ease-in-out infinite;
        }

        .approach-bowler {
            position: absolute;
            left: 0;
            top: 0;
            width: 10px;
            height: 16px;
        }

        .approach-bowler::before {
            content: "";
            position: absolute;
            top: 0;
            left: 2px;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #F8FAFC;
        }

        .approach-bowler::after {
            content: "";
            position: absolute;
            top: 7px;
            left: 4px;
            width: 2px;
            height: 8px;
            background: #F59E0B;
            border-radius: 1px;
        }

        .approach-ball {
            right: 0;
            bottom: 0;
        }

        @keyframes gutter-roll {
            0% { left: 2px; top: 9px; transform: rotate(0deg); }
            62% { left: 46px; top: 9px; transform: rotate(380deg); }
            100% { left: 62px; top: 17px; transform: rotate(520deg); }
        }

        @keyframes back-to-approach {
            0% { left: 56px; }
            100% { left: 10px; }
        }

        /* Suppress native streamlit circle loader */
        [data-testid="stLoading"] {
            display: none !important;
        }

        /* =========================================================
           SIDEBAR BRANDING & IDENTITY CARD
           ========================================================= */
        .ptcc-side-brand {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 0 16px 0;
            border-bottom: 1px solid #1E293B;
            margin-bottom: 16px;
        }

        .ptcc-side-title {
            color: #F8FAFC;
            font-size: 14px;
            font-weight: 700;
            line-height: 1.2;
        }

        .ptcc-side-badge {
            display: inline-block;
            background: #064E3B;
            color: #34D399;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
            margin-top: 4px;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        .ptcc-nav-heading {
            color: #64748B;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
            margin: 16px 0 6px 0;
        }

        .ptcc-id-row {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 6px;
        }

        .ptcc-avatar {
            width: 38px;
            height: 38px;
            background: #2563EB;
            color: #FFFFFF;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
            box-shadow: 0 2px 6px rgba(37, 99, 235, 0.4);
        }

        .ptcc-id-name {
            color: #F8FAFC;
            font-size: 14px;
            font-weight: 700;
            line-height: 1.2;
        }

        .ptcc-id-center {
            color: #94A3B8;
            font-size: 12px;
            margin-bottom: 10px;
        }

        .ptcc-role-pill {
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            display: inline-block;
            text-transform: uppercase;
        }

        .ptcc-role-admin {
            background: #064E3B;
            color: #6EE7B7;
        }

        .ptcc-role-td {
            background: #1E3A8A;
            color: #93C5FD;
        }

        /* Movement Banner */
        .ptcc-banner {
            background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
            border: 1px solid #334155;
            border-left: 4px solid #3B82F6;
            border-radius: 8px;
            padding: 12px 16px;
            color: #F8FAFC;
            font-weight: 700;
            font-size: 15px;
            margin-bottom: 16px;
        }

        .ptcc-banner small {
            display: block;
            color: #94A3B8;
            font-weight: 500;
            font-size: 12px;
            margin-top: 2px;
        }

        /* Remove browser autofill yellow highlights */
        input:-webkit-autofill,
        input:-webkit-autofill:hover, 
        input:-webkit-autofill:focus,
        textarea:-webkit-autofill,
        textarea:-webkit-autofill:hover,
        textarea:-webkit-autofill:focus,
        select:-webkit-autofill,
        select:-webkit-autofill:hover,
        select:-webkit-autofill:focus {
            -webkit-text-fill-color: #F8FAFC !important;
            -webkit-box-shadow: 0 0 0px 1000px #0F172A inset !important;
            transition: background-color 5000s ease-in-out 0s !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_styles() -> None:
    """Helper for standalone portal views (?mode=bowler, ?mode=score)."""
    apply_clean_theme()
"""Application styling, themes, and CSS overrides for PTCC."""

import streamlit as st


def apply_clean_theme() -> None:
    """Inject core layout, Slate palette, responsive anti-dimming, and custom animations."""
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
           THEMATIC ROLLING BOWLING BALL & PIN LOADING ANIMATION
           ========================================================= */
        .bowling-loading-container {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            background: #0F172A;
            border: 1px dashed #334155;
            border-radius: 6px;
            margin: 10px 0;
        }

        .bowling-lane-micro {
            position: relative;
            width: 44px;
            height: 20px;
            overflow: hidden;
            display: flex;
            align-items: center;
        }

        .bowling-ball-rolling {
            font-size: 14px;
            position: absolute;
            left: 0;
            animation: roll-and-bounce 1.2s infinite ease-in-out;
            transform-origin: center;
        }

        .pins-target {
            font-size: 14px;
            position: absolute;
            right: 2px;
            animation: pin-shake 1.2s infinite ease-in-out;
        }

        .loading-text-glow {
            color: #F59E0B;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.5px;
            animation: pulse-text 1.5s infinite ease-in-out;
        }

        @keyframes roll-and-bounce {
            0% {
                left: 0%;
                transform: rotate(0deg);
            }
            50% {
                left: 65%;
                transform: rotate(360deg);
            }
            100% {
                left: 0%;
                transform: rotate(0deg);
            }
        }

        @keyframes pin-shake {
            0%, 40%, 60%, 100% { transform: translate(0, 0) rotate(0deg); }
            45% { transform: translate(1px, -1px) rotate(3deg); }
            50% { transform: translate(-1px, 1px) rotate(-3deg); }
            55% { transform: translate(0px, -1px) rotate(1deg); }
        }

        @keyframes pulse-text {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        /* Hide the native streamlit loader in operations to prevent double loading icons */
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
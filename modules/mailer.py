"""Outbound email for CHUSBC tournaments via Gmail SMTP with branded tournament-desk styling."""

import base64
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
import smtplib

import streamlit as st
from modules.settings import get_secret

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
DEFAULT_ALERT_EMAIL = "chusbc.tournaments@gmail.com"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHUSBC_LOGO = ASSETS_DIR / "CHUSBC.jpg"


def _build_email_shell(inner_content: str, preview_text: str = "") -> str:
    """Wraps body markup in a tournament-desk card layout styled for CHUSBC."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cecil Harford USBC</title>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #0F172A; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #E2E8F0;">
  <span style="display: none !important; visibility: hidden; opacity: 0; color: transparent; height: 0; width: 0; max-height: 0;">
    {escape(preview_text)}
  </span>
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #0F172A;">
    <tr>
      <td align="center" style="padding: 12px;">
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 580px; background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; overflow: hidden; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);">
          
          <!-- BRAND HEADER -->
          <tr>
            <td align="center" style="padding: 26px 24px 18px 24px; background: linear-gradient(180deg, #182234 0%, #1E293B 100%); border-bottom: 2px solid #D97706;">
              <table role="presentation" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <img src="cid:chusbc_logo" alt="CHUSBC" height="60" style="display: block; margin: 0 auto 12px auto; background-color: #FFFFFF; padding: 6px; border-radius: 8px; border: 1px solid #475569;" />
                  </td>
                </tr>
                <tr>
                  <td align="center">
                    <div style="font-size: 19px; font-weight: 800; color: #F8FAFC; letter-spacing: -0.3px; text-transform: uppercase;">
                      Cecil Harford USBC
                    </div>
                    <div style="font-size: 12px; font-weight: 700; color: #F59E0B; letter-spacing: 1.2px; text-transform: uppercase; margin-top: 3px;">
                      Tournament Control Center &middot; Official Operations
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- INNER CARD BODY -->
          <tr>
            <td style="padding: 28px 24px;">
              {inner_content}
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td align="center" style="padding: 18px 24px; background-color: #0B132B; border-top: 1px solid #334155; font-size: 11px; color: #64748B; line-height: 1.5;">
              Official Tournament Operations Notice &middot; Cecil Harford USBC Sanctioned Competition<br>
              Host Centers: Forest Hill Lanes &middot; Harford Lanes &middot; APG Bowling Center
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_ptcc_mail(to_email: str, subject: str, html_content: str) -> bool:
    """Send an HTML email with embedded CHUSBC sanction seal."""
    sender = get_secret("CHUSBC_GMAIL_USER", DEFAULT_ALERT_EMAIL)
    app_password = get_secret("CHUSBC_GMAIL_APP_PASSWORD")

    if not sender or not app_password or not to_email:
        return False

    cleaned_password = app_password.replace(" ", "").strip()

    msg_root = MIMEMultipart("related")
    msg_root["From"] = f"CHUSBC Tournament Desk <{sender}>"
    msg_root["To"] = to_email
    msg_root["Subject"] = subject

    msg_alternative = MIMEMultipart("alternative")
    msg_root.attach(msg_alternative)

    msg_alternative.attach(MIMEText(html_content, "html"))

    if CHUSBC_LOGO.is_file():
        try:
            with open(CHUSBC_LOGO, "rb") as img_file:
                img_data = MIMEImage(img_file.read(), _subtype="jpeg")
                img_data.add_header("Content-ID", "<chusbc_logo>")
                img_data.add_header("Content-Disposition", "inline", filename="CHUSBC.jpg")
                msg_root.attach(img_data)
        except Exception:
            pass

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender, cleaned_password)
            server.sendmail(sender, [to_email], msg_root.as_string())
    except (smtplib.SMTPException, OSError):
        return False
    return True


def send_admin_registration_alert(applicant: dict) -> bool:
    """Dispatches a tournament-official alert for pending desk operator credentials."""
    admin_email = get_secret("ADMIN_ALERT_EMAIL", DEFAULT_ALERT_EMAIL)
    display_name = escape(str(applicant.get("display_name") or "Tournament Official Applicant"))
    username = escape(str(applicant.get("username") or "-"))
    email = escape(str(applicant.get("email") or "-"))
    center = escape(str(applicant.get("center_affiliation") or "CHUSBC"))
    raw_role = str(applicant.get("role") or "td").lower()
    role_label = "Tournament Director (TD)" if raw_role == "td" else "System Administrator"

    inner_content = f"""
      <div style="border-left: 3px solid #F59E0B; padding-left: 12px; margin-bottom: 20px;">
        <h3 style="margin: 0 0 4px 0; color: #FFFFFF; font-size: 18px; font-weight: 700;">
          Tournament Official Credentials Pending Review
        </h3>
        <p style="margin: 0; font-size: 13px; color: #F59E0B; font-weight: 600;">
          Action Required: Tournament Desk Access Request
        </p>
      </div>

      <p style="margin: 0 0 20px 0; font-size: 14px; color: #CBD5E1; line-height: 1.5;">
        A tournament official has registered for desk access to manage lane play, roster verification, and squad scoring for Cecil Harford USBC championship events.
      </p>

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; margin-bottom: 24px;">
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #94A3B8; font-size: 13px; font-weight: 600; width: 38%;">Official's Name</td>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #F8FAFC; font-size: 14px; font-weight: 700;">{display_name}</td>
        </tr>
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #94A3B8; font-size: 13px; font-weight: 600;">Desk Username</td>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #38BDF8; font-size: 14px; font-weight: 700; font-family: monospace;">{username}</td>
        </tr>
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #94A3B8; font-size: 13px; font-weight: 600;">Contact Email</td>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #E2E8F0; font-size: 14px;">{email}</td>
        </tr>
        <tr>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #94A3B8; font-size: 13px; font-weight: 600;">Host House Affiliation</td>
          <td style="padding: 12px 16px; border-bottom: 1px solid #1E293B; color: #F8FAFC; font-size: 14px; font-weight: 600;">{center}</td>
        </tr>
        <tr>
          <td style="padding: 12px 16px; color: #94A3B8; font-size: 13px; font-weight: 600;">Requested Role</td>
          <td style="padding: 12px 16px;">
            <span style="background-color: #064E3B; color: #6EE7B7; font-size: 11px; font-weight: 700; padding: 4px 9px; border-radius: 4px; letter-spacing: 0.5px; border: 1px solid #059669;">
              {role_label}
            </span>
          </td>
        </tr>
      </table>

      <div style="background-color: #1E293B; border-radius: 6px; padding: 12px 16px; border: 1px dashed #475569; text-align: center;">
        <p style="font-size: 13px; color: #94A3B8; margin: 0;">
          To grant or decline credentials, log into the <b>Tournament Control Center</b> and open the <b>Staff Accounts</b> console.
        </p>
      </div>
    """

    preview = f"Official registration pending: {display_name} ({username}) requested credentials for {center}."
    full_html = _build_email_shell(inner_content, preview_text=preview)
    return send_ptcc_mail(str(admin_email), f"Desk Action Required: Tournament Official Registration ({username})", full_html)


def send_applicant_approval_notice(applicant_email: str, display_name: str) -> bool:
    """Dispatches a confirmation notice to the approved tournament official."""
    if not applicant_email:
        return False

    display = escape(display_name)
    inner_content = f"""
      <div style="border-left: 3px solid #10B981; padding-left: 12px; margin-bottom: 20px;">
        <h3 style="margin: 0 0 4px 0; color: #34D399; font-size: 19px; font-weight: 700;">
          Tournament Desk Access Granted
        </h3>
        <p style="margin: 0; font-size: 13px; color: #6EE7B7; font-weight: 600;">
          Cecil Harford USBC Official Operations
        </p>
      </div>

      <p style="font-size: 14px; color: #E2E8F0; line-height: 1.6; margin-bottom: 20px;">
        Hello <b>{display}</b>,<br><br>
        Your credentials for the <b>Prism Tournament Control Center</b> have been verified and approved by the tournament committee. You now have operational clearance to manage squad rosters, lane pairs, scoring entries, and side pots across CHUSBC events.
      </p>

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin: 24px 0;">
        <tr>
          <td align="center">
            <span style="display: inline-block; background-color: #0284C7; color: #FFFFFF; font-weight: 700; font-size: 14px; padding: 12px 24px; border-radius: 6px; text-decoration: none; border: 1px solid #38BDF8;">
              Open Tournament Desk Console
            </span>
          </td>
        </tr>
      </table>

      <p style="font-size: 12px; color: #94A3B8; margin-top: 16px; text-align: center;">
        Need technical assistance on shift? Contact the CHUSBC Tournament Administration Desk.
      </p>
    """

    preview = "Your Cecil Harford USBC tournament desk credentials have been approved."
    full_html = _build_email_shell(inner_content, preview_text=preview)
    return send_ptcc_mail(applicant_email, "Tournament Desk Credentials Approved - Cecil Harford USBC", full_html)


def dispatch_bowler_recap_email(bowler: dict, scores: list, totals: dict | None) -> bool:
    """Dispatches a certified tournament series scoresheet directly to a competitor."""
    to_email = bowler.get("email")
    if not to_email:
        return False

    totals = totals or {}
    name = escape(str(bowler.get("name", "Competitor")))
    handicap = int(bowler.get("handicap") or 0)
    entering_avg = bowler.get("entering_avg") or "N/A"

    rows = []
    computed_scratch = 0
    for score in scores:
        game = score.get("game_number", "")
        scratch = int(score.get("scratch_score") or 0)
        computed_scratch += scratch
        rows.append(
            f"""
            <tr>
              <td style="padding: 10px 14px; border-bottom: 1px solid #1E293B; font-weight: 600; color: #94A3B8;">Game {escape(str(game))}</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #1E293B; color: #F8FAFC; text-align: center; font-size: 15px; font-weight: 600;">{scratch}</td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #1E293B; color: #38BDF8; font-weight: 700; text-align: center; font-size: 15px;">{scratch + handicap}</td>
            </tr>
            """
        )

    total_scratch = int(totals.get("scratch_total", computed_scratch))
    total_handicap = int(totals.get("handicap_total", total_scratch + handicap * len(scores)))

    prize_meta = []
    if totals.get("place"):
        prize_meta.append(f"<b>Final Finish:</b> #{escape(str(totals['place']))}")
    if totals.get("prize_amount"):
        prize_meta.append(f"<b>Prize Payout:</b> ${float(totals['prize_amount']):,.2f}")
    if totals.get("smart_scholarship"):
        prize_meta.append(f"<b>USBC SMART Scholarship:</b> ${float(totals['smart_scholarship']):,.2f}")

    prize_card = ""
    if prize_meta:
        prize_card = f"""
        <div style="background-color: #064E3B; border: 1px solid #059669; border-radius: 8px; padding: 14px; margin-top: 20px; color: #ECFDF5; font-size: 14px;">
          {' &middot; '.join(prize_meta)}
        </div>
        """

    inner_content = f"""
      <div style="border-left: 3px solid #38BDF8; padding-left: 12px; margin-bottom: 16px;">
        <h3 style="margin: 0 0 4px 0; color: #FFFFFF; font-size: 19px; font-weight: 700;">
          Official Tournament Series Scoresheet
        </h3>
        <p style="margin: 0; font-size: 13px; color: #38BDF8; font-weight: 600;">
          Sanctioned Competition Performance Record
        </p>
      </div>

      <p style="font-size: 14px; color: #CBD5E1; margin-bottom: 20px;">
        Bowler: <b>{name}</b> &middot; Entering Avg: <b>{entering_avg}</b> &middot; HDCP/Game: <b>+{handicap}</b>
      </p>

      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #0F172A; border: 1px solid #334155; border-radius: 8px;">
        <thead>
          <tr style="border-bottom: 1px solid #334155;">
            <th align="left" style="padding: 10px 14px; color: #94A3B8; font-size: 12px; text-transform: uppercase;">Game</th>
            <th align="center" style="padding: 10px 14px; color: #94A3B8; font-size: 12px; text-transform: uppercase;">Scratch</th>
            <th align="center" style="padding: 10px 14px; color: #94A3B8; font-size: 12px; text-transform: uppercase;">Handicap Series</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
          <tr style="background-color: #1E293B;">
            <td style="padding: 12px 14px; font-weight: 800; color: #F8FAFC;">Series Total</td>
            <td align="center" style="padding: 12px 14px; font-weight: 800; color: #F8FAFC; font-size: 16px;">{total_scratch}</td>
            <td align="center" style="padding: 12px 14px; font-weight: 800; color: #38BDF8; font-size: 16px;">{total_handicap}</td>
          </tr>
        </tbody>
      </table>

      {prize_card}

      <p style="font-size: 13px; color: #94A3B8; margin-top: 24px; text-align: center; line-height: 1.5;">
        Thank you for competing in Cecil Harford USBC sanctioned tournaments. Good luck on the lanes!
      </p>
    """

    preview = f"Official tournament recap for {name}: Series total {total_handicap}."
    full_html = _build_email_shell(inner_content, preview_text=preview)
    return send_ptcc_mail(str(to_email), f"Tournament Scoresheet: {name} - Cecil Harford USBC", full_html)
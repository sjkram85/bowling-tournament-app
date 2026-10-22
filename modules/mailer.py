"""Outbound email for CHUSBC tournaments via Gmail SMTP."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import streamlit as st

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_ptcc_mail(to_email: str, subject: str, html_content: str) -> bool:
    """Send an HTML email; returns True on success, False if sending failed."""
    sender = st.secrets["CHUSBC_GMAIL_USER"]
    app_password = st.secrets["CHUSBC_GMAIL_APP_PASSWORD"]

    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender, app_password)
            server.sendmail(sender, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError):
        return False
    return True


def send_admin_registration_alert(applicant: dict) -> bool:
    """Tell the administrator that someone has applied for a staff account."""
    admin_email = st.secrets["ADMIN_ALERT_EMAIL"]
    rows = "".join(
        f"<tr><td><b>{label}</b></td><td>{escape(str(applicant.get(key) or '-'))}</td></tr>"
        for label, key in (
            ("Name", "display_name"),
            ("Username", "username"),
            ("Email", "email"),
            ("Center", "center_affiliation"),
            ("Requested role", "role"),
        )
    )
    html_content = f"""
    <html><body>
      <h2>New staff account awaiting approval</h2>
      <table cellpadding="6" cellspacing="0">{rows}</table>
      <p>Sign in to the Prism Tournament Control Center and open Staff Accounts to approve or reject this request.</p>
    </body></html>
    """
    return send_ptcc_mail(str(admin_email), "Prism: new staff registration awaiting approval", html_content)


def send_applicant_approval_notice(applicant_email: str, display_name: str) -> bool:
    """Confirm to an applicant that their account has been approved."""
    if not applicant_email:
        return False
    html_content = f"""
    <html><body>
      <h2>Your account is approved</h2>
      <p>Hello {escape(display_name)},</p>
      <p>Your Prism Tournament Control Center account has been approved. You can now sign in.</p>
      <p>Cecil Harford USBC</p>
    </body></html>
    """
    return send_ptcc_mail(applicant_email, "Your Prism account has been approved", html_content)


def dispatch_bowler_recap_email(bowler: dict, scores: list, totals: dict | None) -> bool:
    """Email a bowler their games, scratch/handicap totals and prize status.

    Recognized ``totals`` keys (all optional): ``scratch_total``, ``handicap_total``,
    ``place``, ``prize_status``, ``prize_amount``.
    """
    to_email = bowler.get("email")
    if not to_email:
        return False

    totals = totals or {}
    name = escape(str(bowler.get("name", "Bowler")))
    handicap = int(bowler.get("handicap") or 0)

    rows = []
    computed_scratch = 0
    for score in scores:
        game = score.get("game_number", "")
        scratch = int(score.get("scratch_score") or 0)
        computed_scratch += scratch
        rows.append(
            f"<tr><td>Game {escape(str(game))}</td><td>{scratch}</td>"
            f"<td>{scratch + handicap}</td></tr>"
        )

    total_scratch = int(totals.get("scratch_total", computed_scratch))
    total_handicap = int(totals.get("handicap_total", total_scratch + handicap * len(scores)))

    prize_lines = []
    if totals.get("place"):
        prize_lines.append(f"<li>Final place: {escape(str(totals['place']))}</li>")
    prize_lines.append(f"<li>Prize status: {escape(str(totals.get('prize_status') or 'No prize'))}</li>")
    if totals.get("prize_amount"):
        prize_lines.append(f"<li>Prize amount: ${float(totals['prize_amount']):,.2f}</li>")
    prize_html = f"<h3>Results</h3><ul>{''.join(prize_lines)}</ul>"

    html_content = f"""
    <html><body>
      <h2>Tournament Recap for {name}</h2>
      <table border="1" cellpadding="6" cellspacing="0">
        <tr><th>Game</th><th>Scratch</th><th>With Handicap</th></tr>
        {''.join(rows)}
        <tr><td><b>Total</b></td><td><b>{total_scratch}</b></td><td><b>{total_handicap}</b></td></tr>
      </table>
      {prize_html}
      <p>Thank you for bowling with Cecil Harford USBC!</p>
    </body></html>
    """
    return send_ptcc_mail(str(to_email), "Your CHUSBC Tournament Recap", html_content)

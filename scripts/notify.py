"""
notify.py — Layer 3: Gmail push notification
LinkedIn Job Intel — Anthony Chilaka

Sends all jobs in the filtered_jobs JSON to the mentee's notify_to address.
Job selection happens in Cowork chat:
  1. Claude runs Layer 2 and shows PASSED / BORDERLINE results in chat
  2. Anthony says which job numbers to push
  3. Claude writes a trimmed JSON containing only the approved jobs
  4. Anthony runs this script — it sends everything in the file, no prompt

Usage:
  python notify.py --config ../config/mentees/user2.json --jobs-file path/to/filtered_jobs.json

NOTE: Will fail with an authentication error if sender.json still contains
placeholder values.
"""

import json
import os
import sys
import argparse
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ── Config loaders ────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sender_config() -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sender_path = os.path.join(script_dir, "..", "config", "sender.json")
    sender = load_json(sender_path)

    if "PLACEHOLDER" in sender.get("sender_email", ""):
        print("\n[ERROR] sender.json still contains placeholder values.")
        print("Please create the product Gmail account and update config/sender.json.")
        sys.exit(1)

    return sender


# ── Email builder ──────────────────────────────────────────────────

def build_email(matched_jobs: list[dict], user_name: str, date_str: str) -> tuple[str, str]:
    count = len(matched_jobs)
    subject = f"[LinkedIn Job Intel] {count} matching role{'s' if count != 1 else ''} for you — {date_str}"

    rows = ""
    for job in matched_jobs:
        job_number   = job.get("job_number", "")
        title        = job.get("title", "(no title)")
        company      = job.get("company", "(company not extracted)")
        url          = job.get("url", "#")
        match_reason = job.get("match_reason", "")
        source       = job.get("source", "")
        status       = job.get("status", "")
        source_label = "LinkedIn Jobs" if source == "linkedin_jobs_api" else "LinkedIn Feed Post"
        status_colour = "#2e7d32" if status == "PASSED" else "#e65100"
        status_label  = "✅ PASSED" if status == "PASSED" else "⚠️ BORDERLINE"

        rows += f"""
        <tr>
          <td style="padding:14px 8px; border-bottom:1px solid #eee; vertical-align:top;">
            <span style="font-size:11px; color:#888; font-weight:bold;">{job_number}</span><br>
            <strong><a href="{url}" style="color:#0073b1; text-decoration:none;">{title}</a></strong><br>
            <span style="color:#555; font-size:13px;">{company}</span><br>
            <span style="color:#888; font-size:12px;">{source_label}</span>
          </td>
          <td style="padding:14px 8px; border-bottom:1px solid #eee; font-size:13px; color:#333; vertical-align:top;">
            <span style="color:{status_colour}; font-weight:bold; font-size:12px;">{status_label}</span><br><br>
            {match_reason}
          </td>
        </tr>
        """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; max-width: 720px; margin: auto;">
      <h2 style="color:#0073b1; margin-bottom:4px;">LinkedIn Job Intel</h2>
      <p style="color:#888; font-size:13px; margin-top:0;">Pushed by Anthony · {date_str}</p>
      <p>Hi {user_name},</p>
      <p>
        <strong>{count} role{'s have' if count != 1 else ' has'} been selected for you</strong>
        — all passed the global talent filter and are open to international remote candidates.
      </p>
      <p style="font-size:13px; color:#555;">
        Apply early. Roles are shared immediately after daily collection.
      </p>

      <table style="width:100%; border-collapse:collapse; margin-top:16px;">
        <thead>
          <tr style="background:#f3f3f3;">
            <th style="padding:10px 8px; text-align:left; font-size:13px; width:45%;">Role</th>
            <th style="padding:10px 8px; text-align:left; font-size:13px;">Why it matched</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>

      <p style="margin-top:28px; font-size:13px; color:#888;">
        Click the job title to go directly to the LinkedIn listing.<br>
        If a role is marked <strong>BORDERLINE</strong>, verify whether the company accepts
        international candidates before applying.
      </p>
      <p style="font-size:12px; color:#bbb; margin-top:20px;">
        LinkedIn Job Intel &middot; Powered by Claude Cowork
      </p>
    </body>
    </html>
    """

    return subject, html_body


# ── Email sender ──────────────────────────────────────────────────

def send_email(sender: dict, recipient: str, subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender["sender_email"]
    msg["To"]      = recipient

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(sender["smtp_server"], sender["smtp_port"]) as server:
        server.ehlo()
        server.starttls()
        server.login(sender["smtp_login"], sender["sender_password"])
        server.sendmail(sender["sender_email"], recipient, msg.as_string())


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Intel — Layer 3 notifier")
    parser.add_argument("--config",     required=True, help="Path to user config JSON")
    parser.add_argument("--jobs-file",  required=True, help="Path to approved jobs JSON (trimmed by Claude in Cowork)")
    args = parser.parse_args()

    user_config = load_json(args.config)
    sender      = load_sender_config()

    with open(args.jobs_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        print("No jobs found in file. Exiting.")
        return

    date_str  = datetime.date.today().strftime("%Y-%m-%d")
    user_name = user_config.get("name", "there")
    recipient = user_config.get("notify_to", "")

    if not recipient:
        print("[ERROR] No notify_to email address in user config. Exiting.")
        sys.exit(1)

    subject, html_body = build_email(jobs, user_name, date_str)

    print(f"\nSending {len(jobs)} job(s) to: {recipient} ...")

    try:
        send_email(sender, recipient, subject, html_body)
        print(f"✅ Email sent successfully to {recipient}")
        print(f"   Subject : {subject}")
        print(f"   Jobs    : {len(jobs)} pushed\n")
    except smtplib.SMTPAuthenticationError:
        print("\n[ERROR] Gmail authentication failed.")
        print("Check that sender.json has the correct App Password (not your Gmail login password).")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Failed to send email: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

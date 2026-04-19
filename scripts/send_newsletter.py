#!/usr/bin/env python3
"""
send_newsletter.py  —  Send AI Newsflash by email
==================================================
Sends the newsletter as a rich HTML email via Gmail.
Includes a "View Online" button linking to GitHub Pages.

Usage:
    python send_newsletter.py --input ai-newsflash-march-25-2026_with_images.html
"""

import argparse
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ── CONFIG — edit these ───────────────────────────────────────────────────────
GMAIL_ADDRESS  = "dana.aronovich@gmail.com"
GMAIL_APP_PASS = "jmtx ftmi zgba gfed"
GITHUB_URL     = "https://danaaro.github.io/ai-newsletter/"

# Add recipient emails here
RECIPIENTS = [
    "dana.aronovich@gmail.com",   # yourself first (test)
    # "colleague@example.com",
    # "colleague2@example.com",
]
# ─────────────────────────────────────────────────────────────────────────────


def build_email(html_content: str, subject: str) -> str:
    """Wrap the newsletter HTML with a View Online banner at the top."""
    banner = f"""
    <div style="
        background: #0A0A0F;
        text-align: center;
        padding: 16px 24px;
        font-family: Arial, sans-serif;
        font-size: 13px;
        color: #6B6B80;
        border-bottom: 1px solid rgba(255,255,255,0.08);
    ">
        Having trouble viewing this email?
        <a href="{GITHUB_URL}" style="
            color: #00D4FF;
            text-decoration: none;
            font-weight: bold;
            margin-left: 6px;
        ">View full newsletter online &rarr;</a>
    </div>
    """

    # Insert banner right after <body>
    if "<body" in html_content:
        insert_at = html_content.find(">", html_content.find("<body")) + 1
        return html_content[:insert_at] + banner + html_content[insert_at:]

    return banner + html_content


def extract_subject(html_content: str, fallback: str) -> str:
    """Pull subject from <title> tag."""
    import re
    match = re.search(r"<title>(.*?)</title>", html_content, re.IGNORECASE)
    if match:
        # Strip emoji and clean up: "🔥 AI Newsflash — March 25, 2026" -> keep as-is
        return match.group(1).strip()
    return fallback


def send(html_path: Path) -> None:
    html_content = html_path.read_text(encoding="utf-8")
    subject = extract_subject(html_content, f"AI Newsflash — {html_path.stem}")
    body_html = build_email(html_content, subject)

    print(f"Subject  : {subject}")
    print(f"From     : {GMAIL_ADDRESS}")
    print(f"To       : {', '.join(RECIPIENTS)}")
    print(f"Sending...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Dana Aronovich <{GMAIL_ADDRESS}>"
    msg["To"]      = ", ".join(RECIPIENTS)

    # Plain text fallback
    plain = f"View the full newsletter online: {GITHUB_URL}"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    import ssl
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
        server.sendmail(GMAIL_ADDRESS, RECIPIENTS, msg.as_string())

    print(f"Done! Sent to {len(RECIPIENTS)} recipient(s).")


def main():
    parser = argparse.ArgumentParser(description="Send AI Newsflash newsletter by email")
    parser.add_argument("--input", required=True, help="Newsletter HTML file to send")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        sys.exit(f"Error: file not found: {path}")

    send(path)


if __name__ == "__main__":
    main()

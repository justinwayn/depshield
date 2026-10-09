"""Weekly risk digest: summarizes vendor news, uptime stats, and riskiest dependency.

Sends via free Gmail SMTP (smtplib). Configure in the web UI Settings page or env:
    DEPSHIELD_SMTP_USER, DEPSHIELD_SMTP_PASS (Gmail app password), DEPSHIELD_DIGEST_TO

Run weekly, e.g.:  0 9 * * 1 /path/to/venv/bin/python /path/to/app/digest.py --send
Preview without sending:  python digest.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import db
from vendors import VENDOR_CATALOG

META = {v["key"]: v for v in VENDOR_CATALOG}
WEEK = 7 * 86400


def build_digest() -> tuple[str, str]:
    """Returns (subject, html_body)."""
    now = db.now()
    since = now - WEEK
    vendors = db.list_vendors(enabled_only=True)

    rows = []
    riskiest = None
    for v in vendors:
        from checks import risk_score

        r = risk_score(v, META.get(v["key"]))
        up = r["uptime_7d"]
        incs = db.incidents_since(v["id"], since)
        rows.append(
            {
                "name": v["name"],
                "category": v["category"],
                "score": r["score"],
                "level": r["level"],
                "uptime": up,
                "incidents": len(incs),
                "reasons": r["reasons"],
            }
        )
        if riskiest is None or r["score"] > riskiest["score"]:
            riskiest = rows[-1]

    alerts = db.list_alerts(limit=20)
    new_alerts = [a for a in alerts if a["created_at"] >= since]
    domain_up = db.domain_uptime_pct(since)
    domain = db.get_setting("domain") or "(not set)"

    date_str = datetime.now().strftime("%b %d, %Y")
    subject = f"DepShield weekly risk digest — {date_str}"

    color = {"LOW": "#2ea043", "MEDIUM": "#d29922", "HIGH": "#f85149"}
    parts = [f"<h2>🛡️ DepShield weekly digest — {date_str}</h2>"]
    parts.append(f"<p>Your domain <b>{domain}</b>: 7-day uptime "
                 f"<b>{domain_up if domain_up is not None else 'n/a'}%</b></p>")
    if riskiest:
        parts.append(
            f"<p>⚠️ <b>Riskiest dependency: {riskiest['name']}</b> "
            f"({riskiest['score']}/100 — {riskiest['level']})</p>"
        )
    parts.append("<table border='1' cellpadding='6' cellspacing='0'>"
                 "<tr><th>Vendor</th><th>Risk</th><th>7d health</th><th>Incidents</th></tr>")
    for r_ in sorted(rows, key=lambda x: -x["score"]):
        parts.append(
            f"<tr><td><b>{r_['name']}</b><br><small>{r_['category']}</small></td>"
            f"<td style='color:{color[r_['level']]}'><b>{r_['score']} ({r_['level']})</b></td>"
            f"<td>{r_['uptime'] if r_['uptime'] is not None else 'n/a'}%</td>"
            f"<td>{r_['incidents']}</td></tr>"
        )
    parts.append("</table>")
    parts.append(f"<h3>Alerts this week ({len(new_alerts)})</h3>")
    if new_alerts:
        parts.append("<ul>" + "".join(f"<li><b>[{a['kind']}]</b> {a['title']}</li>" for a in new_alerts) + "</ul>")
    else:
        parts.append("<p>None — quiet week. 🎉</p>")
    parts.append("<p><small>DepShield runs on your own machine. Your data never leaves it.</small></p>")
    return subject, "\n".join(parts)


def send_digest(to_addr: str | None = None) -> bool:
    user = os.environ.get("DEPSHIELD_SMTP_USER") or db.get_setting("smtp_user")
    pw = os.environ.get("DEPSHIELD_SMTP_PASS") or db.get_setting("smtp_pass")
    to = to_addr or os.environ.get("DEPSHIELD_DIGEST_TO") or db.get_setting("digest_to")
    if not (user and pw and to):
        print("SMTP not configured: need smtp_user, smtp_pass (Gmail app password), digest_to.")
        print("Set them in the web UI Settings page or via env vars.")
        return False
    subject, html = build_digest()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    print(f"Digest sent to {to}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--to", default=None)
    args = ap.parse_args()
    db.init_db()
    if args.dry_run:
        subject, html = build_digest()
        print("SUBJECT:", subject)
        print(html[:3000])
    elif args.send:
        send_digest(args.to)
    else:
        ap.print_help()

# 🛡️ DepShield — Vendor-risk radar for one-person SaaS

> Your SaaS has one employee. Make sure no vendor can fire them.

DepShield watches the vendors your business depends on (CDN, DNS, payments, email,
hosting), scores each one's risk, alerts you to incidents and terms-of-service changes,
and keeps a zero-cost exit plan ready for every dependency.

**100% free and self-hosted.** Your data never leaves your machine. No paid APIs,
no cloud services, no accounts.

## Quick start

```bash
cd app
chmod +x run.sh
./run.sh
# open http://127.0.0.1:5057
```

First run creates `depshield.db` (SQLite) and seeds the 5-vendor catalog:
Cloudflare, Stripe, AWS, SendGrid, Google Cloud — each with live status monitoring,
a risk score, and a curated exit playbook.

## What it does

| Feature | How |
|---|---|
| Vendor dependency map | Dashboard with per-vendor risk scores (0–100, transparent reasons) |
| Multi-point status checks | Polls each vendor's public status API every 15 min via cron |
| Incident alerts | New incidents + degradations land in the Alerts feed instantly |
| Policy-change watcher | Hashes vendor ToS pages, alerts on content change (`checks.py --policy`) |
| Exit-plan playbooks | Zero-cost alternatives + migration notes per vendor |
| Weekly risk digest | HTML email via free Gmail SMTP (`digest.py --send`) |
| Your own domain | Optional uptime check alongside vendors (Settings page) |

## Scheduling (cron)

```cron
# vendor status checks every 15 minutes
*/15 * * * * /path/to/app/venv/bin/python /path/to/app/checks.py --once
# weekly digest, Mondays 9am
0 9 * * 1 /path/to/app/venv/bin/python /path/to/app/digest.py --send
# terms-of-service diff watch, Sundays (heavier, weekly is enough)
0 8 * * 0 /path/to/app/venv/bin/python /path/to/app/checks.py --once --policy
```

## Configuration

All in the web UI under **Settings**, or via env vars:

- `DEPSHIELD_DB` — SQLite path (default `./depshield.db`)
- `DEPSHIELD_PORT` — web port (default `5057`)
- `DEPSHIELD_SMTP_USER` / `DEPSHIELD_SMTP_PASS` — Gmail + app password
- `DEPSHIELD_DIGEST_TO` — where the weekly digest goes

## API

- `GET /api/status` → JSON: vendor risk scores + unread alert count

## Project layout

```
app/
  app.py        # Flask web UI (dashboard, vendors, playbooks, alerts, settings)
  checks.py     # check engine: status APIs, incidents, ToS diff, risk scores
  digest.py     # weekly risk digest email builder + Gmail SMTP sender
  db.py         # SQLite schema + helpers
  vendors.py    # 5-vendor catalog: status APIs, base risk, exit playbooks
  templates/    # Jinja pages (dark theme)
  static/       # style.css
  run.sh        # one-command launcher (builds venv on first run)
```

## Roadmap

- [ ] Uptime checks from 3+ geographic vantage points (currently single-origin)
- [ ] SMS alerts (Twilio free tier) for HIGH-risk events
- [ ] Historical policy-change archive (hosted tier feature)
- [ ] More vendors in catalog (Hetzner, Paddle, Resend, Bunny)
- [ ] Optional local-Ollama incident summarization (still $0)

## License

MIT — free forever for the indie community.

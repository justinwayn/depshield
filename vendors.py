"""Seed catalog of the 5 major vendors DepShield watches out of the box.

Each entry carries:
  - status_api: a free public JSON/RSS endpoint for live incident data
  - base_risk: 0-100 score from public ban/price-hike/outage history
  - playbook: zero-cost exit plan (alternatives + migration notes)
"""
from __future__ import annotations

VENDOR_CATALOG = [
    {
        "key": "cloudflare",
        "name": "Cloudflare",
        "category": "CDN / DNS",
        "status_api": "https://www.cloudflarestatus.com/api/v2/summary.json",
        "status_page": "https://www.cloudflarestatus.com",
        "terms_url": "https://www.cloudflare.com/terms/",
        "base_risk": 75,
        "risk_notes": (
            "Documented history of banning paying customers with little warning "
            "(HN: 'Small SaaS banned by Cloudflare after 4 years'). Single point "
            "of failure for DNS + CDN + WAF for most indie SaaS."
        ),
        "playbook": {
            "alternatives": [
                "Bunny CDN — pay-as-you-go, ~$0.01/GB, no ban-happy abuse team",
                "Self-hosted nginx + certbot on Hetzner (~$5/mo VPS)",
                "DNS: deSEC (free, EU non-profit) or Cloudflare-free registrars",
            ],
            "migration_notes": (
                "1. Lower DNS TTL to 300s a week before. 2. Mirror cache rules to "
                "Bunny pull zones. 3. Move DNS to deSEC, keep Cloudflare as backup "
                "nameserver during cutover. 4. Terminate after 72h clean."
            ),
        },
    },
    {
        "key": "stripe",
        "name": "Stripe",
        "category": "Payments",
        "status_api": "https://api.stripe.com/v1/charges?limit=1",
        "status_page": "https://status.stripe.com",
        "terms_url": "https://stripe.com/legal/ssa",
        "base_risk": 60,
        "risk_notes": (
            "Account holds/freezes are the #1 killer story on Indie Hackers. "
            "Payout holds of 7-120 days with opaque review. No real human support "
            "for sub-$1M accounts."
        ),
        "playbook": {
            "alternatives": [
                "Paddle — merchant of record, handles tax/VAT, friendlier reviews",
                "Lemon Squeezy — MoR, fast onboarding for digital products",
                "Polar — open-source-friendly MoR for dev tools",
            ],
            "migration_notes": (
                "1. Open Paddle/Lemon Squeezy account BEFORE you need it. "
                "2. Dual-run checkout for 2 weeks. 3. Export customer + "
                "subscription data via Stripe API weekly (automated backup). "
                "4. Keep 2 months operating cash outside Stripe."
            ),
        },
    },
    {
        "key": "aws",
        "name": "AWS",
        "category": "Hosting",
        "status_api": "https://status.aws.amazon.com/rss/all.rss",
        "status_page": "https://status.aws.amazon.com",
        "terms_url": "https://aws.amazon.com/agreement/",
        "base_risk": 40,
        "risk_notes": (
            "Rarely bans, but surprise bills and region outages are the risk. "
            "Free-tier expirations silently convert to paid. Data egress fees "
            "make leaving expensive — by design."
        ),
        "playbook": {
            "alternatives": [
                "Hetzner — ~1/3 the price, generous free egress, EU/US regions",
                "DigitalOcean — simpler pricing, good indie track record",
                "Self-hosted mini-PC / used server for staging",
            ],
            "migration_notes": (
                "1. Containerize everything (docker compose) so the app is portable. "
                "2. Replicate data to Hetzner with nightly pg_dump/rsync. "
                "3. Watch egress: keep backups incremental. 4. Kill unused "
                "EBS snapshots and NAT gateways — the silent bill killers."
            ),
        },
    },
    {
        "key": "sendgrid",
        "name": "SendGrid (Twilio)",
        "category": "Email",
        "status_api": "https://status.sendgrid.com/api/v2/summary.json",
        "status_page": "https://status.sendgrid.com",
        "terms_url": "https://www.twilio.com/en-us/legal/tos",
        "base_risk": 50,
        "risk_notes": (
            "Aggressive automated suspensions for bounce/spam signals; shared-IP "
            "reputation damage from other tenants. Deliverability drops are "
            "silent until users complain."
        ),
        "playbook": {
            "alternatives": [
                "Postmark — best deliverability for transactional, strict but fair",
                "Resend — modern API, generous free tier for devs",
                "Amazon SES — $0.10/1k emails, rock solid if you warm up",
                "Self-hosted Postal on a Hetzner VPS for full control",
            ],
            "migration_notes": (
                "1. Warm the new provider: start with 10% of volume. "
                "2. Set up SPF/DKIM/DMARC on the new domain path first. "
                "3. Keep SendGrid as fallback for 30 days. 4. Export suppression "
                "lists so you don't re-mail bounces."
            ),
        },
    },
    {
        "key": "google",
        "name": "Google Cloud / Workspace",
        "category": "Hosting / Email",
        "status_api": "https://status.cloud.google.com/incidents.json",
        "status_page": "https://status.cloud.google.com",
        "terms_url": "https://cloud.google.com/terms/",
        "base_risk": 35,
        "risk_notes": (
            "Lower ban risk, higher lock-in risk: Workspace + GCP + Firebase form "
            "a gravity well. Price changes (Maps API 2018-style) are the "
            "historical pattern, not bans."
        ),
        "playbook": {
            "alternatives": [
                "Email: Fastmail or Proton Mail (Workspace replacement)",
                "Hosting: Hetzner / Fly.io for containers",
                "Auth: self-hosted Authentik / PocketBase instead of Firebase Auth",
            ],
            "migration_notes": (
                "1. Decouple auth first — it's the hardest lock-in. "
                "2. Move email MX records with a weekend cutover. "
                "3. Export Firebase data to Postgres early; don't wait. "
                "4. Audit GCP billing alerts — set a hard budget cap today."
            ),
        },
    },
]


def get_vendor(key: str) -> dict | None:
    for v in VENDOR_CATALOG:
        if v["key"] == key:
            return v
    return None

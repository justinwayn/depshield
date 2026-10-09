"""DepShield check engine: polls vendor status APIs, records uptime, ingests incidents.

Run on a schedule, e.g.:  */15 * * * * /path/to/venv/bin/python /path/to/app/checks.py
Or:  python checks.py --once
"""
from __future__ import annotations

import argparse
import hashlib
import time
import xml.etree.ElementTree as ET

import requests

import db
from vendors import VENDOR_CATALOG

HTTP_TIMEOUT = 15
UA = {"User-Agent": "DepShield/0.1 (vendor-risk radar; +https://github.com/justinwayn)"}


def _get(url):
    t0 = time.time()
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers=UA)
        ms = int((time.time() - t0) * 1000)
        return r, ms, None
    except Exception as e:  # network failure = check failure
        ms = int((time.time() - t0) * 1000)
        return None, ms, str(e)


# ---------- statuspage.io style APIs (Cloudflare, Stripe, SendGrid) ----------
def poll_statuspage(vendor_row) -> tuple[bool, int, str, list]:
    """Returns (ok, latency_ms, detail, incidents)."""
    r, ms, err = _get(vendor_row["status_api"])
    if err or r is None:
        return False, ms, f"status API unreachable: {err}", []
    if r.status_code != 200:
        return False, ms, f"status API HTTP {r.status_code}", []
    try:
        data = r.json()
    except Exception as e:
        return False, ms, f"bad JSON: {e}", []

    status = data.get("status", {})
    indicator = status.get("indicator", "unknown")
    desc = status.get("description", "")
    ok = indicator in ("none",)
    detail = f"{indicator}: {desc}".strip(": ")

    incidents = []
    for inc in data.get("incidents", []) or []:
        incidents.append(
            {
                "external_id": str(inc.get("id", inc.get("shortlink", ""))),
                "title": inc.get("name", "Untitled incident"),
                "impact": inc.get("impact"),
                "started_at": _parse_iso(inc.get("created_at")),
                "resolved": inc.get("status") in ("resolved", "postmortem"),
                "url": inc.get("shortlink"),
            }
        )
    return ok, ms, detail, incidents


# ---------- Google Cloud status JSON ----------
def poll_google(vendor_row):
    r, ms, err = _get(vendor_row["status_api"])
    if err or r is None:
        return False, ms, f"status API unreachable: {err}", []
    try:
        data = r.json()
    except Exception as e:
        return False, ms, f"bad JSON: {e}", []
    incidents = []
    active = 0
    for inc in data if isinstance(data, list) else []:
        end = inc.get("end")
        resolved = bool(end)
        if not resolved:
            active += 1
        updates = inc.get("updates") or []
        first = updates[-1] if updates else {}
        incidents.append(
            {
                "external_id": str(inc.get("id", "")),
                "title": inc.get("summary") or first.get("text", "Google Cloud incident")[:120],
                "impact": inc.get("severity"),
                "started_at": _parse_iso(inc.get("begin")),
                "resolved": resolved,
                "url": inc.get("uri"),
            }
        )
    ok = active == 0
    detail = "all clear" if ok else f"{active} active incident(s)"
    return ok, ms, detail, incidents


# ---------- Stripe: status page blocks API scraping, so use the API itself ----------
def poll_stripe(vendor_row):
    """Stripe's statuspage API is not publicly reachable; a 401 from the real
    API endpoint proves the platform is up (no key = invalid_request_error)."""
    r, ms, err = _get("https://api.stripe.com/v1/charges?limit=1")
    if err or r is None:
        return False, ms, f"Stripe API unreachable: {err}", []
    try:
        body = r.json()
        err_type = (body.get("error") or {}).get("type", "")
    except Exception:
        err_type = ""
    if r.status_code == 401 and err_type == "invalid_request_error":
        return True, ms, "API live (auth challenge as expected)", []
    if r.status_code < 500:
        return True, ms, f"API responding (HTTP {r.status_code})", []
    return False, ms, f"Stripe API HTTP {r.status_code}", []


# ---------- AWS status RSS ----------
def poll_aws_rss(vendor_row):
    r, ms, err = _get(vendor_row["status_api"])
    if err or r is None:
        return False, ms, f"RSS unreachable: {err}", []
    try:
        root = ET.fromstring(r.text)
    except Exception as e:
        return False, ms, f"bad RSS: {e}", []
    incidents = []
    cutoff = int(time.time()) - 72 * 3600  # only events from the last 72h count
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if "[RESOLVED]" in title.upper():
            continue
        pub_ts = _parse_rfc822(item.findtext("pubDate") or "")
        if pub_ts and pub_ts < cutoff:
            continue
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title)[:200]
        # AWS RSS only lists CURRENT issues; treat items published in last 48h as active-ish
        incidents.append(
            {
                "external_id": hashlib.sha1(guid.encode()).hexdigest()[:16],
                "title": title[:200],
                "impact": None,
                "started_at": _parse_rfc822(pub),
                "resolved": False,
                "url": link,
            }
        )
    ok = len(incidents) == 0
    detail = "all clear" if ok else f"{len(incidents)} issue(s) on AWS status feed"
    return ok, ms, detail, incidents


# ---------- ToS / policy page diff watcher ----------
def poll_policy_pages(vendor_row, vendor_meta) -> list:
    """Hash vendor terms pages; alert when content changes. Returns alert titles."""
    changed = []
    terms_url = (vendor_meta or {}).get("terms_url")
    if not terms_url:
        return changed
    r, ms, err = _get(terms_url)
    if err or r is None or r.status_code != 200:
        return changed
    h = hashlib.sha256(r.text.encode("utf-8", "ignore")).hexdigest()
    prev = db.last_snapshot(vendor_row["id"], "terms")
    db.save_snapshot(vendor_row["id"], "terms", terms_url, h)
    if prev and prev["content_hash"] != h:
        changed.append(vendor_row["name"])
    return changed


# ---------- helpers ----------
def _parse_iso(s):
    if not s:
        return None
    try:
        from datetime import datetime

        s2 = s.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s2).timestamp())
    except Exception:
        return None


def _parse_rfc822(s):
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        return None


POLLERS = {
    "cloudflare": poll_statuspage,
    "stripe": poll_stripe,
    "sendgrid": poll_statuspage,
    "google": poll_google,
    "aws": poll_aws_rss,
}


def check_vendor(vendor_row, vendor_meta, watch_policy=False):
    key = vendor_row["key"]
    poller = POLLERS.get(key, poll_statuspage)
    ok, ms, detail, incidents = poller(vendor_row)
    db.record_check(vendor_row["id"], ok, ms, detail)

    new_count = 0
    for inc in incidents:
        is_new = db.record_incident(
            vendor_row["id"],
            inc["external_id"] or hashlib.sha1(inc["title"].encode()).hexdigest()[:12],
            inc["title"],
            inc.get("impact"),
            inc.get("started_at"),
            inc.get("url"),
        )
        if inc.get("resolved"):
            db.mark_incident_resolved(vendor_row["id"], inc["external_id"])
        if is_new:
            new_count += 1
            db.add_alert(
                "incident",
                f"New {vendor_row['name']} incident: {inc['title'][:90]}",
                f"Impact: {inc.get('impact') or 'unknown'}\n{inc.get('url') or ''}",
            )
    if not ok:
        db.add_alert(
            "outage",
            f"{vendor_row['name']} reports degraded status",
            detail,
        )
    if watch_policy:
        for name in poll_policy_pages(vendor_row, vendor_meta):
            db.add_alert(
                "policy",
                f"{name} terms-of-service page changed",
                "The vendor's legal terms page content changed since last check. Review it.",
            )
    return {"vendor": vendor_row["name"], "ok": ok, "latency_ms": ms, "detail": detail,
            "new_incidents": new_count, "total_incidents": len(incidents)}


def check_domain():
    domain = db.get_setting("domain")
    if not domain:
        return {"skipped": True}
    url = domain if domain.startswith("http") else f"https://{domain}"
    r, ms, err = _get(url)
    ok = err is None and r is not None and r.status_code < 500
    db.record_domain_check(ok, ms)
    if not ok:
        db.add_alert("domain", f"Your domain is unreachable: {domain}", err or f"HTTP {r.status_code if r else '?'}")
    return {"domain": domain, "ok": ok, "latency_ms": ms}


def risk_score(vendor_row, vendor_meta) -> dict:
    """Transparent 0-100 risk score."""
    base = (vendor_meta or {}).get("base_risk", 50)
    score = base
    reasons = [f"Base risk {base}/100 — {(vendor_meta or {}).get('risk_notes', '')[:110]}"]
    now = int(time.time())
    recent = db.incidents_since(vendor_row["id"], now - 7 * 86400)
    day = db.incidents_since(vendor_row["id"], now - 86400)
    if day:
        score += 15
        reasons.append(f"+15: {len(day)} incident(s) in the last 24h")
    elif recent:
        score += 10
        reasons.append(f"+10: {len(recent)} incident(s) in the last 7 days")
    up = db.uptime_pct(vendor_row["id"], now - 7 * 86400)
    if up is not None and up < 99.0:
        score += 10
        reasons.append(f"+10: 7-day status-page health {up}% (< 99%)")
    score = max(0, min(100, score))
    level = "LOW" if score < 40 else "MEDIUM" if score < 65 else "HIGH"
    return {"score": score, "level": level, "reasons": reasons, "uptime_7d": up}


def run_all(watch_policy=False):
    db.init_db()
    # ensure catalog vendors exist
    for v in VENDOR_CATALOG:
        db.upsert_vendor(v["key"], v["name"], v["category"], v["status_api"], v["status_page"])
    meta = {v["key"]: v for v in VENDOR_CATALOG}
    results = []
    for row in db.list_vendors(enabled_only=True):
        try:
            results.append(check_vendor(row, meta.get(row["key"]), watch_policy))
        except Exception as e:
            db.record_check(row["id"], False, None, f"checker error: {e}")
            results.append({"vendor": row["name"], "ok": False, "detail": str(e)})
    results.append(check_domain())
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one check cycle")
    ap.add_argument("--policy", action="store_true", help="also diff terms-of-service pages")
    args = ap.parse_args()
    out = run_all(watch_policy=args.policy)
    for r in out:
        print(r)

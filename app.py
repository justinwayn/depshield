"""DepShield web UI — vendor-risk radar dashboard.

Run:  ./run.sh        (or: ./venv/bin/python app.py)
Then:  http://127.0.0.1:5057
"""
from __future__ import annotations

import os
import threading
from datetime import datetime

from flask import Flask, redirect, render_template, request, url_for, jsonify

import db
from vendors import VENDOR_CATALOG, get_vendor
from checks import run_all, risk_score

app = Flask(__name__)
META = {v["key"]: v for v in VENDOR_CATALOG}


def fmt_ts(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


app.jinja_env.filters["ts"] = fmt_ts


def ensure_seed():
    db.init_db()
    for v in VENDOR_CATALOG:
        db.upsert_vendor(v["key"], v["name"], v["category"], v["status_api"], v["status_page"])


@app.route("/")
def dashboard():
    vendors = db.list_vendors()
    cards = []
    for v in vendors:
        r = risk_score(v, META.get(v["key"]))
        cards.append({**v, **r})
    cards.sort(key=lambda c: -c["score"])
    alerts = db.list_alerts(limit=10)
    domain = db.get_setting("domain")
    domain_up = db.domain_uptime_pct(db.now() - 7 * 86400)
    return render_template(
        "dashboard.html",
        cards=cards,
        alerts=alerts,
        unread=db.unread_count(),
        domain=domain,
        domain_up=domain_up,
    )


@app.route("/vendors/<int:vendor_id>")
def vendor_detail(vendor_id):
    v = db.get_vendor_row(vendor_id)
    if not v:
        return "Vendor not found", 404
    meta = META.get(v["key"], {})
    r = risk_score(v, meta)
    checks = db.recent_checks(vendor_id, 30)
    incidents = db.list_incidents(vendor_id, 20)
    playbook = (meta.get("playbook") or {})
    return render_template(
        "vendor.html",
        v=v,
        risk=r,
        checks=checks,
        incidents=incidents,
        playbook=playbook,
        risk_notes=meta.get("risk_notes", ""),
        status_page=v["status_page"],
    )


@app.route("/vendors/add", methods=["GET", "POST"])
def vendor_add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "Other").strip() or "Other"
        status_api = request.form.get("status_api", "").strip() or None
        status_page = request.form.get("status_page", "").strip() or None
        if name:
            key = "custom-" + name.lower().replace(" ", "-")
            db.upsert_vendor(key, name, category, status_api, status_page)
        return redirect(url_for("dashboard"))
    catalog_keys = {v["key"] for v in db.list_vendors()}
    available = [v for v in VENDOR_CATALOG if v["key"] not in catalog_keys]
    return render_template("add.html", available=available)


@app.route("/vendors/<int:vendor_id>/toggle", methods=["POST"])
def vendor_toggle(vendor_id):
    v = db.get_vendor_row(vendor_id)
    if v:
        db.set_vendor_enabled(vendor_id, not v["enabled"])
    return redirect(url_for("dashboard"))


@app.route("/vendors/<int:vendor_id>/delete", methods=["POST"])
def vendor_delete(vendor_id):
    db.delete_vendor(vendor_id)
    return redirect(url_for("dashboard"))


@app.route("/playbooks")
def playbooks():
    vendors = db.list_vendors()
    books = []
    for v in vendors:
        meta = META.get(v["key"], {})
        if meta.get("playbook"):
            books.append({"vendor": v, "playbook": meta["playbook"],
                          "risk_notes": meta.get("risk_notes", "")})
    return render_template("playbooks.html", books=books, unread=db.unread_count())


@app.route("/alerts")
def alerts():
    db.mark_alerts_read()
    return render_template("alerts.html", alerts=db.list_alerts(100), unread=0)


@app.route("/check-now", methods=["POST"])
def check_now():
    def _run():
        run_all()

    threading.Thread(target=_run, daemon=True).start()
    return redirect(url_for("dashboard"))


@app.route("/api/status")
def api_status():
    vendors = db.list_vendors(enabled_only=True)
    out = []
    for v in vendors:
        r = risk_score(v, META.get(v["key"]))
        out.append({"name": v["name"], "score": r["score"], "level": r["level"]})
    return jsonify({"vendors": out, "unread_alerts": db.unread_count()})


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for k in ("domain", "digest_to", "smtp_user", "smtp_pass"):
            val = request.form.get(k, "").strip()
            if val or k == "domain":
                db.set_setting(k, val)
        return redirect(url_for("settings"))
    s = {k: db.get_setting(k, "") for k in ("domain", "digest_to", "smtp_user", "smtp_pass")}
    return render_template("settings.html", s=s, unread=db.unread_count())


@app.route("/digest-preview")
def digest_preview():
    from digest import build_digest

    subject, html = build_digest()
    return f"<h3>{subject}</h3><hr>" + html


ensure_seed()

if __name__ == "__main__":
    port = int(os.environ.get("DEPSHIELD_PORT", "5057"))
    app.run(host="127.0.0.1", port=port, debug=False)

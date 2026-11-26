"""
web.py — Admin dashboard (Flask)
Routes:
  GET  /          → login page
  POST /login     → authenticate
  GET  /dashboard → control panel
  POST /save      → save config (admins, groups, cookies)
  POST /start     → start bot subprocess
  POST /stop      → stop bot subprocess
  GET  /status    → JSON bot status
  GET  /logout    → clear session
"""

import os
import json
import subprocess
import signal
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
)

from config import DASHBOARD_PASSWORD, PORT, DATA_FILE

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "s3cr3t-change-in-prod")

bot_process: subprocess.Popen | None = None
ENV_FILE = ".env.runtime"


# ── auth decorator ────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ── helpers ───────────────────────────────────────────────────
def read_env() -> dict:
    env = {}
    if Path(ENV_FILE).exists():
        for line in Path(ENV_FILE).read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def write_env(data: dict):
    lines = [f'{k}={v}' for k, v in data.items()]
    Path(ENV_FILE).write_text("\n".join(lines))


def bot_running() -> bool:
    global bot_process
    if bot_process is None:
        return False
    return bot_process.poll() is None


def read_stats() -> dict:
    if not Path(DATA_FILE).exists():
        return {}
    try:
        return json.loads(Path(DATA_FILE).read_text())
    except Exception:
        return {}


# ── routes ────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    if session.get("authed"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == DASHBOARD_PASSWORD:
            session["authed"] = True
            return redirect(url_for("dashboard"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    env = read_env()
    stats = read_stats()
    warnings = []
    if not env.get("ADMIN_USERNAMES"):
        warnings.append("No admin usernames configured.")
    if not env.get("GROUP_IDS"):
        warnings.append("No group IDs configured.")

    today_key = datetime.now().strftime("%Y-%m-%d")
    today_data = stats.get("daily_stats", {}).get(today_key, {})
    total_msgs = sum(today_data.values())
    active_users = len(today_data)
    km = stats.get("known_members", {})
    members_tracked = sum(len(v) for v in km.values())

    return render_template(
        "dashboard.html",
        env=env,
        stats=stats,
        bot_running=bot_running(),
        warnings=warnings,
        today_key=today_key,
        total_msgs=total_msgs,
        active_users=active_users,
        members_tracked=members_tracked,
    )


@app.route("/save", methods=["POST"])
@login_required
def save_config():
    admins_raw = request.form.get("admins", "")
    groups_raw = request.form.get("groups", "")
    cookies = request.form.get("cookies", "")

    # enforce caps
    admins = [a.strip() for a in admins_raw.split(",") if a.strip()][:5]
    groups = [g.strip() for g in groups_raw.split(",") if g.strip()][:3]

    env = read_env()
    env["ADMIN_USERNAMES"] = ",".join(admins)
    env["GROUP_IDS"] = ",".join(groups)
    if cookies.strip():
        env["IG_COOKIES_JSON"] = cookies.strip()

    write_env(env)
    return redirect(url_for("dashboard"))


@app.route("/start", methods=["POST"])
@login_required
def start_bot():
    global bot_process
    if bot_running():
        return redirect(url_for("dashboard"))

    env = {**os.environ}
    # inject runtime env
    for k, v in read_env().items():
        env[k] = v

    bot_process = subprocess.Popen(
        ["python", "bot.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return redirect(url_for("dashboard"))


@app.route("/stop", methods=["POST"])
@login_required
def stop_bot():
    global bot_process
    if bot_process and bot_process.poll() is None:
        bot_process.send_signal(signal.SIGTERM)
        bot_process.wait(timeout=5)
    bot_process = None
    return redirect(url_for("dashboard"))


@app.route("/status")
@login_required
def status():
    stats = read_stats()
    return jsonify(
        {
            "bot_running": bot_running(),
            "daily_stats": stats.get("daily_stats", {}),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

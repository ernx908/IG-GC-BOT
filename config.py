"""
config.py — read all settings from environment variables.
Set these in Render dashboard → Environment.
"""

import os
import json

# ── Bot session ───────────────────────────────────────────────
BOT_SESSION_FILE = os.environ.get("BOT_SESSION_FILE", "session.json")

# ── Admin usernames (max 5) ───────────────────────────────────
# Comma-separated: "admin1,admin2,admin3"
_admins_raw = os.environ.get("ADMIN_USERNAMES", "")
ADMIN_USERNAMES: list[str] = [
    a.strip() for a in _admins_raw.split(",") if a.strip()
][:5]   # hard cap at 5

# ── Group thread IDs (max 3) ──────────────────────────────────
# Comma-separated Instagram DM thread IDs
_groups_raw = os.environ.get("GROUP_IDS", "")
GROUP_IDS: list[str] = [
    g.strip() for g in _groups_raw.split(",") if g.strip()
][:3]   # hard cap at 3

# ── Persistence ───────────────────────────────────────────────
DATA_FILE = os.environ.get("DATA_FILE", "bot_data.json")

# ── Web dashboard port ────────────────────────────────────────
PORT = int(os.environ.get("PORT", 5000))

# ── Dashboard secret password ─────────────────────────────────
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme123")

# ── Instagram cookies JSON (optional, can paste in dashboard) ─
IG_COOKIES_JSON = os.environ.get("IG_COOKIES_JSON", "")


def validate():
    errors = []
    if len(ADMIN_USERNAMES) == 0:
        errors.append("No admin usernames set (ADMIN_USERNAMES env var).")
    if len(GROUP_IDS) == 0:
        errors.append("No group IDs set (GROUP_IDS env var).")
    if DASHBOARD_PASSWORD == "changeme123":
        errors.append("DASHBOARD_PASSWORD is still default — change it!")
    return errors

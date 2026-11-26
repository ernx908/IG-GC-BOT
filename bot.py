"""
Instagram GC Bot — full runtime
Handles: welcome back (12h cooldown), new member welcome, admin commands,
         keyword triggers, scheduled messages, /send_gc DM relay.
"""

import asyncio
import json
import os
import re
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError

from config import (
    BOT_SESSION_FILE,
    ADMIN_USERNAMES,
    GROUP_IDS,
    DATA_FILE,
    PORT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("gcbot")

# ─────────────────────────── state ───────────────────────────
# welcome_back_last[user_id] = unix timestamp of last welcome-back
welcome_back_last: dict[str, float] = {}

# message count for /total: { "2024-01-01": { user_id: count } }
daily_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

# members who have been in gc (to distinguish new vs returning)
known_members: dict[str, set] = defaultdict(set)   # thread_id -> {user_id}

# /bad targets: { victim_user_id: bad_phrase }
bad_targets: dict[str, str] = {}

# spam state: { thread_id: asyncio.Task }
spam_tasks: dict[str, asyncio.Task] = {}

# stop flags for /bad per user
bad_stop: dict[str, bool] = {}

cl = Client()


# ─────────────────────────── session ─────────────────────────
def load_session(cookie_json: str | None = None) -> bool:
    """
    Load session from saved file or from raw cookie JSON pasted into env.
    cookie_json = raw Firefox cookie export (list of dicts with name/value).
    """
    if Path(BOT_SESSION_FILE).exists():
        try:
            cl.load_settings(BOT_SESSION_FILE)
            cl.get_timeline_feed()          # ping to validate
            log.info("Session loaded from file.")
            return True
        except Exception as e:
            log.warning(f"Saved session invalid: {e}")

    raw = cookie_json or os.environ.get("IG_COOKIES_JSON")
    if raw:
        try:
            cookies = json.loads(raw)
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            cl.set_settings({})
            cl.set_cookies(cookie_dict)
            cl.get_timeline_feed()
            cl.dump_settings(BOT_SESSION_FILE)
            log.info("Session loaded from cookie JSON.")
            return True
        except Exception as e:
            log.error(f"Cookie login failed: {e}")

    return False


# ─────────────────────────── helpers ─────────────────────────
def now_ts() -> float:
    return time.time()


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def is_admin(username: str) -> bool:
    return username.lower() in [a.lower() for a in ADMIN_USERNAMES]


def save_data():
    Path(DATA_FILE).write_text(
        json.dumps(
            {
                "welcome_back_last": welcome_back_last,
                "daily_stats": {k: dict(v) for k, v in daily_stats.items()},
                "known_members": {k: list(v) for k, v in known_members.items()},
            },
            indent=2,
        )
    )


def load_data():
    global welcome_back_last, daily_stats, known_members
    if Path(DATA_FILE).exists():
        raw = json.loads(Path(DATA_FILE).read_text())
        welcome_back_last = raw.get("welcome_back_last", {})
        for k, v in raw.get("daily_stats", {}).items():
            daily_stats[k] = defaultdict(int, v)
        for k, v in raw.get("known_members", {}).items():
            known_members[k] = set(v)


def get_username(user_id: str) -> str:
    try:
        info = cl.user_info(user_id)
        return info.username
    except Exception:
        return str(user_id)


# ─────────────────────────── commands ────────────────────────
async def cmd_spam(thread_id: str, text: str, times: int = 15):
    for _ in range(times):
        if spam_tasks.get(thread_id + "_stop"):
            break
        try:
            cl.direct_send(text, thread_ids=[thread_id])
        except Exception as e:
            log.warning(f"Spam send error: {e}")
        await asyncio.sleep(0.8)
    spam_tasks.pop(thread_id, None)
    spam_tasks.pop(thread_id + "_stop", None)


async def cmd_bad(thread_id: str, victim_id: str, phrase: str):
    """Watch victim messages in thread and reply with phrase."""
    bad_targets[victim_id] = phrase
    bad_stop[victim_id] = False


def stop_bad(victim_id: str):
    bad_stop[victim_id] = True
    bad_targets.pop(victim_id, None)


def build_total_report() -> str:
    key = today_key()
    stats = daily_stats.get(key, {})
    total_msgs = sum(stats.values())
    active_users = len(stats)
    # known_members across all threads
    total_known = sum(len(v) for v in known_members.values())
    return (
        f"📊 Today's Report ({key})\n"
        f"Total messages: {total_msgs}\n"
        f"Active users: {active_users}\n"
        f"Total joined members tracked: {total_known}"
    )


MENU_TEXT = """📋 Bot Commands Menu

👑 Admin Only:
@bot /spam <text>  → Send text 15× (reply /stop to cancel)
@bot /bad @user <phrase>  → Auto-reply phrase to victim
@bot /song <name>  → Send a song from Instagram
@bot /stop  → Stop active spam or /bad
@bot /total  → Today's message stats
@bot /menu  → This menu

📌 Auto Features:
• New member → Welcome message
• Returning member → Welcome back (max 1× per 12h)
• "ignore" in message → Special reply
• Instagram GC link → Special reply
• 12:00 AM → Good night message @everyone
• 7:00 AM → Good morning message @everyone

💬 DM to bot: /send_gc <text>  → Bot sends text to all GCs"""


# ─────────────────────────── message processor ───────────────
async def process_message(thread_id: str, msg, sender_id: str, sender_username: str):
    text: str = getattr(msg, "text", "") or ""
    msg_id: str = str(msg.id)

    # stat tracking
    daily_stats[today_key()][sender_id] += 1

    bot_id = str(cl.user_id)

    # ── /stop (reply to spam or bad) ──────────────────────────
    if text.strip().lower() == "/stop":
        # stop spam for this thread
        spam_tasks[thread_id + "_stop"] = True
        # stop bad for anyone
        for uid in list(bad_targets.keys()):
            stop_bad(uid)
        return

    # ── admin commands (must mention bot or start with @bot tag) ──
    if is_admin(sender_username) and f"@{bot_id}" in text.lower() or re.search(r"@\w+\s+/", text):
        lower = text.lower()

        # /spam
        m = re.search(r"/spam\s+(.+)", text, re.IGNORECASE)
        if m:
            spam_text = m.group(1).strip()
            task = asyncio.create_task(cmd_spam(thread_id, spam_text))
            spam_tasks[thread_id] = task
            return

        # /song
        m = re.search(r"/song\s+(.+)", text, re.IGNORECASE)
        if m:
            song_name = m.group(1).strip()
            await handle_song(thread_id, song_name)
            return

        # /bad @target phrase
        m = re.search(r"/bad\s+@(\S+)\s+(.+)", text, re.IGNORECASE)
        if m:
            victim_username = m.group(1)
            phrase = m.group(2).strip()
            try:
                victim_info = cl.user_info_by_username(victim_username)
                await cmd_bad(thread_id, str(victim_info.pk), phrase)
            except Exception:
                cl.direct_send(f"Can't find @{victim_username}", thread_ids=[thread_id])
            return

        # /menu
        if "/menu" in lower:
            cl.direct_send(MENU_TEXT, thread_ids=[thread_id])
            return

        # /total
        if "/total" in lower:
            cl.direct_send(build_total_report(), thread_ids=[thread_id])
            return

    # ── /bad auto-reply ───────────────────────────────────────
    if sender_id in bad_targets and not bad_stop.get(sender_id):
        phrase = bad_targets[sender_id]
        try:
            cl.direct_send(phrase, thread_ids=[thread_id], reply_to_message=msg_id)
        except Exception as e:
            log.warning(f"Bad reply error: {e}")
        return

    # ── keyword triggers ──────────────────────────────────────
    lower_text = text.lower()

    # "ignore" keyword
    if "ignore" in lower_text:
        try:
            cl.direct_send(
                "AWW BACCHA ISSOKIEE MEIN HU NA APKE LIYE 🥹 💋",
                thread_ids=[thread_id],
                reply_to_message=msg_id,
            )
        except Exception as e:
            log.warning(f"Ignore reply error: {e}")
        return

    # Instagram GC link
    if re.search(r"https://ig\.me/j/", text):
        try:
            cl.direct_send(
                "AWW TERE B44P KI BIWI KE PICS DE RHA HAI GC PE ? 🥰",
                thread_ids=[thread_id],
                reply_to_message=msg_id,
            )
        except Exception as e:
            log.warning(f"Link reply error: {e}")
        return

    # ── welcome back (returning member, 12h cooldown) ─────────
    last_ts = welcome_back_last.get(sender_id, 0)
    if (now_ts() - last_ts) >= 43200:   # 43200s = 12h
        welcome_back_last[sender_id] = now_ts()
        try:
            cl.direct_send(
                f"Welcome back to our gc @{sender_username} how are you? 🎈",
                thread_ids=[thread_id],
            )
        except Exception as e:
            log.warning(f"Welcome back error: {e}")


async def handle_song(thread_id: str, song_name: str):
    """Search Instagram audio and send, or error message."""
    try:
        results = cl.search_audio(song_name)
        if results:
            audio = results[0]
            # Send audio by sharing track link / clip
            cl.direct_send(
                f"🎵 {audio.title} — {audio.artist if hasattr(audio, 'artist') else ''}",
                thread_ids=[thread_id],
            )
        else:
            cl.direct_send("song nhi mil rha 😔", thread_ids=[thread_id])
    except Exception:
        cl.direct_send("song nhi mil rha 😔", thread_ids=[thread_id])


# ─────────────────────────── thread poller ───────────────────
processed_msg_ids: set[str] = set()


async def poll_threads():
    while True:
        try:
            for thread_id in GROUP_IDS:
                try:
                    thread = cl.direct_thread(thread_id, amount=20)
                except Exception as e:
                    log.warning(f"Thread fetch {thread_id}: {e}")
                    continue

                # check for new members
                current_ids = {str(u.pk) for u in thread.users}
                new_members = current_ids - known_members[thread_id]
                for uid in new_members:
                    uname = get_username(uid)
                    try:
                        cl.direct_send(
                            f"Welcome to our gc @{uname} 🎉",
                            thread_ids=[thread_id],
                        )
                        log.info(f"Welcomed new member @{uname} in {thread_id}")
                    except Exception as e:
                        log.warning(f"New member welcome error: {e}")
                known_members[thread_id] = current_ids

                # process messages
                for msg in reversed(thread.messages):
                    mid = str(msg.id)
                    if mid in processed_msg_ids:
                        continue
                    processed_msg_ids.add(mid)

                    sender_id = str(msg.user_id)
                    bot_id = str(cl.user_id)
                    if sender_id == bot_id:
                        continue

                    sender_username = get_username(sender_id)

                    # DM relay: /send_gc in DM to bot
                    if not thread.is_group:
                        await handle_dm(thread_id, msg, sender_id, sender_username)
                        continue

                    await process_message(thread_id, msg, sender_id, sender_username)

        except Exception as e:
            log.error(f"Poll error: {e}")

        save_data()
        await asyncio.sleep(4)   # poll every 4 seconds


async def handle_dm(thread_id: str, msg, sender_id: str, sender_username: str):
    """Handle DMs from admins to bot: /send_gc <text>"""
    text = getattr(msg, "text", "") or ""
    if not is_admin(sender_username):
        return
    m = re.match(r"/send_gc\s+(.+)", text.strip(), re.IGNORECASE | re.DOTALL)
    if m:
        gc_text = m.group(1).strip()
        for gid in GROUP_IDS:
            try:
                cl.direct_send(gc_text, thread_ids=[gid])
                log.info(f"Admin DM relay sent to {gid}: {gc_text[:40]}")
            except Exception as e:
                log.warning(f"DM relay error: {e}")


# ─────────────────────────── scheduler ───────────────────────
async def scheduler():
    last_goodnight = ""
    last_goodmorning = ""

    while True:
        now = datetime.now()
        date_key = now.strftime("%Y-%m-%d")

        # 12:00 AM — good night
        if now.hour == 0 and now.minute == 0 and last_goodnight != date_key:
            last_goodnight = date_key
            msg = "GOOD NIGHT USERS\nSusu karke soo jana babu 💋 @everyone"
            for gid in GROUP_IDS:
                try:
                    cl.direct_send(msg, thread_ids=[gid])
                except Exception as e:
                    log.warning(f"Good night error: {e}")

        # 7:00 AM — good morning
        if now.hour == 7 and now.minute == 0 and last_goodmorning != date_key:
            last_goodmorning = date_key
            msg = "GOOD MORNING Ngas How are you @everyone"
            for gid in GROUP_IDS:
                try:
                    cl.direct_send(msg, thread_ids=[gid])
                except Exception as e:
                    log.warning(f"Good morning error: {e}")

        await asyncio.sleep(30)


# ─────────────────────────── entry point ─────────────────────
async def run_bot():
    load_data()
    if not load_session():
        log.error("No valid session. Upload cookies via dashboard.")
        return

    log.info("Bot started. Polling threads: %s", GROUP_IDS)
    await asyncio.gather(
        poll_threads(),
        scheduler(),
    )


if __name__ == "__main__":
    asyncio.run(run_bot())

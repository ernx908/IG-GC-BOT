# Instagram GC Bot

Automated Instagram Group Chat bot with a web control panel.

---

## Features

| Feature | Detail |
|---|---|
| Welcome back | Sends "Welcome back @user 🎈" once per 12 hours per member |
| New member | Auto-detects newly added members and sends welcome |
| "ignore" trigger | Auto-replies with custom message when anyone types "ignore" |
| GC link trigger | Detects `ig.me/j/` links and fires a comeback reply |
| Good night | Sends at 12:00 AM daily to all GCs |
| Good morning | Sends at 7:00 AM daily to all GCs |
| /spam | Admin: bot sends a message 15× |
| /song | Admin: bot searches and sends a song from Instagram |
| /bad | Admin: bot auto-replies to a target user every message |
| /stop | Cancels active /spam or /bad |
| /menu | Full command list posted in GC |
| /total | Today's message count + active users + member count |
| /send_gc | Admin DM relay: bot forwards your DM text to all GCs |

**Caps:** Max 5 admins · Max 3 group chats

---

## Repository Files

```
instagram-gc-bot/
├── bot.py            ← Main bot runtime (async polling + scheduler)
├── web.py            ← Flask admin dashboard
├── config.py         ← All settings read from environment variables
├── requirements.txt  ← Python dependencies
├── render.yaml       ← Render.com deployment config
├── Dockerfile        ← Docker self-host option
├── .gitignore
├── README.md
└── templates/
    ├── login.html    ← Dashboard login page
    └── dashboard.html ← Control panel UI
```

---

## Deploy on Render (Free, 24/7)

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "initial"
git remote add origin https://github.com/YOUR_USER/instagram-gc-bot.git
git push -u origin main
```

### 2. Create Render Web Service

1. Go to [render.com](https://render.com) → New → Web Service
2. Connect your GitHub repo
3. Render auto-detects `render.yaml` — accept defaults

### 3. Set Environment Variables in Render

Go to your service → Environment tab → add:

| Key | Value |
|---|---|
| `DASHBOARD_PASSWORD` | Your chosen password |
| `ADMIN_USERNAMES` | `username1,username2` (no @, max 5) |
| `GROUP_IDS` | `3402823...,3402823...` (max 3) |
| `IG_COOKIES_JSON` | *(paste later via dashboard)* |
| `FLASK_SECRET` | Any random string |

### 4. Get your Render URL

After deploy, Render gives you a URL like:
`https://instagram-gc-bot.onrender.com`

That is your dashboard. Bookmark it.

---

## Getting Instagram Session Cookies (Firefox)

1. Open Firefox → go to `https://www.instagram.com` → log in as the bot account
2. Press `F12` → go to **Storage** tab → expand **Cookies** → click `instagram.com`
3. Right-click on the cookie list → **Copy All** (some versions show "Export")
4. The result is a JSON array — paste it into the dashboard's cookie field

> The session is saved to `session.json` on first load. Future restarts reuse it automatically.

---

## Getting Group Thread ID

1. Open Instagram in browser → DMs → open the group chat
2. URL looks like:  
   `https://www.instagram.com/direct/t/340282366841710300588172137...`
3. Copy the long number after `/t/` — that is the Thread ID
4. Paste in dashboard under "Group Thread IDs"

---

## Admin Command Usage (inside Instagram GC)

All admin commands require mentioning the bot's Instagram username first:

```
@botusername /spam Hello chat!
@botusername /song Blinding Lights
@botusername /bad @victimuser BHGG
@botusername /menu
@botusername /total
```

To stop spam or /bad — reply to any bot message with:
```
/stop
```

To relay a message from bot's DM to all GCs:
```
/send_gc Good morning everyone!
```
(Send this as a DM to the bot account)

---

## Self-Host with Docker

```bash
docker build -t gc-bot .
docker run -d \
  -p 5000:5000 \
  -e DASHBOARD_PASSWORD=yourpassword \
  -e ADMIN_USERNAMES=admin1,admin2 \
  -e GROUP_IDS=340282366...,340282366... \
  -e FLASK_SECRET=randomstring \
  -v $(pwd)/data:/app \
  gc-bot
```

Then open `http://localhost:5000`

---

## Notes

- The bot polls Instagram every 4 seconds — stays within normal rate limits
- Session cookies from Firefox bypass the need for username/password login, reducing ban risk
- `session.json` and `bot_data.json` are gitignored — never commit them
- On Render free tier the service spins down after 15 min inactivity — use UptimeRobot to ping `/status` every 5 min to keep it alive

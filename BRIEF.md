# SI Archive Bot — Full Project Brief
> For an AI assistant replicating or improving this project.

---

## What This Is

A Telegram bot for a church's Sermon Illustration (SI) Ministry. The ministry creates Photoshop slides and shares files via Telegram. The bot automatically archives files from Telegram to Google Drive with date-stamped, sermon-named folder structure.

**User:** Non-technical church ministry team  
**Scale:** Small team, files up to 2GB, sporadic usage  
**Budget:** Free

---

## Final Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | Best library support for Telegram + Google APIs |
| Telegram framework | **Pyrogram 2.0.106** | Handles files up to 2GB via MTProto. `python-telegram-bot` is limited to 20MB downloads via Bot API. |
| Google Drive | Google Drive API v3 + **OAuth2 refresh token** | Service accounts have no storage quota — they cannot upload file content. OAuth2 with a personal account uses the account's real storage. |
| Web server | Flask (health endpoint only) | Render free tier requires an HTTP server to stay alive |
| Hosting | **Render.com** (free web service) | Vercel was rejected — its 10s serverless timeout kills large file transfers. Render runs a persistent process. |
| Keep-alive | UptimeRobot (free) | Pings `/health` every 5 min to prevent Render free tier spin-down |

---

## Critical Lessons Learned (Do Not Repeat These Mistakes)

### 1. Do NOT use Vercel for this
Vercel serverless functions time out at 10 seconds on the free tier. A 100MB file takes longer than that just to download. Render.com runs a persistent process and has no timeout issue.

### 2. Do NOT use a Google Service Account for Drive uploads
Service accounts have no storage quota. They can create folders (metadata) but cannot upload file content. Error: `HTTP 403 — Service Accounts do not have storage quota`. Use OAuth2 with a real Google account instead.

### 3. Use Pyrogram, not python-telegram-bot
Telegram Bot API's `getFile` endpoint caps at 20MB. The ministry sends PSDs and videos that exceed this. Pyrogram uses MTProto directly and handles up to 2GB.

### 4. Pyrogram requires API_ID + API_HASH even for bots
Get these from https://my.telegram.org — they are free. Without them Pyrogram won't initialise.

### 5. Pin Python to 3.11 on Render
Render defaults to the latest Python (3.14 at time of writing). Pyrogram 2.0.106 is not compatible with Python 3.14. Add a `.python-version` file containing `3.11.9`.

### 6. Use simple upload for files < 5MB, resumable for larger
`MediaFileUpload(resumable=True)` fails with `ResumableUploadError` on small files on low-CPU hosts. Switch to `resumable=False` for files under 5MB.

### 7. Flask must bind to `PORT` env var, not hardcoded 8080
Render injects `PORT` dynamically. Read it with `int(os.getenv("PORT", 8080))`.

### 8. Run Flask health server in a daemon thread
Pyrogram's `app.run()` is blocking. Start Flask in `threading.Thread(target=..., daemon=True)` before calling `app.run()`.

---

## File Structure

```
SI-Telegram-Bot/
├── bot.py              # Main bot — Pyrogram handlers + Flask health server
├── drive.py            # Google Drive service — folder creation + file upload
├── sermons.py          # Sermon list CRUD — stored in sermons.json
├── setup_oauth.py      # ONE-TIME script — generates Google OAuth2 refresh token
├── sermons.json        # Auto-created — sermon list (ephemeral on Render free tier)
├── client_secrets.json # OAuth2 Desktop App credentials (gitignored)
├── .python-version     # Contains: 3.11.9
├── requirements.txt
├── render.yaml
├── .env                # Real credentials (gitignored)
├── .env.example        # Safe placeholder reference
└── .gitignore
```

---

## Environment Variables

| Variable | Where to get it |
|---|---|
| `API_ID` | https://my.telegram.org → API development tools |
| `API_HASH` | Same as above |
| `BOT_TOKEN` | @BotFather on Telegram → /newbot |
| `ADMIN_IDS` | Comma-separated Telegram user IDs. Leave blank = everyone is admin |
| `GOOGLE_CLIENT_ID` | Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client (Desktop app) |
| `GOOGLE_CLIENT_SECRET` | Same as above |
| `GOOGLE_REFRESH_TOKEN` | Run `setup_oauth.py` once locally, sign into Google account |
| `DRIVE_ROOT_FOLDER_ID` | Folder ID from Google Drive URL (the string after `/folders/`) |
| `PORT` | Set automatically by Render — do not hardcode |

---

## Naming Convention

```
Folder structure:
  SI Archive / 2026 / May / 24 May - Grace In Suffering /

File rename:
  20260524_GraceInSuffering_originalfilename.psd
  └─ YYYYMMDD + SermonTitlePascalCase + original filename preserved
```

---

## Bot Flow

```
User sends file to bot (Telegram DM)
  ↓
Bot replies with sermon picker (inline keyboard from sermons.json)
  ↓
User selects sermon OR types custom "YYYY-MM-DD Title"
  ↓
Bot downloads file from Telegram to /tmp (Pyrogram, handles up to 2GB)
  ↓
Bot checks file exists and is non-empty
  ↓
Bot creates folder structure in Google Drive if it doesn't exist
  ↓
Bot uploads file using OAuth2 (user's personal Google account quota)
  < 5MB → simple upload
  ≥ 5MB → resumable chunked upload (8MB chunks)
  ↓
Bot replies with ✅ confirmation + Drive link
  ↓
Temp file deleted from /tmp
```

---

## Bot Commands

| Command | Who | What |
|---|---|---|
| `/start` or `/help` | Anyone | Shows usage instructions |
| `/addsermon YYYY-MM-DD Title` | Admins only | Adds sermon to picker list |
| `/listsermons` | Anyone | Shows all sermons with their IDs |
| `/removesermon ID` | Admins only | Removes sermon by ID |

---

## Google OAuth2 Setup (One-Time)

1. Google Cloud Console → project → Enable **Google Drive API**
2. APIs & Services → Credentials → **+ Create Credentials** → OAuth client ID → **Desktop app**
3. Download JSON → save as `client_secrets.json` in project root
4. APIs & Services → OAuth consent screen → Add your Google email as **Test user**
5. Run: `python3 setup_oauth.py`
6. Browser opens → sign in → Allow
7. Terminal prints `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`
8. Add all three to `.env` and Render environment variables

---

## Render Deployment

- Type: **Web Service** (not Worker — free Worker tier may require paid plan)
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Region: Singapore (or nearest to users)
- Health check path: `/health`
- After deploy: set up UptimeRobot to ping `https://your-app.onrender.com/health` every 5 minutes

---

## Known Limitations & Planned Work

- `sermons.json` is ephemeral — resets on every Render deploy. Fix: use a free DB (Supabase) or Render persistent disk ($)
- Failure webhook not yet built: if upload fails, admins should be notified via Telegram DM with file details and a failed_uploads.json queue
- Google Drive push notification (files.watch) to confirm uploads landed — planned as safety net
- No group chat support yet — bot is private DM only
- For truly large files (>1GB), Render free tier's 512MB RAM may become a constraint depending on Pyrogram's buffering behaviour

---

## requirements.txt

```
pyrogram==2.0.106
tgcrypto==1.2.5
flask==3.0.3
google-api-python-client==2.131.0
google-auth==2.29.0
google-auth-oauthlib==1.2.0
python-dotenv==1.0.1
```

---

## render.yaml

```yaml
services:
  - type: web
    name: si-archive-bot
    env: python
    region: singapore
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python bot.py
```

---

## GitHub Repo

https://github.com/mynameisjiajun/SI-Upload-app-.git

import os
import re
import logging
import threading
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
    Message,
)

from drive import DriveService
from sermons import SermonManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PORT = int(os.getenv("PORT", 8080))

# ── Services ──────────────────────────────────────────────────────────────────

drive = DriveService()
sermon_mgr = SermonManager()

app = Client(
    "si_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# user_id → { message, file_name, file_size, awaiting_custom }
pending: dict = {}

# ── Health server (keeps Render web service alive) ────────────────────────────

health_app = Flask(__name__)


@health_app.route("/health")
def health():
    return "OK", 200


@health_app.route("/")
def root():
    return "SI Archive Bot is running.", 200


def _run_health_server():
    health_app.run(host="0.0.0.0", port=PORT, use_reloader=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / (1024 ** 3):.2f} GB"


def title_slug(title: str) -> str:
    """'Grace In Suffering' → 'GraceInSuffering'"""
    words = re.sub(r"[^a-zA-Z0-9 ]", "", title).split()
    return "".join(w.capitalize() for w in words) or "Untitled"


def build_new_filename(date_str: str, sermon_title: str, original_name: str) -> str:
    date_compact = date_str.replace("-", "")       # 20260524
    slug = title_slug(sermon_title)                 # GraceInSuffering
    if "." in original_name:
        base, ext = original_name.rsplit(".", 1)
        return f"{date_compact}_{slug}_{base}.{ext}"
    return f"{date_compact}_{slug}_{original_name}"


def sermon_keyboard(sermons: list) -> InlineKeyboardMarkup:
    rows = []
    for s in sermons:
        label = f"📅 {s['date']}  {s['title']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"s:{s['id']}")])
    rows.append([InlineKeyboardButton("✏️ Enter custom name", callback_data="s:custom")])
    return InlineKeyboardMarkup(rows)


# ── Bot handlers ──────────────────────────────────────────────────────────────

@app.on_message(filters.command(["start", "help"]) & filters.private)
async def cmd_start(client, message: Message):
    await message.reply_text(
        "👋 **SI Archive Bot**\n\n"
        "Send me any file and I'll rename and archive it to Google Drive "
        "under the correct sermon folder.\n\n"
        "**Commands**\n"
        "`/addsermon YYYY-MM-DD Title` — Add a sermon\n"
        "`/listsermons` — View sermon list\n"
        "`/removesermon ID` — Remove a sermon",
        quote=True,
    )


@app.on_message(filters.command("listsermons") & filters.private)
async def cmd_list(client, message: Message):
    sermons = sermon_mgr.get_sermons()
    if not sermons:
        await message.reply_text(
            "No sermons yet. Use `/addsermon YYYY-MM-DD Title` to add one.",
            quote=True,
        )
        return
    lines = ["**Sermons**\n"]
    for s in sermons:
        lines.append(f"`{s['id']}` — {s['date']} | {s['title']}")
    await message.reply_text("\n".join(lines), quote=True)


@app.on_message(filters.command("addsermon") & filters.private)
async def cmd_add(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("⛔ Only admins can add sermons.", quote=True)
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply_text(
            "Usage: `/addsermon YYYY-MM-DD Sermon Title`\n"
            "Example: `/addsermon 2026-05-31 Grace In Suffering`",
            quote=True,
        )
        return

    date_str, title = parts[1], parts[2]
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.reply_text("Invalid date. Use `YYYY-MM-DD`.", quote=True)
        return

    s = sermon_mgr.add_sermon(date_str, title)
    await message.reply_text(
        f"✅ Added `{s['id']}` — {date_str} | {title}", quote=True
    )


@app.on_message(filters.command("removesermon") & filters.private)
async def cmd_remove(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("⛔ Only admins can remove sermons.", quote=True)
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: `/removesermon ID`", quote=True)
        return

    sid = parts[1].strip()
    if sermon_mgr.remove_sermon(sid):
        await message.reply_text(f"✅ Removed `{sid}`.", quote=True)
    else:
        await message.reply_text(f"Sermon `{sid}` not found.", quote=True)


@app.on_message(
    filters.private
    & (filters.document | filters.photo | filters.video | filters.audio)
)
async def handle_file(client, message: Message):
    user_id = message.from_user.id

    if message.document:
        media = message.document
        file_name = media.file_name or f"document_{message.date.strftime('%Y%m%d_%H%M%S')}"
        file_size = media.file_size or 0
    elif message.photo:
        media = message.photo
        file_name = f"photo_{message.date.strftime('%Y%m%d_%H%M%S')}.jpg"
        file_size = media.file_size or 0
    elif message.video:
        media = message.video
        file_name = media.file_name or f"video_{message.date.strftime('%Y%m%d_%H%M%S')}.mp4"
        file_size = media.file_size or 0
    elif message.audio:
        media = message.audio
        file_name = media.file_name or f"audio_{message.date.strftime('%Y%m%d_%H%M%S')}.mp3"
        file_size = media.file_size or 0
    else:
        return

    pending[user_id] = {
        "message": message,
        "file_name": file_name,
        "file_size": file_size,
    }

    sermons = sermon_mgr.get_sermons()
    await message.reply_text(
        f"📎 **{file_name}**  ({format_size(file_size)})\n\n"
        "Which sermon is this for?",
        reply_markup=sermon_keyboard(sermons),
        quote=True,
    )


@app.on_callback_query(filters.regex(r"^s:"))
async def on_sermon_selected(client, cb: CallbackQuery):
    user_id = cb.from_user.id

    if user_id not in pending:
        await cb.answer("Session expired. Please resend the file.", show_alert=True)
        return

    data = cb.data[2:]  # strip "s:"

    if data == "custom":
        pending[user_id]["awaiting_custom"] = True
        await cb.message.edit_text(
            "Type the sermon name:\n"
            "Format: `YYYY-MM-DD Title`\n"
            "Example: `2026-05-31 Special Service`"
        )
        await cb.answer()
        return

    sermon = sermon_mgr.get_sermon(data)
    if not sermon:
        await cb.answer("Sermon not found.", show_alert=True)
        return

    await cb.answer()
    await cb.message.edit_text("⏳ Starting upload…")
    await _process_upload(client, cb.message, user_id, sermon)


@app.on_message(filters.private & filters.text & ~filters.command(["start", "help", "addsermon", "listsermons", "removesermon"]))
async def handle_custom_name(client, message: Message):
    user_id = message.from_user.id
    if user_id not in pending or not pending[user_id].get("awaiting_custom"):
        return

    text = message.text.strip()
    parts = text.split(" ", 1)
    try:
        date = datetime.strptime(parts[0], "%Y-%m-%d").strftime("%Y-%m-%d")
        title = parts[1] if len(parts) > 1 else "Untitled"
    except ValueError:
        date = datetime.now().strftime("%Y-%m-%d")
        title = text

    pending[user_id].pop("awaiting_custom", None)
    sermon = {"date": date, "title": title, "id": "custom"}

    status = await message.reply_text("⏳ Starting upload…", quote=True)
    await _process_upload(client, status, user_id, sermon)


# ── Upload logic ──────────────────────────────────────────────────────────────

async def _process_upload(client, status_msg, user_id: int, sermon: dict):
    info = pending.pop(user_id, None)
    if not info:
        return

    original_msg: Message = info["message"]
    file_name: str = info["file_name"]
    file_size: int = info["file_size"]
    new_name = build_new_filename(sermon["date"], sermon["title"], file_name)
    tmp_path = f"/tmp/{new_name}"

    last_pct = [-1]

    async def progress(current, total):
        pct = int(current / total * 100) if total else 0
        step = pct // 10 * 10
        if step != last_pct[0] and step % 10 == 0:
            last_pct[0] = step
            try:
                await status_msg.edit_text(
                    f"⬇️ Downloading… {step}%  "
                    f"({format_size(current)} / {format_size(total)})"
                )
            except Exception:
                pass

    try:
        await status_msg.edit_text(f"⬇️ Downloading… 0%  (0 B / {format_size(file_size)})")
        try:
            await original_msg.download(file_name=tmp_path, progress=progress)
        except Exception as exc:
            logger.exception("Download failed")
            await status_msg.edit_text(f"❌ Download failed: {type(exc).__name__}: {exc}")
            return

        await status_msg.edit_text("⬆️ Uploading to Google Drive…")
        try:
            folder_id = drive.get_or_create_folder(sermon["date"], sermon["title"])
            _, web_link = drive.upload_file(tmp_path, new_name, folder_id)
        except Exception as exc:
            logger.exception("Drive upload failed")
            await status_msg.edit_text(f"❌ Drive upload failed: {type(exc).__name__}: {exc}")
            return

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        await status_msg.edit_text(
            f"✅ **Archived!**\n\n"
            f"📄 `{new_name}`\n"
            f"📂 {sermon['date']} — {sermon['title']}\n"
            f"🔗 [View in Google Drive]({web_link})"
        )

    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    threading.Thread(target=_run_health_server, daemon=True).start()
    logger.info("Health server started on port %s", PORT)
    logger.info("Starting SI Archive Bot…")
    app.run()

from __future__ import annotations
import asyncio
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Optional
import html
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from .config import GOOGLE_OAUTH_MODE
from .drive import build_flow, device_code_request, poll_device_token, creds_from_token_response, email_from_id_token

from telegram.constants import ParseMode

from .config import DOWNLOAD_DIR, EDIT_THROTTLE_SECS
from .db import init_db, save_state, load_creds, delete_creds, set_folder, get_folder, save_creds
from .drive import get_service_for_user, upload_with_progress
from .downloader import download_http, download_telegram_file
from .utils import Throttle, card_done

log = logging.getLogger(__name__)

_URL_RE = re.compile(r'(https?://\S+)', re.I)

def extract_urls(text: Optional[str]) -> list[str]:
    if not text:
        return []
    return _URL_RE.findall(text.strip())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Hi! I can upload your Telegram files or direct HTTP links to your Google Drive.\n\n"
        "Commands:\n"
        "• /login – Connect your Google Drive\n"
        "• /logout – Disconnect Google Drive\n"
        "• /me – Show connected account & folder\n"
        "• /setfolder <folder_id> – Set a specific Drive folder\n\n"
        "Send me a video/file or paste a direct link and I’ll handle the rest."
    )
    await update.message.reply_text(text, disable_web_page_preview=True)
    
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = load_creds(uid)
    folder = get_folder(uid)

    if not data:
        await update.message.reply_text("Not connected. Use /login to connect your Google Drive.")
        return

    email, _ = data
    folder_txt = html.escape(folder) if folder else "Telegram Bot Uploads (auto)"
    text = f"Connected as <b>{html.escape(email)}</b>\nFolder: <code>{folder_txt}</code>"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def setfolder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setfolder <drive_folder_id> (or /setfolder none to reset)")
        return
    arg = context.args[0].strip().lower()
    if arg in ("none","reset","default"):
        set_folder(update.effective_user.id, None)
        await update.message.reply_text("Folder reset. I’ll use the default 'Telegram Bot Uploads'.")
    else:
        set_folder(update.effective_user.id, arg)
        await update.message.reply_text(f"Folder set to: <code>{html.escape(arg)}</code>", parse_mode=ParseMode.HTML)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if GOOGLE_OAUTH_MODE == "web":
        # Web OAuth (needs redirect URI/domain)
        from uuid import uuid4
        state = uuid4().hex
        save_state(state, uid)
        flow = build_flow(state)
        auth_url, _ = flow.authorization_url(
            prompt="consent", access_type="offline", include_granted_scopes="true"
        )
        await update.message.reply_text("Tap to connect your Google Drive:\n" + auth_url)
        return

    # Device Flow (no domain needed)
    dc = await device_code_request()
    status = await update.message.reply_text(
        "🔐 Connect Google Drive\n\n"
        "1) Open: https://www.google.com/device\n"
        f"2) Enter code: {dc.user_code}\n\n"
        "I’ll wait while you approve…"
    )

    try:
        tok = await poll_device_token(dc.device_code, dc.interval)  # uses server-suggested interval
        creds_json = creds_from_token_response(tok)
        email = email_from_id_token(tok.get("id_token"))
        save_creds(uid, email, creds_json)
        await status.edit_text(f"✅ Connected as {email}. You can now send files or links.")
    except Exception as e:
        await status.edit_text(f"❌ Login failed: {e}")


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    delete_creds(update.effective_user.id)
    await update.message.reply_text("Disconnected from Google Drive.")

async def _process_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, src: str, from_telegram: bool, file_id: Optional[str]=None):
    uid = update.effective_user.id
    data = load_creds(uid)
    if not data:
        await update.message.reply_text("Please /login first to connect your Google Drive.")
        return

    status_msg = await update.message.reply_text("Preparing…")
    throttle = Throttle(EDIT_THROTTLE_SECS)

    def updater(txt: str):
        if throttle.ready():
            asyncio.create_task(status_msg.edit_text(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True))

    # 1) Download
    try:
        dl_start = time.time()
        if from_telegram and file_id:
            dest, mime, total = await download_telegram_file(context.bot, file_id, DOWNLOAD_DIR, updater)
        else:
            dest, mime, total = await download_http(src, DOWNLOAD_DIR, updater)
        dl_elapsed = time.time() - dl_start

        # Show a short "Download complete" card before upload
        size_bytes = dest.stat().st_size
        await status_msg.edit_text(
            card_done("Download complete", file_name=dest.name, size=size_bytes, dl_time=dl_elapsed),
            parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:
        log.exception("Download failed")
        await status_msg.edit_text(f"❌ Download failed: {html.escape(str(e))}", parse_mode=ParseMode.HTML)
        return

    # 2) Upload
    try:
        ul_start = time.time()
        service, _ = get_service_for_user(uid)
        if not service:
            await status_msg.edit_text("Please /login first to connect your Google Drive.")
            return
        if not mime:
            mime, _ = mimetypes.guess_type(dest.name)

        # immediately switch the message to an initial uploading card (0%); the loop inside upload will keep updating
        updater(card_progress("Uploading File", 0, size_bytes, 0.0, 0.0, -1))

        link = upload_with_progress(service, uid, str(dest), dest.name, mime, updater)
        ul_elapsed = time.time() - ul_start

        # 3) Final summary
        await status_msg.edit_text(
            card_done("Upload complete", file_name=dest.name, size=size_bytes, dl_time=dl_elapsed, ul_time=ul_elapsed, link=link),
            parse_mode=ParseMode.HTML, disable_web_page_preview=False
        )
    except Exception as e:
        log.exception("Upload failed")
        await status_msg.edit_text(f"❌ Upload failed: {html.escape(str(e))}", parse_mode=ParseMode.HTML)
        return

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document or update.message.video or update.message.animation
    if not doc:
        await update.message.reply_text("Send a document/video or a direct link.")
        return
    await _process_and_upload(update, context, src="telegram", from_telegram=True, file_id=doc.file_id)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = extract_urls(update.message.text)
    if not urls:
        await update.message.reply_text("No URL found. Send a direct link or upload a file.")
        return
    # Process the first URL only (can extend to batch)
    await _process_and_upload(update, context, src=urls[0], from_telegram=False)

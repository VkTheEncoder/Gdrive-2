from __future__ import annotations
import asyncio
import logging
import mimetypes
import re
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import DOWNLOAD_DIR, EDIT_THROTTLE_SECS
from .db import init_db, save_state, load_creds, delete_creds, set_folder, get_folder
from .drive import get_service_for_user, upload_with_progress
from .downloader import download_http, download_telegram_file
from .utils import Throttle

log = logging.getLogger(__name__)

_URL_RE = re.compile(r'(https?://\S+)', re.I)

def extract_urls(text: Optional[str]) -> list[str]:
    if not text:
        return []
    return _URL_RE.findall(text.strip())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I can upload your Telegram files or direct links to *your* Google Drive.\n\n"
        "Commands:\n"
        "• /login – Connect your Google Drive\n"
        "• /logout – Disconnect Google Drive\n"
        "• /me – Show account & folder\n"
        "• /setfolder <folder_id> – Use a specific Drive folder\n\n"
        "Send me a video/file *or* paste a direct link (HTTP) and I’ll do the rest.",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

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
    txt = f"Connected as **{email}**\nFolder: `{folder or 'Telegram Bot Uploads (auto)'}`"
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

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
        await update.message.reply_text(f"Folder set to `{arg}`", parse_mode=ParseMode.MARKDOWN)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from uuid import uuid4
    from .drive import build_flow
    uid = update.effective_user.id
    state = uuid4().hex
    save_state(state, uid)
    flow = build_flow(state)
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
    await update.message.reply_text(
        "Tap to connect your Google Drive:\n" + auth_url,
        disable_web_page_preview=False
    )

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
            asyncio.create_task(status_msg.edit_text(txt))

    # 1) Download
    try:
        if from_telegram and file_id:
            dest, mime = await download_telegram_file(context.bot, file_id, DOWNLOAD_DIR, updater)
        else:
            dest, mime = await download_http(src, DOWNLOAD_DIR, updater)
    except Exception as e:
        log.exception("Download failed")
        await status_msg.edit_text(f"❌ Download failed: {e}")
        return

    # 2) Upload
    try:
        service, _ = get_service_for_user(uid)
        if not service:
            await status_msg.edit_text("Please /login first to connect your Google Drive.")
            return
        # guess mime if needed
        if not mime:
            mime, _ = mimetypes.guess_type(dest.name)
        link = upload_with_progress(service, uid, str(dest), dest.name, mime, updater)
    except Exception as e:
        log.exception("Upload failed")
        await status_msg.edit_text(f"❌ Upload failed: {e}")
        return

    await status_msg.edit_text(f"✅ Uploaded to Google Drive:\n{link}")

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

from __future__ import annotations
import aiohttp
import asyncio
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse
from .utils import fmt_progress_html  # instead of fmt_progress
from telegram import Bot
from telegram.constants import FileDownloadOutOfRange

from .config import DOWNLOAD_DIR, DL_CHUNK

_FILE_RE = re.compile(r'filename\*?=([^;]+)', re.I)

def sanitize_filename(name: str) -> str:
    name = unquote(name)
    name = name.strip().replace("\n", " ").replace("\r", " ")
    name = re.sub(r'[\\/*?:"<>|]+', "_", name)
    return name[:240] or "file"

def pick_name_from_headers(url: str, headers: dict) -> str:
    cd = headers.get("Content-Disposition") or headers.get("content-disposition")
    if cd:
        m = _FILE_RE.search(cd)
        if m:
            v = m.group(1).strip().strip('"').strip("'")
            v = v.split("UTF-8''")[-1]
            return sanitize_filename(v)
    # Fallback to URL path
    path = urlparse(url).path
    name = os.path.basename(path) or "file"
    return sanitize_filename(name)

async def download_http(
    url: str, dest_dir: Path, status_updater: Callable[[str], None]
) -> tuple[Path, Optional[str]]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, allow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            name = pick_name_from_headers(str(r.url), r.headers)
            dest = dest_dir / name
            start = last = time.time()
            done = 0
            last_done = 0
            with open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(DL_CHUNK):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last >= 1.0:
                        speed = (done - last_done) / (now - last)
                        eta = (total - done) / (speed if speed > 0 else 1) if total else -1
                        status_updater(fmt_progress_html("⏬ Downloading", done, total, speed, eta))
                        last = now
                        last_done = done
            mime = r.headers.get("Content-Type")
            return dest, mime

async def download_telegram_file(
    bot: Bot, file_id: str, dest_dir: Path, status_updater: Callable[[str], None]
) -> tuple[Path, Optional[str]]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    tg_file = await bot.get_file(file_id)
    # Build direct file URL and stream with our own progress
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"
    # Guess a sane name
    base = os.path.basename(tg_file.file_path)
    name = sanitize_filename(base or "telegram_file")
    dest = dest_dir / name
    async with aiohttp.ClientSession() as sess:
        async with sess.get(file_url) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            start = last = time.time()
            done = 0
            last_done = 0
            with open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(DL_CHUNK):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last >= 1.0:
                        speed = (done - last_done) / (now - last)
                        eta = (total - done) / (speed if speed > 0 else 1) if total else -1
                        status_updater(fmt_progress_html("⏬ Downloading", done, total, speed, eta))
                        last = now
                        last_done = done
    mime, _ = mimetypes.guess_type(dest.name)
    return dest, mime

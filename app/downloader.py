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
from telegram import Bot
from telegram.constants import FileDownloadOutOfRange
from .utils import card_progress
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
) -> tuple[Path, Optional[str], int]:
    """
    Robust HTTP downloader that supports resume and retries when servers lie about
    Content-Length or drop the connection mid-stream.
    Returns: (dest_path, mime, total_bytes) where total_bytes may be 0 if unknown.
    """
    import aiohttp
    from aiohttp import ClientPayloadError, ClientConnectorError, ContentTypeError
    import asyncio
    import time
    from .utils import card_progress

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Decide filename first (HEAD if possible)
    async with aiohttp.ClientSession() as sess:
        mime = None
        total_declared = 0
        name = None

        # Try HEAD to learn size/name quickly (ignore errors)
        try:
            async with sess.head(url, allow_redirects=True) as hr:
                if hr.status // 100 == 2:
                    total_declared = int(hr.headers.get("Content-Length") or 0)
                    name = pick_name_from_headers(str(hr.url), hr.headers)
                    mime = hr.headers.get("Content-Type")
        except Exception:
            pass  # Some servers disallow HEAD; we’ll figure it out from GET

    # Fallback to name from URL if HEAD failed
    if not name:
        name = pick_name_from_headers(url, {})

    dest = dest_dir / name
    dest_tmp = dest.with_suffix(dest.suffix + ".part")

    # State for progress
    start_time = time.time()
    last_t = start_time
    last_done = 0
    done = 0
    total = total_declared  # may be updated from Content-Range on first 206

    # If a .part file exists from a previous attempt, continue from there
    if dest_tmp.exists():
        done = dest_tmp.stat().st_size

    max_retries = 5
    retries_left = max_retries

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as sess:
        # We always (re)open the file in append mode
        with open(dest_tmp, "ab") as f:
            while True:
                headers = {}
                if done > 0:
                    headers["Range"] = f"bytes={done}-"

                try:
                    async with sess.get(url, allow_redirects=True, headers=headers, timeout=aiohttp.ClientTimeout(total=None)) as r:
                        r.raise_for_status()

                        # Handle sizes
                        # If server honors Range, status is 206 and Content-Range gives us total
                        cr = r.headers.get("Content-Range")
                        if cr and "bytes" in cr and "/" in cr:
                            try:
                                total = int(cr.split("/")[-1])
                            except Exception:
                                pass
                        if total == 0:
                            try:
                                # For 200 (no range) we can still have Content-Length
                                total = int(r.headers.get("Content-Length") or 0)
                            except Exception:
                                total = 0

                        # If server ignored our Range and sent 200, but we had partial data,
                        # restart from scratch (truncate)
                        if done > 0 and r.status == 200:
                            f.seek(0)
                            f.truncate(0)
                            done = 0
                            last_done = 0
                            start_time = last_t = time.time()

                        if not mime:
                            mime = r.headers.get("Content-Type")

                        # Stream
                        async for chunk in r.content.iter_chunked(DL_CHUNK):
                            f.write(chunk)
                            done += len(chunk)

                            now = time.time()
                            if now - last_t >= 1.0:
                                dt = max(0.001, now - last_t)
                                speed = (done - last_done) / dt
                                eta = (total - done) / speed if (speed > 0 and total) else -1
                                elapsed = now - start_time
                                status_updater(card_progress("Downloading File", done, total, speed, elapsed, eta))
                                last_t, last_done = now, done

                        # Successfully reached EOF of this request
                        # If we know total and matched it, we’re done;
                        # if total unknown or we downloaded everything available, also done.
                        if total == 0 or done >= total:
                            break

                        # If we’re here with done < total, the server closed early.
                        # Loop will retry with Range to get the rest.
                        retries_left = max_retries

                except (aiohttp.ContentLengthError, ClientPayloadError, ClientConnectorError, asyncio.TimeoutError, ConnectionResetError) as e:
                    if retries_left > 0:
                        retries_left -= 1
                        # brief backoff
                        await asyncio.sleep(1.0)
                        continue
                    # out of retries
                    raise

    # Finalize file
    os.replace(dest_tmp, dest)
    return dest, mime, total


async def download_telegram_file(bot: Bot, file_id: str, dest_dir: Path, status_updater: Callable[[str], None]) -> tuple[Path, Optional[str], int]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    tg_file = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"
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
                        dt = max(0.001, now - last)
                        speed = (done - last_done) / dt
                        eta = (total - done) / speed if (speed > 0 and total) else -1
                        elapsed = now - start
                        status_updater(card_progress("Downloading File", done, total, speed, elapsed, eta))
                        last, last_done = now, done
    mime, _ = mimetypes.guess_type(dest.name)
    return dest, mime, total

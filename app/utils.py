from __future__ import annotations
import math
import time
import html as _html

# ---------- Humanizers ----------
def human_size(n: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.2f} {units[i]}"

def human_rate(bps: float) -> str:
    return human_size(bps) + "/s" if bps > 0 else "-"

def human_time(seconds: float) -> str:
    if seconds <= 0 or math.isinf(seconds) or math.isnan(seconds):
        return "-"
    s = int(seconds)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

# ---------- Progress cards (HTML) ----------
def card_progress(stage_title: str, done: int, total: int, speed: float, elapsed: float, eta: float) -> str:
    """
    Pretty, emoji-based, monospaced-friendly progress card. Use with parse_mode=HTML.
    """
    total = total or 0
    pct = (done / total * 100.0) if total > 0 else 0.0
    return (
        f"📥 <b>{_html.escape(stage_title)}</b>\n\n"
        f"📊 <b>Size:</b> {human_size(done)} of {human_size(total)}\n"
        f"⚡ <b>Speed:</b> {human_rate(speed)}\n"
        f"⏱️ <b>Time Elapsed:</b> {human_time(elapsed)}\n"
        f"⏳ <b>ETA:</b> {human_time(eta)}\n"
        f"📈 <b>Progress:</b> {pct:.1f}%"
    )

def card_done(title: str, *, file_name: str, size: int, dl_time: float | None = None,
              ul_time: float | None = None, link: str | None = None) -> str:
    rows = [f"✅ <b>{_html.escape(title)}</b>\n"]
    rows.append(f"📄 <b>File:</b> {_html.escape(file_name)}")
    rows.append(f"📦 <b>Size:</b> {human_size(size)}")
    if dl_time is not None:
        rows.append(f"⬇️ <b>Download time:</b> {human_time(dl_time)}")
    if ul_time is not None:
        rows.append(f"⬆️ <b>Upload time:</b> {human_time(ul_time)}")
    if link:
        safe = _html.escape(link, quote=True)
        rows.append(f"🔗 <b>Link:</b> <a href=\"{safe}\">Open in Drive</a>")
    return "\n".join(rows)

# ---------- Throttle ----------
class Throttle:
    """Simple rate limiter for editing messages."""
    def __init__(self, interval: float):
        self.interval = float(interval)
        self._last = 0.0
    def ready(self) -> bool:
        now = time.monotonic()
        if (now - self._last) >= self.interval:
            self._last = now
            return True
        return False

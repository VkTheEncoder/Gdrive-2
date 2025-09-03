from __future__ import annotations
import math
import time
import html as _html

def human_size(n: float) -> str:
    units = ["B","KB","MB","GB","TB"]
    i = 0
    while n >= 1024 and i < len(units)-1:
        n /= 1024.0
        i += 1
    return f"{n:.2f} {units[i]}"

def _human_eta(seconds: float) -> str:
    if seconds <= 0 or math.isinf(seconds) or math.isnan(seconds):
        return "-"
    s = int(seconds)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"

def make_bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(1.0, pct))
    fill = int(round(width * pct))
    return "█" * fill + "░" * (width - fill)

def fmt_progress_html(stage: str, done: int, total: int, speed: float, eta_s: float) -> str:
    pct = (done / total) if total else 0.0
    bar = make_bar(pct)
    pct_txt = f"{pct*100:5.1f}%"
    spd = human_size(speed) + "/s" if speed > 0 else "-"
    eta = _human_eta(eta_s)
    # Use <pre> for fixed width; avoid putting any user-provided strings inside without escaping
    return (
        f"{_html.escape(stage)}\n"
        f"<pre>[{bar}] {pct_txt}\n"
        f"{human_size(done)}/{human_size(total or 0)}  •  {spd}  •  ETA {eta}</pre>"
    )

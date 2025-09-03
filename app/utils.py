from __future__ import annotations
import math
import time

def human_size(n: float) -> str:
    units = ["B","KB","MB","GB","TB"]
    i = 0
    while n >= 1024 and i < len(units)-1:
        n /= 1024.0
        i += 1
    return f"{n:.2f} {units[i]}"

def make_bar(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(1.0, pct))
    fill = int(round(width * pct))
    return "█" * fill + "░" * (width - fill)

class Throttle:
    def __init__(self, interval: float):
        self.interval = interval
        self._last = 0.0
    def ready(self) -> bool:
        now = time.monotonic()
        if (now - self._last) >= self.interval:
            self._last = now
            return True
        return False

def fmt_progress(stage: str, done: int, total: int, speed: float, eta_s: float) -> str:
    pct = (done / total) if total else 0.0
    bar = make_bar(pct)
    pct_txt = f"{pct*100:5.1f}%"
    spd = human_size(speed) + "/s" if speed > 0 else "-"
    eta = f"{int(eta_s)}s" if eta_s > 0 else "-"
    return f"{stage} [{bar}] {pct_txt}\n{human_size(done)}/{human_size(total)}  •  {spd}  •  ETA {eta}"

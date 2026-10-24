"""ساعات التشغيل بتوقيت الرياض، تدعم الفترات التي تتجاوز منتصف الليل"""
from __future__ import annotations

import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

_RANGE = re.compile(r"^\s*(\d{1,2}):?(\d{2})?\s*-\s*(\d{1,2}):?(\d{2})?\s*$")


def parse_hours(spec: str) -> list[tuple[time, time]]:
    """'08:00-02:00, 14:00-16:00' أو فارغ = طوال اليوم"""
    spec = (spec or "").strip()
    if not spec or spec in ("24", "24h", "off", "all"):
        return []
    out = []
    for part in spec.split(","):
        m = _RANGE.match(part)
        if not m:
            raise ValueError(f"صيغة غير صحيحة: {part}. مثال 08:00-02:00")
        h1, m1, h2, m2 = int(m[1]), int(m[2] or 0), int(m[3]), int(m[4] or 0)
        if not (0 <= h1 <= 24 and 0 <= h2 <= 24 and m1 < 60 and m2 < 60):
            raise ValueError(f"وقت غير صحيح: {part}")
        out.append((time(h1 % 24, m1), time(h2 % 24, m2)))
    return out


def in_hours(spec: str, tz: str, now: datetime | None = None) -> bool:
    ranges = parse_hours(spec)
    if not ranges:
        return True
    now = now or datetime.now(ZoneInfo(tz))
    t = now.astimezone(ZoneInfo(tz)).time()
    for a, b in ranges:
        if a == b:
            return True
        if a < b and a <= t < b:
            return True
        if a > b and (t >= a or t < b):   # فترة تعبر منتصف الليل
            return True
    return False

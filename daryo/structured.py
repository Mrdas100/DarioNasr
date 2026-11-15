"""Conservative source extraction for ticket prices and explicitly marked absences.

No inferred dates, opponents, medical statuses or prices. Unmatched source text
stays in the body. Extraction happens before emoji and newline cleanup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import BIDI_RE, strip_decor, tidy_punct


@dataclass
class StructuredPost:
    template: str
    headline: str
    body: str = ""
    rows: list[tuple[str, str]] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


FULL_TIME = re.compile(r"(?:نهاية\s+(?:المباراة|اللقاء)|انتهت\s+(?:المباراة|المواجهة)|انتهى\s+اللقاء|"
                       r"صافرة\s+النهاية|النتيجة\s+النهائية|\bFT\b)", re.I)
SCORE = re.compile(r"(?P<a>[\u0621-\u064A]{2,})\s*\(?\s*(?P<sa>\d{1,2})\s*\)?\s*[-–—×xX:]\s*"
                   r"\(?\s*(?P<sb>\d{1,2})\s*\)?\s*(?P<b>[\u0621-\u064A]{2,})")


def _result(text: str) -> StructuredPost | None:
    """«النصر 3-1 الاتفاق» with an explicit full-time marker; one-word team names
    exactly as written. Anything less certain stays ordinary news."""
    if not FULL_TIME.search(text):
        return None
    lines = [x for x in text.splitlines() if x.strip()]
    for i, line in enumerate(lines):
        flat = strip_decor(line)
        m = SCORE.search(flat)
        if not m or "النصر" not in (m.group("a"), m.group("b")) or m.group("a") == m.group("b"):
            continue
        rest = [_clean(FULL_TIME.sub("", strip_decor(x))) for j, x in enumerate(lines) if j != i]
        rest = [x for x in rest if x]
        return StructuredPost("result", rest[0] if rest else "", "\n".join(rest[1:]),
                              extra=dict(home=m.group("a"), away=m.group("b"),
                                         home_score=m.group("sa"), away_score=m.group("sb")))
    return None


def is_ticket_post(raw: str) -> bool:
    return bool(re.search(r"(?:تذاكر|التذاكر)", raw) and
                re.search(r"(?:النصر|الأهلي|الاهلي|webook\.com)", raw, re.I))


def _clean(text: str) -> str:
    return tidy_punct(strip_decor(text)).strip(" ()،,:؛-•")


def extract(raw: str) -> StructuredPost | None:
    text = BIDI_RE.sub("", raw or "")
    result = _result(text)
    if result is not None:
        return result
    if is_ticket_post(text):
        # Prefer explicit parentheses, then a small set of stand names. Each
        # match retains the numeric spelling and range order of the source.
        price = re.compile(
            r"(?:\(\s*(?P<label>[^()\n:：]{2,32})\s*\)|"
            r"(?P<known>خلف\s+المرمى|الواجهة|الواجهه|زوايا|الزوايا|دور\s+ثالث|الدور\s+الثالث))"
            r"\s*[:：]?\s*(?P<value>(?:من\s*)?\d+(?:\s*[-–—]\s*\d+)?)\s*ريال"
        )
        matches = list(price.finditer(text))
        rows = [(_clean(m.group('label') or m.group('known')),
                 re.sub(r"\s*[-–—]\s*", "–", m.group('value').strip()) + " ريال") for m in matches]
        remainder = text
        for m in reversed(matches):
            remainder = remainder[:m.start()] + " " + remainder[m.end():]
        lines = [_clean(x) for x in remainder.splitlines()]
        lines = [x for x in lines if x and not re.match(r"^(?:رابط|للحجز)\b", x)]
        if not lines:
            return None
        heading = lines.pop(0)
        # An unbroken price announcement may contain all the rows in its first
        # line; the heading is retained exactly rather than shortened mid-name.
        return StructuredPost("tickets", heading, "\n".join(lines), rows)
    if re.search(r"(?:غيابات|إصابات|اصابات)", text) and "❌" in text:
        # Only accept one consistently marked list. Retain mixed / ambiguous
        # status posts as ordinary news rather than assign a false status.
        if re.search(r"[✅✔🟢]", text):
            return None
        heading, sep, rest = text.partition("\n")
        if not sep:
            heading, sep, rest = text.partition(":")
        if not sep:
            return None
        rows, tail = [], ""
        for part in re.split(r"\(?\s*❌\s*\)?", rest):
            name = _clean(part)
            if not name:
                continue
            if re.search(r"(?:تبقى|تبقّى|باقي|يوم|موعد)", name):
                tail = name
            else:
                rows.append((name, "مصاب" if re.search(r"(?:إصابات|اصابات)", heading) else "غائب"))
        if rows and len(rows) <= 20:
            return StructuredPost("availability", _clean(heading), tail, rows)
    return None

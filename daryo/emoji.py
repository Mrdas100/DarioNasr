"""إيموجي أبل داخل نص التصميم: تقسيم النص إلى كلمات وإيموجي، وجلب صورة كل إيموجي

الصور من مكتبة emoji-datasource-apple: تُنزّل وقت البناء للأكثر استخدامًا،
وأي إيموجي جديد يُنزّل مرة واحدة ويُحفظ في مجلد البيانات. إن تعذر جلبه يُحذف من التصميم
"""
from __future__ import annotations

import logging
import re
import threading
import urllib.request
from pathlib import Path

from PIL import Image

log = logging.getLogger("daryo.emoji")

_BASE = ("\U0001F000-\U0001F1E5\U0001F200-\U0001FAFF☀-➿⬀-⯿⌀-⏿"
         "←-⇿■-◿‼⁉™ℹ〰〽")
_MOD = "(?:️|[\U0001F3FB-\U0001F3FF])*"
CLUSTER = re.compile(f"(?:[\U0001F1E6-\U0001F1FF]{{2}}|[{_BASE}]{_MOD}(?:‍[{_BASE}]{_MOD})*)")
_STRAY = re.compile("[️‍\U0001F3FB-\U0001F3FF\U0001F1E6-\U0001F1FF⃣]")

SOURCES = ["https://cdn.jsdelivr.net/npm/emoji-datasource-apple@15.1.2/img/apple/64/{}.png",
           "https://unpkg.com/emoji-datasource-apple@15.1.2/img/apple/64/{}.png"]
BUNDLED = Path(__file__).resolve().parent.parent / "assets" / "emoji"


def is_emoji_char(ch: str) -> bool:
    return bool(CLUSTER.fullmatch(ch) or _STRAY.fullmatch(ch))


def runs(text: str) -> list[tuple[bool, str]]:
    """[(إيموجي؟, نص)] بالترتيب المنطقي للنص"""
    out, pos = [], 0
    for m in CLUSTER.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group()))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def names(cluster: str) -> list[str]:
    cps = [f"{ord(c):x}" for c in cluster]
    full = "-".join(cps)
    bare = "-".join(c for c in cps if c != "fe0f")
    cands = [full, bare]
    if len(cps) == 1:
        cands.append(f"{cps[0]}-fe0f")
    return list(dict.fromkeys(cands))


def tidy(text: str, max_run: int = 2) -> str:
    """إيموجي بداية السطر زخرفة تُحذف، والتكرار الطويل يُختصر"""
    lines = []
    for line in text.split("\n"):
        line = re.sub(f"^(?:\\s*(?:{CLUSTER.pattern}))+\\s*", "", line)
        line = re.sub(f"((?:{CLUSTER.pattern})\\s*){{{max_run + 1},}}",
                      lambda m: "".join(CLUSTER.findall(m.group())[:max_run]) + " ", line)
        lines.append(line)
    return "\n".join(lines)


class EmojiStore:
    def __init__(self, cache_dir: Path | None = None, download: bool = True):
        self.dirs = [BUNDLED] + ([cache_dir] if cache_dir else [])
        self.cache_dir = cache_dir
        self.download = download
        self._img: dict[str, Image.Image | None] = {}
        self._lock = threading.Lock()

    def _find(self, cluster: str) -> Path | None:
        for n in names(cluster):
            for d in self.dirs:
                p = d / f"{n}.png"
                if p.exists():
                    return p
        if not (self.download and self.cache_dir):
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for n in names(cluster):
            for src in SOURCES:
                try:
                    data = urllib.request.urlopen(src.format(n), timeout=10).read()
                except Exception:
                    continue
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    p = self.cache_dir / f"{n}.png"
                    p.write_bytes(data)
                    return p
        log.info("لا توجد صورة أبل للإيموجي %s فلن يظهر", cluster.encode("unicode_escape"))
        return None

    def get(self, cluster: str) -> Image.Image | None:
        with self._lock:
            if cluster not in self._img:
                p = self._find(cluster)
                try:
                    self._img[cluster] = Image.open(p).convert("RGBA") if p else None
                except Exception:
                    self._img[cluster] = None
            return self._img[cluster]

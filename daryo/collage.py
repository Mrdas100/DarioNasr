"""ألبوم الخبر: كل صور الألبوم كاملة (بلا قص) في لوحة واحدة تُوضع مكان الصورة في التصميم"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

from PIL import Image, ImageOps

CW = 1904                # عرض اللوحة (ضعف مساحة الصورة تقريبًا لحدة أعلى)
GAP = 14
MAX_PHOTOS = 4
SLOT = (1000, 1150)      # المساحة التقريبية للصورة في التصميم
ASPECT = (0.55, 2.4)     # حدود نسبة عرض اللوحة لارتفاعها


def _rows(n: int):
    """كل طرق تقسيم n صور متتالية إلى صفوف (حد أقصى 3 في الصف)"""
    for k in range(n):
        for cuts in combinations(range(1, n), k):
            b = (0, *cuts, n)
            rows = [list(range(b[i], b[i + 1])) for i in range(len(b) - 1)]
            if all(len(r) <= 3 for r in rows):
                yield rows


def _layout(aspects: list[float]):
    """صفوف مضبوطة: كل صف بعرض اللوحة وارتفاعه يحفظ نسب صوره، فلا قص ولا فراغ"""
    best = None
    for rows in _rows(len(aspects)):
        hs = [(CW - GAP * (len(r) - 1)) / sum(aspects[i] for i in r) for r in rows]
        total = sum(hs) + GAP * (len(rows) - 1)
        # لوحة بنسبة معقولة (لا شريط طويل جدًا ولا عريض جدًا)، ثم أكبر حجم تظهر به أصغر صورة
        ratio = CW / total
        off = max(0.0, ASPECT[0] - ratio, ratio - ASPECT[1])
        fit = min(SLOT[0] / CW, SLOT[1] / total)
        score = (off, -min(h * h * aspects[i] for r, h in zip(rows, hs) for i in r) * fit * fit)
        if best is None or score < best[0]:
            best = (score, rows, hs, total)
    return best[1], best[2], int(round(best[3]))


def make_collage(paths: list[str], out: Path) -> str:
    ims = [ImageOps.exif_transpose(Image.open(p)).convert("RGB") for p in paths[:MAX_PHOTOS]]
    rows, hs, total = _layout([im.width / im.height for im in ims])
    canvas = Image.new("RGB", (CW, total), (255, 255, 255))
    y = 0.0
    for r, h in zip(rows, hs):
        x = 0.0
        for j, i in enumerate(r):
            im = ims[i]
            # آخر صورة في الصف تأخذ ما تبقى من العرض (فرق بكسل واحد من التقريب)
            w = CW - int(round(x)) if j == len(r) - 1 else int(round(h * im.width / im.height))
            canvas.paste(im.resize((max(1, w), int(round(h))), Image.LANCZOS), (int(round(x)), int(round(y))))
            x += w + GAP
        y += h + GAP
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=92)
    return str(out)

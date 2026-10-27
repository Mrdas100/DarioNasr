"""ألبوم الخبر: كل صور الألبوم في شبكة واحدة تُوضع مكان الصورة في التصميم"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

CW, CH = 1904, 2000      # ضعف مساحة الصورة تقريبًا لحدة أعلى
GAP = 14
MAX_PHOTOS = 4


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    # قص من المنتصف مع ميل للأعلى حتى لا تُقص الوجوه
    return ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(0.5, 0.35))


def _cells(n: int, landscape: bool) -> list[tuple[int, int, int, int]]:
    half_w, half_h = (CW - GAP) // 2, (CH - GAP) // 2
    if n == 2:
        if landscape:   # صورتان عريضتان: فوق بعض
            return [(0, 0, CW, half_h), (0, half_h + GAP, CW, CH)]
        return [(0, 0, half_w, CH), (half_w + GAP, 0, CW, CH)]
    if n == 3:          # كبيرة فوق واثنتان تحت
        top = int(CH * 0.55)
        return [(0, 0, CW, top), (0, top + GAP, half_w, CH), (half_w + GAP, top + GAP, CW, CH)]
    return [(0, 0, half_w, half_h), (half_w + GAP, 0, CW, half_h),
            (0, half_h + GAP, half_w, CH), (half_w + GAP, half_h + GAP, CW, CH)]


def make_collage(paths: list[str], out: Path) -> str:
    ims = [ImageOps.exif_transpose(Image.open(p)).convert("RGB") for p in paths[:MAX_PHOTOS]]
    landscape = sum(im.width / im.height for im in ims) / len(ims) > 1.2
    canvas = Image.new("RGB", (CW, CH), (255, 255, 255))
    for im, (x0, y0, x1, y1) in zip(ims, _cells(len(ims), landscape)):
        canvas.paste(_cover(im, x1 - x0, y1 - y0), (x0, y0))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=92)
    return str(out)

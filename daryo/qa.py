"""المراجعة الآلية قبل الإرسال: الخط، الحروف، المحاذاة، الحدود الآمنة، الصورة، المقاس"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageStat

from .config import APPROVED_FONTS
from .emoji import is_emoji_char
from .models import Snap
from .render import FOOTER_TOP, H, SAFE_TOP, SIDE, W, Layout

# حروف تحكم اتجاه لا تحتاج رسمًا
IGNORABLE = {"‌", "‍", "‎", "‏", "\n", " "}


class QAError(Exception):
    pass


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_font(path: Path) -> None:
    if not Path(path).exists():
        raise QAError(f"ملف الخط غير موجود: {path}")
    digest = file_sha256(path)
    if digest not in APPROVED_FONTS:
        raise QAError("ملف الخط ليس من الخطوط المعتمدة. أوقف التصميم")


@lru_cache(maxsize=2)
def _cmap(path: str) -> frozenset[int]:
    return frozenset(TTFont(path)["cmap"].getBestCmap().keys())


def missing_glyphs(text: str, font_path: Path) -> set[str]:
    cmap = _cmap(str(font_path))
    # الإيموجي يُرسم بصور أبل وليس بالخط
    return {ch for ch in text if ch not in IGNORABLE and ord(ch) not in cmap and not is_emoji_char(ch)}


def strip_unsupported(text: str, font_path: Path) -> str:
    cmap = _cmap(str(font_path))
    return "".join(ch for ch in text if ch in IGNORABLE or ord(ch) in cmap or is_emoji_char(ch))


def check_snap_text(snap: Snap, font_path: Path) -> None:
    for t in snap.all_text():
        miss = missing_glyphs(t, font_path)
        if miss:
            raise QAError(f"حروف غير مدعومة في Arial Bold: {' '.join(sorted(miss))}")
    if not snap.headline and not snap.quote:
        raise QAError("لا يوجد عنوان")


def check_image_file(path: str) -> None:
    """صورة المصدر: سليمة وغير صغيرة وغير فارغة"""
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im = im.convert("RGB")
            if min(im.size) < 320:
                raise QAError(f"صورة المصدر صغيرة جدًا {im.size}")
            stat = ImageStat.Stat(im.resize((64, 64)))
            if max(stat.stddev) < 4:
                raise QAError("صورة المصدر شبه فارغة")
    except QAError:
        raise
    except Exception as e:
        raise QAError(f"صورة المصدر تالفة: {e}")


def _overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def check_render(img: Image.Image, lay: Layout, snap: Snap) -> list[str]:
    """يعيد قائمة مشكلات. القائمة الفارغة تعني أن التصميم سليم"""
    problems: list[str] = []
    if img.size != (W, H):
        problems.append(f"المقاس {img.size} بدل {W}x{H}")
    if img.mode != "RGB":
        problems.append("نمط الألوان غير صحيح")
    if lay.overflow:
        problems.append(f"نص لم يتسع بالحجم المقبول: {', '.join(lay.overflow)}")
    if snap.image_path and not lay.image_used:
        problems.append("الصورة لم تُوضع في التصميم")
    if lay.image_used and lay.image_scale > 2.2:
        problems.append("الصورة مكبرة أكثر من اللازم وستظهر مشوشة")

    content = [(n, b) for n, b in lay.boxes if n not in ("footer",)]
    for name, b in content:
        if name.startswith("text:") or name.startswith("chip:") or name in ("photo", "logo"):
            margin = 0 if name == "photo" else SIDE - 12   # الصورة قد تملأ عرض التصميم
            if b[0] < margin or b[2] > W - margin:
                problems.append(f"{name} خارج الهامش الجانبي الآمن")
            if b[1] < SAFE_TOP - 2 and name != "photo":   # الصورة قد تبدأ من أعلى التصميم
                problems.append(f"{name} داخل منطقة واجهة سناب العلوية")
            if b[3] > FOOTER_TOP and name != "photo":
                problems.append(f"{name} يتداخل مع شريط الحقوق")
    names = [(n, b) for n, b in content if n.startswith("text:") or n in ("photo", "logo", "bar")
             or n.startswith("chip:")]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            (n1, b1), (n2, b2) = names[i], names[j]
            if "photo" in (n1, n2):
                other = n2 if n1 == "photo" else n1
                # الشعار والتبويبات فوق الصورة مقصودة، والنص فوق الصورة مقصود في قالب البوستر
                if other == "logo" or other.startswith("chip:") or lay.text_on_photo:
                    continue
            if _overlap(b1, b2):
                problems.append(f"تداخل بين {n1} و {n2}")
    # التأكد من أن النصوص المطلوبة رُسمت فعلًا
    drawn = " ".join(lay.texts)
    for t in (snap.headline, snap.quote):
        if t and t.split()[0] not in drawn:
            problems.append("العنوان لم يُرسم كاملًا")
    # الخطوط المستخدمة: Arial Bold فقط
    for f in lay.fonts:
        if file_sha256(Path(f)) not in APPROVED_FONTS:
            problems.append(f"خط غير معتمد استُخدم: {f}")
    # الصورة غير فارغة
    if max(ImageStat.Stat(img.resize((54, 96))).stddev) < 10:
        problems.append("التصميم الناتج شبه فارغ")
    return problems

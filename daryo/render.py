"""محرك تصميم السنابات 1080×1920 بخط Arial Bold فقط مع تشكيل عربي كامل (Raqm + FriBiDi)"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

from .models import TEMPLATE_AR, Snap

W, H = 1080, 1920
SIDE = 64                 # هامش جانبي آمن
SAFE_TOP = 150            # منطقة اسم الحساب في واجهة سناب
FOOTER_TOP = 1690         # بداية شريط الحقوق
FOOTER_TEXT_Y = 1748      # منتصف نص الحقوق (فوق منطقة الرد في سناب)
CONTENT_BOTTOM = FOOTER_TOP - 36

RED = (213, 18, 38)
DARK_RED = (168, 10, 26)
BLACK = (17, 17, 17)
WHITE = (255, 255, 255)
GREY = (120, 120, 120)
WATERMARK = (247, 247, 247)


class RenderError(Exception):
    pass


@dataclass
class Layout:
    """تقرير التخطيط لفحص الجودة"""
    boxes: list[tuple[str, tuple[int, int, int, int]]] = field(default_factory=list)
    overflow: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    image_used: bool = False
    image_scale: float = 0.0
    fonts: set[str] = field(default_factory=set)

    def add(self, name, box):
        self.boxes.append((name, tuple(int(v) for v in box)))


class Renderer:
    def __init__(self, font_path: Path, logo_path: Path | None, handle: str, account_name: str):
        if not features.check("raqm"):
            raise RenderError("مكتبة Raqm غير متوفرة: لا يمكن تشكيل العربية بشكل صحيح")
        self.font_path = str(font_path)
        self.logo_path = logo_path if logo_path and Path(logo_path).exists() else None
        self.handle = handle
        self.account_name = account_name
        self._cache: dict[int, ImageFont.FreeTypeFont] = {}

    # ---------- أدوات الخط ----------
    def font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._cache:
            self._cache[size] = ImageFont.truetype(self.font_path, size, layout_engine=ImageFont.Layout.RAQM)
        return self._cache[size]

    def width(self, text: str, size: int) -> float:
        return self.font(size).getlength(text, direction="rtl", language="ar")

    def wrap(self, text: str, size: int, max_w: int) -> list[str]:
        lines, cur = [], ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if self.width(trial, size) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def balance(self, text: str, size: int, max_w: int, n: int) -> list[str]:
        """يوازن أطوال الأسطر حتى لا تبقى كلمة يتيمة في السطر الأخير"""
        best = self.wrap(text, size, max_w)
        if n <= 1:
            return best
        lo, hi = max_w * 0.45, max_w
        while hi - lo > 4:
            mid = (lo + hi) / 2
            trial = self.wrap(text, size, int(mid))
            if len(trial) <= n and all(self.width(l, size) <= mid for l in trial):
                best, hi = trial, mid
            else:
                lo = mid
        return best

    def fit(self, text: str, max_w: int, start: int, minimum: int, max_lines: int):
        """أكبر حجم خط يجعل النص ضمن العرض وعدد الأسطر"""
        size = start
        while size >= minimum:
            lines = self.wrap(text, size, max_w)
            if len(lines) <= max_lines and all(self.width(l, size) <= max_w for l in lines):
                return size, self.balance(text, size, max_w, len(lines))
            size -= 3
        return None, self.wrap(text, minimum, max_w)

    @staticmethod
    def line_h(size: int) -> int:
        return int(size * (1.42 if size < 120 else 1.12))

    def draw_lines(self, d: ImageDraw.ImageDraw, lines, size, y, color, lay: Layout, name: str,
                   align: str = "center", x_right: int = W - SIDE) -> int:
        f = self.font(size)
        lay.fonts.add(self.font_path)
        top = y
        for line in lines:
            if align == "center":
                d.text((W / 2, y), line, font=f, fill=color, anchor="ma", direction="rtl", language="ar")
            else:
                d.text((x_right, y), line, font=f, fill=color, anchor="ra", direction="rtl", language="ar")
            lay.texts.append(line)
            y += self.line_h(size)
        maxw = max((self.width(l, size) for l in lines), default=0)
        if align == "center":
            lay.add(name, (W / 2 - maxw / 2, top, W / 2 + maxw / 2, y))
        else:
            lay.add(name, (x_right - maxw, top, x_right, y))
        return y

    # ---------- عناصر الهوية ----------
    def watermark(self, img: Image.Image) -> None:
        d = ImageDraw.Draw(img)
        f = self.font(40)
        text = f"{self.account_name}   {self.handle}"
        tw = int(f.getlength(text, direction="rtl", language="ar")) + 120
        for row, y in enumerate(range(-20, H, 170)):
            off = -(row % 2) * tw // 2
            for x in range(off, W + tw, tw):
                d.text((x, y), text, font=f, fill=WATERMARK, direction="rtl", language="ar")

    def logo(self, img: Image.Image, lay: Layout) -> tuple[int, int, int, int]:
        box_w, box_h = 220, 200
        x1, y0 = W - SIDE + 10, SAFE_TOP + 4
        if self.logo_path:
            logo = Image.open(self.logo_path).convert("RGBA")
            bbox = logo.getchannel("A").getbbox()
            if bbox:
                logo = logo.crop(bbox)
            logo.thumbnail((box_w, box_h), Image.LANCZOS)
            pos = (x1 - logo.width, y0)
            img.paste(logo, pos, logo)
            box = (pos[0], y0, x1, y0 + logo.height)
        else:
            # شعار نصي مؤقت إلى أن يُرفع ملف الشعار الأصلي assets/logo.png
            d = ImageDraw.Draw(img)
            parts = self.account_name.split(maxsplit=1)
            first, rest = parts[0], (parts[1] if len(parts) > 1 else "")
            size = 98
            w1 = self.width(first, size)
            w2 = self.width(rest, size) if rest else 0
            gap = 18 if rest else 0
            d.text((x1, y0), first, font=self.font(size), fill=BLACK, anchor="ra", direction="rtl", language="ar")
            if rest:
                d.text((x1 - w1 - gap, y0), rest, font=self.font(size), fill=RED, anchor="ra",
                       direction="rtl", language="ar")
            total = w1 + gap + w2
            y = y0 + 128
            d.rectangle((x1 - total, y, x1, y + 6), fill=BLACK)
            d.text((x1, y + 14), self.handle, font=self.font(42), fill=BLACK, anchor="ra")
            box = (int(x1 - total), y0, x1, y + 62)
        lay.add("logo", box)
        return box

    def chip(self, d, x_left: int, y: int, text: str, filled: bool, lay: Layout) -> int:
        size = 44
        tw = self.width(text, size)
        pad = 30
        box = (x_left, y, x_left + tw + pad * 2, y + 78)
        if filled:
            d.rounded_rectangle(box, 39, fill=RED)
            color = WHITE
        else:
            d.rounded_rectangle(box, 39, outline=BLACK, width=4, fill=WHITE)
            color = BLACK
        d.text(((box[0] + box[2]) / 2, y + 39), text, font=self.font(size), fill=color, anchor="mm",
               direction="rtl", language="ar")
        lay.add(f"chip:{text}", box)
        lay.texts.append(text)
        return box[2] + 14

    def bar(self, d, y: int, label: str, style: str, lay: Layout) -> int:
        if style == "breaking":
            h = 116
            d.rectangle((0, y, W, y + h), fill=RED)
            size = 84
            tw = self.width(label, size)
            cy = y + h / 2
            d.text((W / 2, cy + 3), label, font=self.font(size), fill=WHITE, anchor="mm",
                   direction="rtl", language="ar")
            # أيقونة 🚨 مرسومة (الخط المعتمد لا يحتوي رموزًا تعبيرية)
            icon = self.siren_img(76)
            for cx in (W / 2 + tw / 2 + 66, W / 2 - tw / 2 - 66):
                self._canvas.paste(icon, (int(cx - 38), int(cy - 42)), icon)
        elif style == "dark":
            h = 96
            d.rectangle((0, y, W, y + h), fill=BLACK)
            d.rectangle((0, y + h, W, y + h + 12), fill=RED)
            d.text((W / 2, y + h / 2 + 2), label, font=self.font(64), fill=WHITE, anchor="mm",
                   direction="rtl", language="ar")
            h += 12
        else:  # red
            h = 100
            d.rectangle((0, y, W, y + h), fill=RED)
            d.text((W / 2, y + h / 2 + 2), label, font=self.font(68), fill=WHITE, anchor="mm",
                   direction="rtl", language="ar")
        lay.add("bar", (0, y, W, y + h))
        lay.texts.append(label)
        return y + h

    _siren_cache: dict = {}

    def siren_img(self, size: int) -> Image.Image:
        """صفارة إنذار 🚨 مرسومة بالأبيض بدقة عالية ثم مصغّرة لحواف ناعمة"""
        if size in self._siren_cache:
            return self._siren_cache[size]
        S = size * 4
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        cx = S / 2
        base_y = S * 0.86
        dome_top = S * 0.34
        r = S * 0.26
        d.rounded_rectangle((cx - r * 1.35, base_y - S * 0.12, cx + r * 1.35, base_y), S * 0.03, fill=WHITE)
        d.pieslice((cx - r, dome_top, cx + r, dome_top + 2 * r), 180, 360, fill=WHITE)
        d.rectangle((cx - r, dome_top + r, cx + r, base_y - S * 0.12), fill=WHITE)
        # لمعة داخل القبة
        d.rounded_rectangle((cx - r * 0.55, dome_top + r * 0.45, cx - r * 0.25, base_y - S * 0.2), S * 0.02, fill=RED)
        w = int(S * 0.07)
        for (x0, y0, x1, y1) in ((cx, S * 0.05, cx, S * 0.22),
                                 (cx - S * 0.30, S * 0.16, cx - S * 0.40, S * 0.06),
                                 (cx + S * 0.30, S * 0.16, cx + S * 0.40, S * 0.06)):
            d.line((x0, y0, x1, y1), fill=WHITE, width=w)
            for x, y in ((x0, y0), (x1, y1)):
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=WHITE)
        im = im.resize((size, size), Image.LANCZOS)
        self._siren_cache[size] = im
        return im

    def footer(self, img: Image.Image, lay: Layout) -> None:
        d = ImageDraw.Draw(img)
        d.rectangle((0, FOOTER_TOP, W, H), fill=RED)
        d.rectangle((0, FOOTER_TOP, W, FOOTER_TOP + 6), fill=DARK_RED)
        d.text((SIDE, FOOTER_TEXT_Y), self.handle, font=self.font(54), fill=WHITE, anchor="lm")
        d.text((W - SIDE, FOOTER_TEXT_Y), self.account_name, font=self.font(50), fill=WHITE, anchor="rm",
               direction="rtl", language="ar")
        hw = self.font(54).getlength(self.handle)
        d.line((SIDE + hw + 24, FOOTER_TEXT_Y - 22, SIDE + hw + 24, FOOTER_TEXT_Y + 22), fill=WHITE, width=3)
        lay.add("footer", (0, FOOTER_TOP, W, H))
        lay.texts += [self.handle, self.account_name]

    # ---------- الصورة ----------
    def load_photo(self, path: str | None):
        if not path:
            return None
        try:
            im = Image.open(path)
            im = ImageOps.exif_transpose(im).convert("RGB")
        except Exception as e:  # صورة تالفة
            raise RenderError(f"تعذر فتح صورة الخبر: {e}")
        return im

    @staticmethod
    def crop_box(w: int, h: int, box_w: int, box_h: int, keep: float = 0.62) -> tuple[int, int, int, int]:
        """قص من المنتصف يقرّب نسبة الصورة من المساحة المتاحة ليكبر حجمها، مع إبقاء 62٪ منها على الأقل"""
        target = box_h / box_w
        ratio = h / w
        if ratio > target:      # أطول من المساحة: نقص من الأعلى والأسفل
            nh = max(int(w * target), int(h * keep))
            return 0, (h - nh) // 2, w, (h - nh) // 2 + nh
        nw = max(int(h / target), int(w * keep))
        return (w - nw) // 2, 0, (w - nw) // 2 + nw, h

    def fit_crop(self, photo: Image.Image, box_w: int, box_h: int) -> Image.Image:
        return photo.crop(self.crop_box(photo.width, photo.height, box_w, box_h))

    def place_photo(self, img: Image.Image, photo: Image.Image, top: int, bottom: int, lay: Layout) -> int:
        box_w = W - 2 * SIDE
        box_h = bottom - top
        if box_h < 380:
            raise RenderError("المساحة المتبقية للصورة غير كافية")
        # احتواء بدون قص ولا تشويه للحفاظ على تفاصيل الصورة الأصلية
        scale = min(box_w / photo.width, box_h / photo.height)
        nw, nh = int(photo.width * scale), int(photo.height * scale)
        resized = photo.resize((nw, nh), Image.LANCZOS)
        x = (W - nw) // 2
        # ظل ناعم وإطار وزوايا دائرية (لا تغيّر محتوى الصورة)
        shadow = Image.new("RGBA", (nw + 60, nh + 60), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((30, 36, nw + 30, nh + 36), 26, fill=(0, 0, 0, 70))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        img.paste(shadow, (x - 30, top - 30), shadow)
        mask = Image.new("L", (nw, nh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, nw - 1, nh - 1), 26, fill=255)
        img.paste(resized, (x, top), mask)
        ImageDraw.Draw(img).rounded_rectangle((x, top, x + nw - 1, top + nh - 1), 26, outline=(230, 230, 230), width=3)
        lay.add("photo", (x, top, x + nw, top + nh))
        lay.image_used = True
        lay.image_scale = scale
        return top + nh

    # ---------- التصميم ----------
    def render(self, snap: Snap) -> tuple[Image.Image, Layout]:
        lay = Layout()
        img = Image.new("RGB", (W, H), WHITE)
        self._canvas = img
        self.watermark(img)
        d = ImageDraw.Draw(img)
        logo_box = self.logo(img, lay)

        # شارات أعلى اليسار: تحديث / غير رسمي
        cx = SIDE
        if snap.is_update:
            cx = self.chip(d, cx, SAFE_TOP + 24, "تحديث", True, lay)
        if snap.is_rumor:
            self.chip(d, cx, SAFE_TOP + 24, "غير رسمي", False, lay)

        y = max(logo_box[3], SAFE_TOP + 100) + 24
        t = snap.template
        if t == "breaking":
            y = self.bar(d, y, TEMPLATE_AR["breaking"], "breaking", lay)
        elif t in ("statement", "transfer"):
            y = self.bar(d, y, TEMPLATE_AR[t], "dark", lay)
        elif t == "stats":
            y = self.bar(d, y, TEMPLATE_AR["stats"], "red", lay)
        else:
            # الأخبار العامة: خط أحمر رفيع بدل الشريط
            d.rectangle((SIDE, y + 8, W - SIDE, y + 16), fill=RED)
            lay.add("rule", (SIDE, y + 8, W - SIDE, y + 16))
            y += 16
        content_top = y + 30

        photo = self.load_photo(snap.image_path)
        has_photo = photo is not None
        max_w = W - 2 * SIDE - (20 if photo is not None else 110)
        avail = CONTENT_BOTTOM - content_top
        # حجم النصوص أكبر في القالب النصي. مع الصورة نصغّر النص تدريجيًا حتى تتسع الصورة دائمًا
        tiers = [(1.0, False), (0.9, False), (0.8, False), (0.8, True), (0.7, True)] if has_photo else [(1.22, False)]
        base_boxes, base_texts = list(lay.boxes), list(lay.texts)
        for k, drop_body in tiers:
            lay.boxes, lay.overflow, lay.texts = list(base_boxes), [], list(base_texts)
            text_img, text_h = self._text_layer(snap, k, drop_body, max_w, lay, compact=has_photo)
            if not has_photo or avail - text_h - 40 >= 760:
                break
        avail = CONTENT_BOTTOM - content_top
        if has_photo:
            photo_space = avail - text_h - 40
            if photo_space < 400:
                raise RenderError("النص طويل ولا يترك مساحة كافية للصورة")
            box_w = W - 2 * SIDE
            photo = self.fit_crop(photo, box_w, photo_space)
            ph = min(photo_space, int(photo.height * min(box_w / photo.width, photo_space / photo.height)))
            slack = max(0, avail - text_h - 40 - ph)
            text_top = content_top + slack // 2
            self._paste_text(img, text_img, text_top, text_h, lay)
            self.place_photo(img, photo, text_top + text_h + 40, text_top + text_h + 40 + ph, lay)
        else:
            if text_h > avail:
                raise RenderError("النص أطول من المساحة المتاحة")
            text_top = content_top + (avail - text_h) // 2
            # إطار أنيق حول النص في القالب النصي
            ImageDraw.Draw(img).rectangle((SIDE + 6, text_top - 50, SIDE + 14, text_top + text_h + 30), fill=RED)
            ImageDraw.Draw(img).rectangle((W - SIDE - 14, text_top - 50, W - SIDE - 6, text_top + text_h + 30), fill=RED)
            self._paste_text(img, text_img, text_top, text_h, lay)

        self.footer(img, lay)
        return img, lay

    def _text_layer(self, snap: Snap, k: float, drop_body: bool, max_w: int, lay: Layout, compact=False):
        text_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(text_img)
        ty = 0
        for name, text, start, minimum, max_lines, color, gap in self._blocks(snap, k):
            if compact:
                # مع صورة أو فيديو: الوسائط هي الأساس والنص مختصر في أعلى التصميم
                start, minimum = start * 0.82, minimum * 0.85
                max_lines = min(max_lines, 2 if name in ("text:headline", "text:quote") else 3)
            if drop_body and name == "text:body":
                continue
            minimum = min(int(minimum), int(start))
            size, lines = self.fit(text, max_w, int(start), int(minimum * min(1.0, k)), max_lines)
            if size is None:
                lay.overflow.append(name)
                size = int(minimum)
                lines = lines[:max_lines]
            ty += gap
            ty = self.draw_lines(td, lines, size, ty, color, lay, name)
        return text_img, ty

    def _paste_text(self, img, text_img, top, h, lay: Layout):
        crop = text_img.crop((0, 0, W, h + 10))
        img.paste(crop, (0, top), crop)
        # إزاحة صناديق النصوص إلى موقعها النهائي
        fixed = []
        for name, (x0, y0, x1, y1) in lay.boxes:
            if name.startswith("text:"):
                fixed.append((name, (x0, y0 + top, x1, y1 + top)))
            else:
                fixed.append((name, (x0, y0, x1, y1)))
        lay.boxes = fixed

    def _blocks(self, s: Snap, k: float):
        """(اسم، نص، حجم البداية، أدنى حجم، أقصى أسطر، لون، فراغ قبله)"""
        b = []
        if s.kicker:
            b.append(("text:kicker", s.kicker, 96 * k, 70, 1, RED, 0))
        if s.template == "statement":
            if s.speaker:
                b.append(("text:speaker", s.speaker, 66 * k, 46, 1, BLACK, 6))
            quote = s.quote or s.headline
            b.append(("text:quote", quote, 74 * k, 46, 4, RED, 14))
            if s.body and s.quote:
                b.append(("text:body", s.body, 50 * k, 38, 2, BLACK, 14))
        elif s.template == "stats":
            if s.number:
                b.append(("text:number", s.number, 200 * k, 130, 1, RED, 0))
            if s.number_caption:
                b.append(("text:number_caption", s.number_caption, 60 * k, 44, 2, BLACK, 0))
            b.append(("text:headline", s.headline, 64 * k, 44, 3, BLACK if s.number else RED, 18))
            if s.body:
                b.append(("text:body", s.body, 50 * k, 38, 2, GREY, 10))
        elif s.template == "transfer":
            b.append(("text:headline", s.headline, 78 * k, 50, 3, BLACK, 0))
            if s.body:
                b.append(("text:body", s.body, 58 * k, 40, 3, RED, 12))
        else:  # breaking / general
            b.append(("text:headline", s.headline, 80 * k, 52, 3, RED, 0))
            if s.body:
                b.append(("text:body", s.body, 54 * k, 36, 6, BLACK, 16))
        return b


def save_png(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path

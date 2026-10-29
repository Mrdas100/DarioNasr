"""محرك تصميم السنابات 1080×1920 بخط Arial Bold فقط مع تشكيل عربي كامل (Raqm + FriBiDi)"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

from .emoji import CLUSTER, EmojiStore, runs
from .models import TEMPLATE_AR, Snap

W, H = 1080, 1920
SIDE = 64                 # هامش جانبي آمن
SAFE_TOP = 150            # منطقة اسم الحساب في واجهة سناب
FOOTER_TOP = 1690         # بداية شريط الحقوق
FOOTER_TEXT_Y = 1748      # منتصف نص الحقوق (فوق منطقة الرد في سناب)
CONTENT_BOTTOM = FOOTER_TOP - 30
PHOTO_SIDE = 48           # الصورة أعرض قليلًا من النص
PHOTO_RADIUS = 32

RED = (213, 18, 38)
BLACK = (17, 17, 17)
WHITE = (255, 255, 255)
GREY = (120, 120, 120)
YELLOW = (255, 199, 0)


NAVY = (10, 36, 84)
INK = (11, 14, 22)

# أنماط التصميم: clean أبيض بسيط، cinema داكن بخلفية من الصورة نفسها، brand بألوان النصر
THEMES = {
    "clean": dict(bg=WHITE, text=BLACK, accent=RED, muted=GREY, side=48, radius=32, footer_text=BLACK),
    "cinema": dict(bg=INK, text=WHITE, accent=YELLOW, muted=(205, 208, 215), side=0, radius=0,
                   footer_text=WHITE),
    "brand": dict(bg=YELLOW, text=NAVY, accent=RED, muted=(55, 62, 80), side=56, radius=36,
                  footer_text=WHITE),
}


class RenderError(Exception):
    pass


@dataclass
class Layout:
    """تقرير التخطيط لفحص الجودة"""
    boxes: list[tuple[str, tuple[int, int, int, int]]] = field(default_factory=list)
    overflow: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    image_used: bool = False
    photo_radius: int = 32
    image_scale: float = 0.0
    fonts: set[str] = field(default_factory=set)

    def add(self, name, box):
        self.boxes.append((name, tuple(int(v) for v in box)))


class Renderer:
    def __init__(self, font_path: Path, logo_path: Path | None, handle: str, account_name: str,
                 emoji: EmojiStore | None = None, style: str = "clean"):
        self.emoji = emoji or EmojiStore(download=False)
        self.style = style if style in THEMES else "clean"
        self.th = THEMES[self.style]
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
        parts = self._runs(text)
        if parts is None:
            return self.font(size).getlength(text, direction="rtl", language="ar")
        es, gap = self._esize(size)
        return sum(es + 2 * gap if is_e else self.font(size).getlength(t, direction="rtl", language="ar")
                   for is_e, t in parts)

    # ---------- الإيموجي داخل النص ----------
    @staticmethod
    def _esize(size: int) -> tuple[int, int]:
        return int(size * 0.92), max(6, int(size * 0.2))

    def _runs(self, text: str):
        """None إن لم يكن في السطر إيموجي، وإلا أجزاء النص والإيموجي المتوفر بصورة أبل"""
        if not CLUSTER.search(text):
            return None
        out = []
        for is_e, t in runs(text):
            if is_e:
                if self.emoji.get(t) is not None:
                    out.append((True, t))
            elif t.strip():
                out.append((False, t.strip()))
        return out

    def _draw_line(self, d, x_right: float, y: int, line: str, size: int, color) -> None:
        """يرسم السطر من اليمين لليسار: كلمات بخط Arial وإيموجي بصور أبل"""
        f = self.font(size)
        es, gap = self._esize(size)
        x = x_right
        for is_e, t in self._runs(line):
            if is_e:
                im = self.emoji.get(t).resize((es, es), Image.LANCZOS)
                x -= gap + es
                self._target.paste(im, (int(x), int(y + size * 0.16)), im)
                x -= gap
            else:
                d.text((x, y), t, font=f, fill=color, anchor="ra", direction="rtl", language="ar")
                x -= f.getlength(t, direction="rtl", language="ar")

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
            if self._runs(line) is not None:
                xr = W / 2 + self.width(line, size) / 2 if align == "center" else x_right
                self._draw_line(d, xr, y, line, size, color)
            elif align == "center":
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
    def logo(self, img: Image.Image, lay: Layout) -> tuple[int, int, int, int]:
        box_w, box_h = 340, 220
        y0 = SAFE_TOP + 6
        if self.logo_path:
            logo = Image.open(self.logo_path).convert("RGBA")
            bbox = logo.getchannel("A").getbbox()
            if bbox:
                logo = logo.crop(bbox)
            logo.thumbnail((box_w, box_h), Image.LANCZOS)
            pos = ((W - logo.width) // 2, y0)
            img.paste(logo, pos, logo)
            box = (pos[0], y0, pos[0] + logo.width, y0 + logo.height)
        else:
            d = ImageDraw.Draw(img)
            d.text((W / 2, y0), self.account_name, font=self.font(96), fill=RED, anchor="ma",
                   direction="rtl", language="ar")
            box = (int(W / 2 - self.width(self.account_name, 96) / 2), y0,
                   int(W / 2 + self.width(self.account_name, 96) / 2), y0 + 130)
        lay.add("logo", box)
        return box

    _siren_cache: dict = {}

    def emoji_img(self, code: str, size: int) -> Image.Image | None:
        """إيموجي أبل من assets/emoji (يُنزّل وقت البناء)، وإلا None فنرسم الأيقونة بأنفسنا"""
        key = (code, size)
        if key not in self._siren_cache:
            p = Path(__file__).resolve().parent.parent / "assets" / "emoji" / f"{code}.png"
            im = None
            if p.exists():
                try:
                    im = Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS)
                except Exception:
                    im = None
            self._siren_cache[key] = im
        return self._siren_cache[key]

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
        """توقيع بسيط في الأسفل: داريو النصر | N9rfc1"""
        d = ImageDraw.Draw(img)
        y = FOOTER_TOP + 36
        hw = self.font(52).getlength(self.handle)
        aw = self.width(self.account_name, 46)
        gap = 34
        total = hw + gap * 2 + aw
        x0 = W / 2 - total / 2
        d.text((x0, y), self.handle, font=self.font(52), fill=YELLOW if self.style == "brand" else RED, anchor="lm")
        d.line((x0 + hw + gap, y - 20, x0 + hw + gap, y + 20), fill=self.th["muted"], width=3)
        d.text((x0 + total, y), self.account_name, font=self.font(46), fill=self.th["footer_text"], anchor="rm",
               direction="rtl", language="ar")
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

    def place_photo(self, img: Image.Image, photo: Image.Image, top: int, bottom: int, lay: Layout) -> int:
        """الصورة كاملة بلا قص ولا تشويه، بزوايا دائرية وظل ناعم"""
        box_w = W - 2 * self.th["side"]
        box_h = bottom - top
        scale = min(box_w / photo.width, box_h / photo.height)
        nw, nh = int(photo.width * scale), int(photo.height * scale)
        resized = photo.resize((nw, nh), Image.LANCZOS)
        x = (W - nw) // 2
        # الصورة بعرض التصميم كاملًا بلا زوايا، وإلا زوايا دائرية
        r = 0 if nw >= W - 2 else (self.th["radius"] or 28)
        lay.photo_radius = r
        if self.style == "brand":   # بطاقة بيضاء حول الصورة
            ImageDraw.Draw(img).rounded_rectangle((x - 14, top - 14, x + nw + 14, top + nh + 14), r + 12, fill=WHITE)
        shadow = Image.new("RGBA", (nw + 80, nh + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((40, 50, nw + 40, nh + 50), r, fill=(0, 0, 0, 60))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        img.paste(shadow, (x - 40, top - 40), shadow)
        mask = Image.new("L", (nw, nh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, nw - 1, nh - 1), r, fill=255)
        img.paste(resized, (x, top), mask)
        lay.add("photo", (x, top, x + nw, top + nh))
        lay.image_used = True
        lay.image_scale = scale
        return top + nh

    # ---------- التصميم ----------
    def render(self, snap: Snap) -> tuple[Image.Image, Layout]:
        """تصميم نظيف: شعار في المنتصف، الصورة كاملة بلا قص، شارة القالب، ثم العنوان والتفاصيل"""
        lay = Layout()
        img = Image.new("RGB", (W, H), self.th["bg"])
        self._canvas = img
        photo = self.load_photo(snap.image_path)
        self.background(img, photo)
        d = ImageDraw.Draw(img)
        logo_box = self.logo(img, lay)
        top = logo_box[3] + 44

        has_photo = photo is not None
        max_w = W - 2 * SIDE - 20
        pill_h = 92
        bottom = CONTENT_BOTTOM
        # أكبر نص ممكن بشرط أن تبقى الصورة بعرضها الكامل أو بارتفاع لا يقل عن 700
        tiers = ([(1.3, False), (1.18, False), (1.06, False), (0.95, False), (0.85, False), (0.8, True),
                  (0.7, True)] if has_photo else [(1.22, False)])
        if has_photo:
            box_w = W - 2 * self.th["side"]
            want = min(photo.height * min(box_w / photo.width, 2.2), 700)
        base_boxes, base_texts = list(lay.boxes), list(lay.texts)
        for k, drop_body in tiers:
            lay.boxes, lay.overflow, lay.texts = list(base_boxes), [], list(base_texts)
            text_img, text_h = self._text_layer(snap, k, drop_body, max_w, lay, compact=has_photo)
            if not has_photo or bottom - top - (pill_h + 40 + text_h + 48) >= want:
                break
        block_h = pill_h + 40 + text_h          # الشارة ثم النص

        if has_photo:
            space = bottom - top - block_h - 48
            if space < 420:
                raise RenderError("النص طويل ولا يترك مساحة كافية للصورة")
            box_w = W - 2 * self.th["side"]
            scale = min(box_w / photo.width, space / photo.height)
            ph = int(photo.height * scale)
            slack = max(0, space - ph)
            y = top + slack // 2                 # المجموعة كلها في منتصف المساحة
            y = self.place_photo(img, photo, y, y + ph, lay) + 48
        else:
            y = top + max(0, bottom - top - block_h) // 2
        y = self.pill(d, y, snap, lay) + 40
        self._paste_text(img, text_img, y, text_h, lay)

        self.footer(img, lay)
        return img, lay

    def background(self, img: Image.Image, photo: Image.Image | None) -> None:
        if self.style == "cinema":
            # خلفية من الصورة نفسها: مموهة وداكنة، ثم تدرج للأسود أسفل التصميم
            if photo is not None:
                bg = ImageOps.fit(photo, (W // 4, H // 4), Image.LANCZOS).filter(ImageFilter.GaussianBlur(10))
                bg = bg.resize((W, H), Image.BICUBIC)
                img.paste(Image.blend(bg, Image.new("RGB", (W, H), INK), 0.62))
            grad = Image.linear_gradient("L").resize((W, H))
            img.paste(Image.new("RGB", (W, H), INK), (0, 0), grad.point(lambda v: int(v * 0.85)))
        elif self.style == "brand":
            # أشرطة مائلة خفيفة بلون أغمق قليلًا
            d = ImageDraw.Draw(img)
            for x in range(-H, W, 120):
                d.polygon([(x, 0), (x + 46, 0), (x + 46 + H, H), (x + H, H)], fill=(250, 190, 0))
            d.rectangle((0, FOOTER_TOP - 6, W, H), fill=NAVY)

    def pill(self, d, y: int, snap: Snap, lay: Layout) -> int:
        """شارة القالب في المنتصف، وبجانبها شارات تحديث / غير رسمي"""
        t = snap.template
        label = TEMPLATE_AR.get(t, "")
        fill, color = {"breaking": (RED, WHITE), "stats": (YELLOW, BLACK),
                       "statement": (BLACK, WHITE), "transfer": (BLACK, WHITE)}.get(t, (RED, WHITE))
        if self.style == "cinema" and fill == BLACK:
            fill, color = WHITE, BLACK
        if self.style == "brand" and fill in (BLACK, YELLOW):
            fill, color = NAVY, WHITE
        size, h = 54, 92
        icon = self.emoji_img("1f6a8", 64) if t == "breaking" else None
        if t == "breaking" and icon is None:
            icon = self.siren_img(64)
        tw = self.width(label, size) + (64 + 22 if icon else 0)
        extra = [("تحديث", RED, WHITE)] if snap.is_update else []
        if snap.is_rumor:
            extra.append(("غير رسمي", WHITE, BLACK))
        ew = [self.width(e[0], 40) + 52 for e in extra]
        total = tw + 96 + sum(w + 18 for w in ew)
        x = W / 2 + total / 2                   # من اليمين: الشارة الرئيسية ثم الإضافية
        box = (int(x - tw - 96), y, int(x), y + h)
        d.rounded_rectangle(box, 26, fill=fill)
        cx = x - 48
        if icon:
            self._canvas.paste(icon, (int(cx - 64), y + (h - 64) // 2), icon)
            cx -= 64 + 22
        d.text((cx, y + h / 2 + 2), label, font=self.font(size), fill=color, anchor="rm",
               direction="rtl", language="ar")
        lay.add("chip:" + label, box)
        lay.texts.append(label)
        x = box[0] - 18
        for (text, bg, fg), w in zip(extra, ew):
            b = (int(x - w), y + 14, int(x), y + h - 14)
            if bg == WHITE:
                d.rounded_rectangle(b, 22, fill=WHITE, outline=BLACK, width=3)
            else:
                d.rounded_rectangle(b, 22, fill=bg)
            d.text(((b[0] + b[2]) / 2, y + h / 2 + 2), text, font=self.font(40), fill=fg, anchor="mm",
                   direction="rtl", language="ar")
            lay.add("chip:" + text, b)
            lay.texts.append(text)
            x = b[0] - 18
        return y + h

    def _text_layer(self, snap: Snap, k: float, drop_body: bool, max_w: int, lay: Layout, compact=False):
        text_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self._target = text_img
        td = ImageDraw.Draw(text_img)
        ty = 0
        for name, text, start, minimum, max_lines, color, gap in self._blocks(snap, k):
            if compact:
                # مع صورة أو فيديو: الوسائط هي الأساس والنص مختصر في أعلى التصميم
                start, minimum = start * 0.82, minimum * 0.85
                max_lines = min(max_lines, 2 if name in ("text:headline", "text:quote") else 4)
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
        A, T, M = self.th["accent"], self.th["text"], self.th["muted"]
        if self.style == "cinema":
            A = WHITE if s.template == "breaking" else YELLOW
        if s.kicker:
            b.append(("text:kicker", s.kicker, 96 * k, 70, 1, A, 0))
        if s.template == "statement":
            if s.speaker:
                b.append(("text:speaker", s.speaker, 66 * k, 46, 1, T, 6))
            quote = s.quote or s.headline
            b.append(("text:quote", quote, 74 * k, 46, 4, A, 14))
            if s.body and s.quote:
                b.append(("text:body", s.body, 50 * k, 38, 2, T, 14))
        elif s.template == "stats":
            if s.number:
                b.append(("text:number", s.number, 200 * k, 130, 1, A, 0))
            if s.number_caption:
                b.append(("text:number_caption", s.number_caption, 60 * k, 44, 2, T, 0))
            b.append(("text:headline", s.headline, 64 * k, 44, 3, T if s.number else A, 18))
            if s.body:
                b.append(("text:body", s.body, 50 * k, 38, 2, M, 10))
        elif s.template == "transfer":
            b.append(("text:headline", s.headline, 78 * k, 50, 3, T, 0))
            if s.body:
                b.append(("text:body", s.body, 58 * k, 40, 3, A, 12))
        else:  # breaking / general
            b.append(("text:headline", s.headline, 80 * k, 52, 3, A if s.template == "breaking" else T, 0))
            if s.body:
                b.append(("text:body", s.body, 54 * k, 36, 6, T, 16))
        return b


def save_png(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path

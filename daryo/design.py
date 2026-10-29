"""قوالب داريو النصر بأسلوب البطاقة والبوستر (مستوحاة من نماذج صاحب الحساب) بألوان النصر

- card: خلفية فاتحة بأشرطة مائلة، بطاقة فيها الصورة كاملة وشارة الشعار، تبويب عاجل، ولوحة نص بيضاء
- poster: الصورة بعرض التصميم كاملًا وتتدرج إلى الكحلي، والعنوان أبيض بمحاذاة اليمين مع خط جانبي
- text: بدون صورة، خلفية كحلية متدرجة ونص أبيض كبير

كل ما فوق الصورة يُرسم في طبقة شفافة منفصلة (lay.overlay) حتى يبقى فوق الفيديو أيضًا
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .models import TEMPLATE_AR, Snap
from .render import FOOTER_TOP, H, SAFE_TOP, W, Layout, RenderError, Renderer

BLUE = (24, 58, 150)          # أزرق النصر
NAVY = (9, 22, 58)
INK = (14, 24, 52)            # نص داكن على الأبيض
YELLOW = (255, 204, 0)
RED = (226, 32, 44)
SLATE = (42, 52, 72)
WHITE = (255, 255, 255)
MUTED = (88, 98, 120)
LIGHT = (238, 240, 246)

CARD_X0, CARD_X1 = 84, W - 84
CARD_W = CARD_X1 - CARD_X0
CARD_R = 30
TEXT_BOTTOM = FOOTER_TOP - 20


class Designer(Renderer):
    def __init__(self, font_path: Path, logo_path, handle, account_name, emoji=None,
                 semibold_path: Path | None = None):
        super().__init__(font_path, logo_path, handle, account_name, emoji=emoji)
        self.bold_path = str(font_path)
        sb = Path(semibold_path) if semibold_path else Path(font_path).with_name(
            Path(font_path).name.replace("-Bold", "-SemiBold"))
        self.semibold_path = str(sb) if sb.exists() else self.bold_path

    # ---------- أدوات ----------
    def _logo_img(self, max_w: int, max_h: int) -> Image.Image | None:
        if not self.logo_path:
            return None
        logo = Image.open(self.logo_path).convert("RGBA")
        bbox = logo.getchannel("A").getbbox()
        if bbox:
            logo = logo.crop(bbox)
        logo.thumbnail((max_w, max_h), Image.LANCZOS)
        return logo

    def _logo_badge(self, over: Image.Image, x1: int, y0: int, lay: Layout, size=(150, 160), round_all=False):
        """شارة كحلية فيها الشعار في الزاوية العليا اليمنى"""
        w, h = size
        d = ImageDraw.Draw(over)
        box = (x1 - w, y0, x1, y0 + h)
        if round_all:
            d.rounded_rectangle(box, 26, fill=NAVY + (235,))
        else:
            d.rounded_rectangle(box, 26, fill=NAVY + (255,), corners=(False, True, False, True))
        d.rectangle((box[0], box[3] - 8, box[2], box[3]), fill=YELLOW + (255,)) if not round_all else None
        logo = self._logo_img(w - 26, h - 34)
        if logo is not None:
            over.paste(logo, (box[0] + (w - logo.width) // 2, y0 + (h - 8 - logo.height) // 2), logo)
        lay.add("logo", box)

    def _text(self, over: Image.Image, blocks, x_right: int, top: int, max_w: int, align: str, lay: Layout,
              dry: bool = False) -> int:
        """يرسم كتل النص ويعيد الارتفاع. dry=True يقيس فقط"""
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self._target = layer
        first = len(lay.boxes)
        d = ImageDraw.Draw(layer)
        y = 0
        for name, text, start, minimum, max_lines, color, gap, weight in blocks:
            self.font_path = self.semibold_path if weight == "semi" else self.bold_path
            size, lines = self.fit(text, max_w, int(start), int(minimum), max_lines)
            if size is None:
                lay.overflow.append(name)
                size, lines = int(minimum), lines[:max_lines]
            y += gap
            y = self.draw_lines(d, lines, size, y, color, lay, name, align=align, x_right=x_right)
        self.font_path = self.bold_path
        if not dry:
            over.alpha_composite(layer.crop((0, 0, W, y + 20)), (0, top))
            lay.boxes = lay.boxes[:first] + [(n, (b[0], b[1] + top, b[2], b[3] + top))
                                             for n, b in lay.boxes[first:]]
        return y

    def _blocks(self, s: Snap, k: float, main, accent, muted):
        """(اسم، نص، حجم، أدنى، أسطر، لون، فراغ، وزن)"""
        b = []
        if s.kicker:
            b.append(("text:kicker", s.kicker, 60 * k, 44, 1, accent, 0, "bold"))
        if s.template == "statement":
            if s.speaker:
                b.append(("text:speaker", s.speaker, 52 * k, 38, 1, accent, 0, "bold"))
            b.append(("text:quote", s.quote or s.headline, 66 * k, 44, 4, main, 10, "bold"))
            if s.body and s.quote:
                b.append(("text:body", s.body, 44 * k, 34, 3, muted, 14, "semi"))
        elif s.template == "stats":
            if s.number:
                b.append(("text:number", s.number, 170 * k, 110, 1, accent, 0, "bold"))
            b.append(("text:headline", s.headline, 62 * k, 42, 3, main, 6, "bold"))
            if s.body:
                b.append(("text:body", s.body, 44 * k, 34, 3, muted, 12, "semi"))
        else:
            b.append(("text:headline", s.headline, 70 * k, 46, 3, main, 0, "bold"))
            if s.body:
                b.append(("text:body", s.body, 46 * k, 34, 5, muted, 16, "semi"))
        return b

    def _fit_blocks(self, snap, max_h, max_w, colors, lay, tiers=(1.2, 1.1, 1.0, 0.9, 0.8, 0.72)):
        base = (list(lay.boxes), list(lay.texts))
        for k in tiers:
            lay.boxes, lay.texts, lay.overflow = list(base[0]), list(base[1]), []
            blocks = self._blocks(snap, k, *colors)
            h = self._text(None, blocks, 0, 0, max_w, "center", lay, dry=True)
            if h <= max_h and not lay.overflow:
                break
        lay.boxes, lay.texts, lay.overflow = list(base[0]), list(base[1]), []
        return blocks, h

    def _footer(self, over: Image.Image, lay: Layout, dark: bool):
        d = ImageDraw.Draw(over)
        y = FOOTER_TOP + 40
        self.font_path = self.bold_path
        hw = self.font(44).getlength(self.handle)
        aw = self.width(self.account_name, 40)
        gap = 28
        total = hw + gap * 2 + aw
        x0 = W / 2 - total / 2
        d.rounded_rectangle((x0 - 34, y - 38, x0 + total + 34, y + 38), 38,
                            fill=(26, 44, 92, 255) if dark else WHITE + (255,))
        d.text((x0, y), self.handle, font=self.font(44), fill=YELLOW if dark else BLUE, anchor="lm")
        d.line((x0 + hw + gap, y - 16, x0 + hw + gap, y + 16), fill=(180, 186, 200), width=3)
        d.text((x0 + total, y), self.account_name, font=self.font(40), fill=WHITE if dark else INK, anchor="rm",
               direction="rtl", language="ar")
        lay.add("footer", (0, FOOTER_TOP, W, H))
        lay.texts += [self.handle, self.account_name]

    def _label(self, snap: Snap) -> str:
        return TEMPLATE_AR.get(snap.template, "خبر")

    def _extras(self, snap: Snap) -> list[str]:
        out = []
        if snap.is_update:
            out.append("تحديث")
        if snap.is_rumor:
            out.append("غير رسمي")
        return out

    # ---------- القالب الرئيسي ----------
    def render(self, snap: Snap):
        photo = self.load_photo(snap.image_path)
        lay = Layout()
        lay.fonts.add(self.bold_path)
        if photo is None:
            img, over = self._render_text(snap, lay)
        elif photo.height / photo.width >= 1.12:
            img, over = self._render_poster(snap, photo, lay)
        else:
            img, over = self._render_card(snap, photo, lay)
        self._footer(over, lay, dark=photo is None or photo.height / photo.width >= 1.12)
        lay.overlay, lay.base = over, img
        final = img.convert("RGBA")
        final.alpha_composite(over)
        return final.convert("RGB"), lay

    # بطاقة: صورة عريضة أو مربعة
    def _render_card(self, snap, photo, lay):
        img = Image.new("RGB", (W, H), LIGHT)
        self._card_background(img)
        over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tab_h = 84
        max_w = CARD_W - 110
        colors = (INK, BLUE, MUTED)
        room = TEXT_BOTTOM - (SAFE_TOP + 70)
        natural = int(photo.height * CARD_W / photo.width)
        # النص أولًا بحد أقصى يترك للصورة 620 على الأقل
        blocks, th = self._fit_blocks(snap, max(220, room - min(natural, 620) - 150), max_w, colors, lay)
        panel_h = max(300, th + 150)
        ph = min(natural, room - panel_h)
        if ph < 420:
            raise RenderError("النص طويل ولا يترك مساحة كافية للصورة")
        total = ph + panel_h
        top = SAFE_TOP + 70 + max(0, (TEXT_BOTTOM - SAFE_TOP - 70 - total) // 2)
        if top + total > TEXT_BOTTOM + 4:
            raise RenderError("النص طويل ولا يترك مساحة كافية للصورة")
        # الصورة كاملة: بعرض البطاقة، وإن كانت أطول من المساحة تُصغّر وتملأ الجوانب نسخة مموهة منها
        scale = min(CARD_W / photo.width, ph / photo.height)
        pw, phh = int(photo.width * scale), int(photo.height * scale)
        resized = ImageOps.fit(photo, (CARD_W // 6, max(1, ph // 6))).filter(ImageFilter.GaussianBlur(5))
        resized = Image.blend(resized.resize((CARD_W, ph)), Image.new("RGB", (CARD_W, ph), NAVY), 0.45)
        resized.paste(photo.resize((pw, phh), Image.LANCZOS), ((CARD_W - pw) // 2, (ph - phh) // 2))
        shadow = Image.new("RGBA", (CARD_W + 80, total + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((40, 52, CARD_W + 40, total + 40), CARD_R, fill=(10, 20, 50, 70))
        shadow = shadow.filter(ImageFilter.GaussianBlur(20))
        img.paste(shadow, (CARD_X0 - 40, top - 40), shadow)
        mask = Image.new("L", (CARD_W, ph), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, ph + CARD_R), CARD_R, fill=255)
        img.paste(resized, (CARD_X0, top), mask)
        px0, py0 = CARD_X0 + (CARD_W - pw) // 2, top + (ph - phh) // 2
        lay.add("photo", (px0, py0, px0 + pw, py0 + phh))
        lay.image_used, lay.image_scale, lay.photo_radius = True, scale, CARD_R if pw >= CARD_W - 2 else 0
        d = ImageDraw.Draw(over)
        # إطار رفيع للبطاقة
        d.rounded_rectangle((CARD_X0 - 3, top - 3, CARD_X1 + 3, top + total + 3), CARD_R + 3, outline=BLUE + (255,),
                            width=4)
        # لوحة النص البيضاء
        pt = top + ph
        d.rounded_rectangle((CARD_X0, pt, CARD_X1, top + total), CARD_R, fill=WHITE + (255,),
                            corners=(False, False, True, True))
        self._logo_badge(over, CARD_X1, top, lay)
        # تبويبات أسفل الصورة: التصنيف ثم الإضافات (تحديث / غير رسمي)
        self._tabs(over, snap, CARD_X1 - 14, pt - tab_h + 2, tab_h, lay)
        self._text(over, blocks, W // 2, pt + (panel_h - th) // 2 - 6, max_w, "center", lay)
        return img, over

    def _tabs(self, over, snap, x1, y, h, lay):
        d = ImageDraw.Draw(over)
        label = self._label(snap)
        self.font_path = self.bold_path
        size = 56
        tw = self.width(label, size)
        sq = 22
        w = int(tw + sq + 110)
        slant = 34
        # حدّ أبيض حول التبويب كما في النموذج
        d.polygon([(x1 + 8, y - 8), (x1 + 8, y + h), (x1 - w - slant - 10, y + h), (x1 - w - 6, y - 8)],
                  fill=WHITE + (255,))
        d.rounded_rectangle((x1 - w, y, x1, y + h), 16, fill=(RED if snap.template == "breaking" else BLUE) + (255,),
                            corners=(True, True, False, False))
        d.polygon([(x1 - w + 10, y), (x1 - w + 10, y + h), (x1 - w - slant, y + h)],
                  fill=(RED if snap.template == "breaking" else BLUE) + (255,))
        cx = x1 - 40
        d.rectangle((cx - sq, y + h / 2 - sq / 2 + 2, cx, y + h / 2 + sq / 2 + 2),
                    fill=(WHITE if snap.template == "breaking" else RED) + (255,))
        d.text((cx - sq - 18, y + h / 2 + 4), label, font=self.font(size), fill=WHITE, anchor="rm",
               direction="rtl", language="ar")
        lay.add("chip:" + label, (int(x1 - w - slant), y, x1, y + h))
        lay.texts.append(label)
        x = x1 - w - slant - 10
        for text in self._extras(snap):
            ew = int(self.width(text, 40) + 70)
            d.polygon([(x, y + 14), (x, y + h), (x - ew - 26, y + h), (x - ew, y + 14)], fill=SLATE + (255,))
            d.text((x - ew / 2 - 10, y + h / 2 + 10), text, font=self.font(40), fill=WHITE, anchor="mm",
                   direction="rtl", language="ar")
            lay.add("chip:" + text, (int(x - ew - 26), y + 14, int(x), y + h))
            lay.texts.append(text)
            x -= ew + 30

    def _card_background(self, img):
        d = ImageDraw.Draw(img)
        g = Image.linear_gradient("L").resize((W, H)).point(lambda v: 255 - v // 6)
        img.paste(Image.new("RGB", (W, H), (226, 230, 240)), (0, 0), g.point(lambda v: 255 - v))
        # أشرطة مائلة على الأطراف بألوان النصر
        for x0, ys in ((-30, (380, 1020, 1500)), (W - 22, (160, 640, 1260))):
            for i, yy in enumerate(ys):
                col = BLUE if i % 2 == 0 else YELLOW
                d.polygon([(x0, yy), (x0 + 52, yy - 90), (x0 + 52, yy + 230), (x0, yy + 320)], fill=col)

    # بوستر: صورة طولية أو فيديو
    def _render_poster(self, snap, photo, lay):
        img = Image.new("RGB", (W, H), NAVY)
        scale = W / photo.width
        ph = int(photo.height * scale)
        if ph > H:      # أطول من التصميم: كاملة بالارتفاع مع خلفية مموهة
            scale = H / photo.height
            ph = H
        pw = int(photo.width * scale)
        bg = ImageOps.fit(photo, (W // 6, H // 6)).filter(ImageFilter.GaussianBlur(6)).resize((W, H))
        img.paste(Image.blend(bg, Image.new("RGB", (W, H), NAVY), 0.55))
        img.paste(photo.resize((pw, ph), Image.LANCZOS), ((W - pw) // 2, 0))
        lay.add("photo", ((W - pw) // 2, 0, (W - pw) // 2 + pw, ph))
        lay.image_used, lay.image_scale, lay.photo_radius = True, scale, 0
        lay.text_on_photo = True
        over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        max_w = W - 200
        colors = (WHITE, YELLOW, (218, 224, 240))
        blocks, th = self._fit_blocks(snap, 520, max_w, colors, lay)
        label_h = 130
        text_top = TEXT_BOTTOM - th - 10
        label_top = text_top - label_h - 10
        # تدرج كحلي يبدأ فوق العنوان بمسافة ويغطي الأسفل
        g0 = max(0, label_top - 420)
        grad = Image.new("RGBA", (W, H - g0), NAVY + (0,))
        alpha = Image.linear_gradient("L").resize((W, H - g0)).point(lambda v: min(255, int(v * 1.8)))
        grad.putalpha(alpha)
        over.alpha_composite(grad, (0, g0))
        d = ImageDraw.Draw(over)
        # التصنيف بخط كبير مع شريط تحته
        label = {"general": "خبر"}.get(snap.template, self._label(snap)) + ":"
        self.font_path = self.bold_path
        lw = self.width(label, 92)
        xr = W - 92
        d.rectangle((xr - lw - 24, label_top + 74, xr + 14, label_top + 122),
                    fill=(RED if snap.template == "breaking" else BLUE) + (255,))
        d.text((xr, label_top + 6), label, font=self.font(92), fill=WHITE, anchor="ra", direction="rtl", language="ar")
        lay.add("chip:" + label, (int(xr - lw - 24), label_top, xr + 14, label_top + 122))
        lay.texts.append(label)
        x = xr - lw - 50
        for text in self._extras(snap):
            ew = int(self.width(text, 38) + 56)
            d.rounded_rectangle((x - ew, label_top + 62, x, label_top + 122), 30, fill=YELLOW + (255,))
            d.text((x - ew / 2, label_top + 94), text, font=self.font(38), fill=NAVY, anchor="mm",
                   direction="rtl", language="ar")
            lay.add("chip:" + text, (x - ew, label_top + 62, x, label_top + 122))
            lay.texts.append(text)
            x -= ew + 16
        # خط جانبي أصفر بجانب النص
        d.rounded_rectangle((W - 78, text_top + 12, W - 66, text_top + th), 6, fill=YELLOW + (255,))
        self._text(over, blocks, W - 100, text_top, max_w, "right", lay)
        self._logo_badge(over, W - 60, SAFE_TOP + 10, lay, size=(170, 180), round_all=True)
        return img, over

    # بدون صورة
    def _render_text(self, snap, lay):
        img = Image.new("RGB", (W, H), BLUE)
        grad = Image.linear_gradient("L").resize((W, H))
        img.paste(Image.new("RGB", (W, H), NAVY), (0, 0), grad)
        d = ImageDraw.Draw(img)
        # مربعات بيضاء على الحواف كما في النموذج
        d.rectangle((W - 90, 0, W, 170), fill=WHITE)
        d.rectangle((0, 1180, 120, 1600), fill=WHITE)
        d.rectangle((W - 90, 1640, W, H), fill=YELLOW)
        over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        logo = self._logo_img(300, 210)
        if logo is not None:
            over.paste(logo, ((W - logo.width) // 2, SAFE_TOP + 20), logo)
            lay.add("logo", ((W - logo.width) // 2, SAFE_TOP + 20, (W + logo.width) // 2, SAFE_TOP + 20 + logo.height))
        max_w = W - 240
        colors = (WHITE, YELLOW, (214, 222, 244))
        blocks, th = self._fit_blocks(snap, 900, max_w, colors, lay, tiers=(1.5, 1.35, 1.2, 1.1, 1.0, 0.9))
        dd = ImageDraw.Draw(over)
        label = self._label(snap)
        lw = self.width(label, 54)
        top = 420 + max(0, (TEXT_BOTTOM - 420 - th - 130) // 2)
        box = (int(W / 2 - lw / 2 - 44), top, int(W / 2 + lw / 2 + 44), top + 86)
        dd.rounded_rectangle(box, 43, fill=(RED if snap.template == "breaking" else YELLOW) + (255,))
        dd.text((W / 2, top + 46), label, font=self.font(54), anchor="mm", direction="rtl", language="ar",
                fill=WHITE if snap.template == "breaking" else NAVY)
        lay.add("chip:" + label, box)
        lay.texts.append(label)
        x = box[0] - 16
        for text in self._extras(snap):
            ew = int(self.width(text, 38) + 50)
            dd.rounded_rectangle((x - ew, top + 14, x, top + 72), 29, outline=WHITE + (255,), width=3)
            dd.text((x - ew / 2, top + 45), text, font=self.font(38), fill=WHITE, anchor="mm",
                    direction="rtl", language="ar")
            lay.add("chip:" + text, (x - ew, top + 14, x, top + 72))
            x -= ew + 14
        self._text(over, blocks, W // 2, top + 130, max_w, "center", lay)
        return img, over

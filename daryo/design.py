"""Daryo Alnasr v5 templates: navy stadium look, brand top bar, per-type layouts.

Real source media stays whole (never cropped). Text, branding and video
overlays share one measured geometry; overflow raises instead of cutting.
The same Designer renders the 9:16 snap and an optional 4:5 post.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .models import TEMPLATE_AR, Snap
from .render import FOOTER_TOP, H, SAFE_TOP, W, Layout, RenderError, Renderer

BG = (8, 22, 52)
GLOW = (23, 52, 121)
PANEL = (20, 40, 86)
NAVY = BG
BLUE = (29, 63, 154)
YELLOW = (255, 204, 0)
RED = (224, 24, 45)
GREEN = (18, 150, 84)
WHITE = (255, 255, 255)
MUTED = (214, 222, 240)
SOFT = (165, 180, 216)
INK = BG
GOLD = (190, 151, 68)
LIGHT = PANEL
LEFT, RIGHT = 72, W - 72
WIDTH = RIGHT - LEFT
TEXT_BOTTOM = FOOTER_TOP - 42
MAX_UPSCALE = 2.1
BAR_GAP = 30          # yellow side bar + gap beside right-aligned headlines
POST_H = 1350         # 4:5 post for X / Instagram


def create_renderer(cfg, emoji=None):
    """The service and CLI must preview exactly the same selected renderer."""
    if cfg.design_style in ("clean", "cinema", "brand"):
        return LegacyDesigner(cfg, emoji)
    return Designer(cfg.font_path, cfg.logo_path, cfg.snap_handle, cfg.account_name, emoji=emoji)


def _sibling(font_path, weight):
    p = Path(font_path)
    q = p.with_name(p.name.replace("-Bold", f"-{weight}"))
    return str(q) if q.exists() and q != p else str(p)


class Designer(Renderer):
    def __init__(self, font_path: Path, logo_path, handle, account_name, emoji=None,
                 semibold_path: Path | None = None):
        super().__init__(font_path, logo_path, handle, account_name, emoji=emoji)
        self.bold_path = str(font_path)
        self.semibold_path = str(semibold_path) if semibold_path and Path(semibold_path).exists() \
            else _sibling(font_path, "SemiBold")
        self.black_path = _sibling(font_path, "Black")
        self.h, self.safe, self.foot = H, SAFE_TOP, FOOTER_TOP
        self._bg_cache: dict[int, Image.Image] = {}
        self._logo_cache: dict = {}

    @property
    def text_bottom(self):
        return self.foot - 42

    @property
    def header_bottom(self):
        return self.safe + 128

    @staticmethod
    def line_h(size):
        return int(size * (1.42 if size < 120 else 1.08))

    @staticmethod
    def _is_video(snap):
        from .video import video_of
        return video_of(snap.image_path) is not None

    @staticmethod
    def _result_as_news(snap: Snap) -> Snap:
        """A score that cannot fit the scoreboard still goes out as ordinary news."""
        score = f"{snap.home} {snap.home_score}-{snap.away_score} {snap.away}"
        extra = [snap.competition, snap.headline, snap.body] + [f"{a}: {b}" for a, b in snap.rows]
        return replace(snap, template="general", headline=score, body="\n".join(x for x in extra if x),
                       rows=[], home="", away="", home_score="", away_score="", competition="")

    def paginate(self, snap: Snap) -> list[Snap]:
        """Preserve every word / row on numbered pages rather than shrink to dust."""
        if snap.template == "result":
            try:
                self.render(snap)
                return [replace(snap, page=1, pages=1)]
            except RenderError:
                snap = self._result_as_news(snap)
        pages = []
        if snap.rows:
            from math import ceil
            capacity = 2 if snap.image_path else 6
            count = ceil(len(snap.rows) / capacity)
            size = ceil(len(snap.rows) / count)
            for i in range(0, len(snap.rows), size):
                pages.append(replace(snap, rows=snap.rows[i:i + size]))
        else:
            field = "quote" if snap.template == "statement" and snap.quote else "body"
            value = getattr(snap, field)
            limit = (32 if snap.image_path else 50) if field == "quote" else (32 if snap.image_path else 54)
            words = value.split()
            if len(words) > limit:
                for i in range(0, len(words), limit):
                    chunk = " ".join(words[i:i + limit])
                    updates = {field: chunk}
                    if field == "quote" and snap.headline == snap.quote:
                        updates["headline"] = chunk
                    pages.append(replace(snap, **updates))
        if not pages:
            pages = [replace(snap)]
        # Word counts are a useful starting point, but Arabic names and mixed
        # alphanumerics vary in width. Validate actual geometry, then bisect
        # overflowing body / quote chunks without losing any source words.
        fitted = []
        pending = list(pages)
        while pending:
            page = pending.pop(0)
            try:
                self.render(page)
                fitted.append(page)
            except RenderError:
                field = "quote" if page.template == "statement" and page.quote else "body"
                words = getattr(page, field).split()
                if page.rows or len(words) < 2:
                    raise
                mid = len(words) // 2
                halves = []
                for part in (words[:mid], words[mid:]):
                    value = " ".join(part)
                    changes = {field: value}
                    if field == "quote" and page.headline == page.quote:
                        changes["headline"] = value
                    halves.append(replace(page, **changes))
                pending[0:0] = halves
        return [replace(p, page=i + 1, pages=len(fitted)) for i, p in enumerate(fitted)]

    # ---------- brand pieces ----------
    def _logo_img(self, max_w, max_h):
        if not self.logo_path:
            return None
        key = (max_w, max_h)
        if key not in self._logo_cache:
            with Image.open(self.logo_path) as source:
                logo = source.convert("RGBA")
            box = logo.getchannel("A").getbbox()
            if box:
                logo = logo.crop(box)
            logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            self._logo_cache[key] = logo
        return self._logo_cache[key]

    def _background(self):
        """Navy with a soft blue stadium glow top-right and faint yellow diagonals."""
        h = self.h
        if h not in self._bg_cache:
            img = Image.new("RGB", (W, h), BG)
            glow = ImageOps.invert(Image.radial_gradient("L")).resize((int(W * 2.0), int(h * 1.1)))
            glow = glow.point(lambda v: int(min(255, max(0, v - 128) * 1.6)))
            img.paste(Image.new("RGB", glow.size, GLOW), (int(W * 0.8 - glow.width / 2), int(-glow.height / 2)), glow)
            stripes = Image.new("RGBA", (W, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(stripes)
            run = int(h * 0.7)
            for x in range(-run, W + run, 60):
                d.polygon([(x, 0), (x + 18, 0), (x + 18 - run, h), (x - run, h)], fill=(255, 204, 0, 9))
            img = img.convert("RGBA")
            img.alpha_composite(stripes)
            self._bg_cache[h] = img.convert("RGB")
        return self._bg_cache[h].copy()

    def _tag(self, snap):
        t = snap.template
        if t == "comment":
            return "", None, None
        if t == "transfer" and snap.transfer_status == "official":
            return "رسمي", GREEN, WHITE
        label = TEMPLATE_AR.get(t, "أخبار النصر")
        if t == "availability" and any(x in snap.headline for x in ("إصابات", "اصابات")):
            label = "الإصابات"
        bg = {"breaking": RED, "tickets": YELLOW, "result": YELLOW, "dhikr": GOLD}.get(t, BLUE)
        return label, bg, (BG if bg == YELLOW else WHITE)

    def _header(self, ink, snap, lay):
        d = ImageDraw.Draw(ink)
        top = self.safe + 6
        logo = self._logo_img(108, 108)
        name_right = RIGHT
        if logo is not None:
            ink.alpha_composite(logo, (RIGHT - logo.width, top + (112 - logo.height) // 2))
            lay.add("logo", (RIGHT - logo.width, top, RIGHT, top + 112))
            name_right = RIGHT - logo.width - 18
        self.font_path = self.black_path
        lay.fonts.add(self.black_path)
        d.text((name_right, top + 50), self.account_name, font=self.font(40), anchor="rs",
               direction="rtl", language="ar", fill=WHITE)
        self.font_path = self.bold_path
        d.text((name_right, top + 66), "DIARIO AL NASSR", font=self.font(21), anchor="rt",
               direction="ltr", fill=YELLOW)
        nw = max(self.width(self.account_name, 40), self.font(21).getlength("DIARIO AL NASSR"))
        lay.add("text:brand", (name_right - nw, top + 6, name_right, top + 96))
        label, bg, fg = self._tag(snap)
        if label:
            self.font_path = self.black_path
            tw = self.width(label, 38)
            w, sk = int(tw + 78), 14
            y0, y1 = top + 22, top + 92
            d.polygon([(LEFT + sk, y0), (LEFT + w, y0), (LEFT + w - sk, y1), (LEFT, y1)], fill=bg)
            d.text((LEFT + w / 2, (y0 + y1) / 2 - 3), label, font=self.font(38), anchor="mm",
                   direction="rtl", language="ar", fill=fg)
            self.font_path = self.bold_path
            lay.add("chip:" + label, (LEFT, y0, LEFT + w, y1))
            lay.texts.append(label)

    def _footer(self, ink, snap, lay):
        d = ImageDraw.Draw(ink)
        y = self.foot + 48
        self.font_path = self.bold_path
        aw = self.width(self.account_name, 32)
        hw = self.font(34).getlength(self.handle)
        pad, gap = 34, 16
        total = aw + hw + 2 * gap + 2 * pad
        x0 = W / 2 - total / 2
        box = (x0, y - 34, x0 + total, y + 34)
        d.rounded_rectangle(box, 34, fill=(255, 255, 255, 26), outline=(255, 255, 255, 50), width=2)
        d.text((box[2] - pad, y), self.account_name, font=self.font(32), anchor="rm",
               direction="rtl", language="ar", fill=WHITE)
        sep = box[2] - pad - aw - gap
        d.line((sep, y - 20, sep, y + 20), fill=(255, 255, 255, 90), width=2)
        d.text((sep - gap, y), self.handle, font=self.font(34), anchor="rm", direction="ltr", fill=YELLOW)
        if snap.pages > 1:
            d.text((LEFT, y), f"{snap.page} / {snap.pages}", font=self.font(30), anchor="lm",
                   direction="ltr", fill=SOFT)
        lay.add("footer", (0, self.foot, W, self.h))
        lay.texts.extend((self.handle, self.account_name))

    @staticmethod
    def _slashes(deco, y, side="left"):
        """Yellow diagonal accents in the Al Nassr sports-account style."""
        d = ImageDraw.Draw(deco)
        def bar(x0, x1, alpha):
            d.polygon([(x0 + 8, y), (x1 + 8, y), (x1, y + 22), (x0, y + 22)], fill=YELLOW + (alpha,))
        if side == "left":
            bar(-40, 230, 255)
            bar(250, 370, 110)
        else:
            bar(W - 230, W + 40, 255)
            bar(W - 370, W - 250, 110)

    # ---------- text ----------
    def _blocks(self, snap, dark=True):
        out = []
        def add(name, value, size, minimum, lines, color, gap=0, weight="bold"):
            if value:
                out.append(("text:" + name, value, size, minimum, lines, color, gap, weight))
        if snap.kicker and snap.kicker != TEMPLATE_AR.get(snap.template) and \
                not (snap.template == "transfer" and snap.transfer_status == "official" and "رسمي" in snap.kicker):
            add("kicker", snap.kicker, 34, 30, 2, YELLOW)
        if snap.template == "statement":
            add("speaker", snap.speaker, 44, 36, 2, YELLOW, 0, "black")
            add("quote", snap.quote or snap.headline, 66, 46, 12, WHITE, 16)
            add("body", snap.body, 40, 34, 5, SOFT, 28, "semi")
        elif snap.template == "stats":
            add("number", snap.number, 300, 150, 1, YELLOW, 0, "black")
            add("number_caption", snap.number_caption, 50, 38, 2, WHITE, 10)
            add("headline", snap.headline, 46, 38, 4, MUTED, 34, "semi")
            add("body", snap.body, 40, 34, 6, SOFT, 18, "semi")
        elif snap.template == "result":
            add("headline", snap.headline, 50, 38, 3, WHITE)
            add("body", snap.body, 40, 34, 5, SOFT, 18, "semi")
        elif snap.template == "dhikr":
            add("headline", snap.headline, 64, 40, 14, WHITE)
        else:
            add("headline", snap.headline, 72 if not snap.rows else 62, 48, 5, WHITE)
            add("body", snap.body, 42, 34, 9, MUTED, 24, "semi")
        return out

    def _measure(self, blocks, width, max_h):
        """Measure without polluting QA boxes. No cutting lines on failure."""
        original = self.font_path
        paths = {"semi": self.semibold_path, "black": self.black_path}
        try:
            for scale in (1.0, .95, .9, .85, .8, .75, .7):
                result, height = [], 0
                for name, text, start, minimum, max_lines, color, gap, weight in blocks:
                    self.font_path = paths.get(weight, self.bold_path)
                    size, lines = self.fit(text, width, max(minimum, int(start * scale)), minimum, max_lines)
                    if size is None:
                        break
                    height += gap + len(lines) * self.line_h(size)
                    result.append((name, lines, size, color, gap, self.font_path))
                if len(result) == len(blocks) and height <= max_h:
                    return result, height
        finally:
            self.font_path = original
        raise RenderError("المحتوى أطول من مساحة القالب؛ يحتاج تقسيمًا إلى سنابات")

    def _draw_blocks(self, over, measured, top, lay, align="right", right=RIGHT):
        self._target = over
        d = ImageDraw.Draw(over)
        y = top
        for name, lines, size, color, gap, font_path in measured:
            self.font_path = font_path
            lay.fonts.add(font_path)
            y += gap
            y = self.draw_lines(d, lines, size, y, color, lay, name, align=align, x_right=right)
        self.font_path = self.bold_path
        return y

    def _draw_news(self, ink, measured, top, lay):
        """Right-aligned headline with the yellow side bar beside its first block."""
        main = [m for m in measured if m[0] != "text:kicker"]
        if main:
            off = sum(m[4] + len(m[1]) * self.line_h(m[2]) for m in measured[:measured.index(main[0])])
            name, lines, size, color, gap, _ = main[0]
            top += off + gap
            h = min(len(lines) * self.line_h(size), 200)
            ImageDraw.Draw(ink).rectangle((RIGHT - 9, top + 12, RIGHT, top + h - 6), fill=YELLOW)
            top -= off + gap
        if False:
            h = min(len(lines) * self.line_h(size), 200)
            ImageDraw.Draw(ink).rectangle((RIGHT - 9, top + 12, RIGHT, top + h - 6), fill=YELLOW)
        return self._draw_blocks(ink, measured, top, lay, right=RIGHT - BAR_GAP)

    def _quote_mark(self, ink, top, lay):
        self.font_path = self.black_path
        lay.fonts.add(self.black_path)
        ImageDraw.Draw(ink).text((RIGHT, top), "“", font=self.font(230), anchor="rt", fill=YELLOW)
        self.font_path = self.bold_path

    # ---------- media ----------
    def _paste_photo(self, img, photo, x, y, scale, lay, radius=0):
        pw, ph = max(1, int(photo.width * scale)), max(1, int(photo.height * scale))
        resized = photo.resize((pw, ph), Image.Resampling.LANCZOS)
        mask = None
        if radius:
            mask = Image.new("L", (pw, ph), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius, fill=255)
        img.paste(resized, (x, y), mask)
        lay.add("photo", (x, y, x + pw, y + ph))
        lay.image_used, lay.image_scale, lay.photo_radius = True, scale, radius
        return pw, ph

    def _band(self, img, photo, top, height):
        """Full-width blurred, darkened copy of the photo behind a narrower whole photo."""
        bg = ImageOps.fit(photo, (W // 8, max(1, height // 8)), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(3)).resize((W, height), Image.Resampling.BICUBIC)
        img.paste(Image.blend(bg, Image.new("RGB", bg.size, BG), 0.55), (0, top))

    def _fade(self, deco, y0, y1, a0, a1):
        """Vertical navy fade on the decoration layer (above photo / video)."""
        if y1 <= y0:
            return
        h = y1 - y0
        alpha = Image.linear_gradient("L").resize((1, 256)).resize((W, h))
        alpha = alpha.point(lambda v: int(a0 + (a1 - a0) * v / 255))
        layer = Image.new("RGBA", (W, h), BG + (0,))
        layer.putalpha(alpha)
        deco.alpha_composite(layer, (0, y0))

    def _render_media(self, snap, photo, lay):
        if snap.template == "stats":
            return self._render_stats(snap, photo, lay)
        if snap.template == "result":
            return self._render_result(snap, photo, lay)
        img = self._background()
        ink, deco = Image.new("RGBA", (W, self.h)), Image.new("RGBA", (W, self.h))
        self._header(ink, snap, lay)
        statement = snap.template == "statement"
        tw = WIDTH if statement else WIDTH - BAR_GAP
        row_h = self._rows_height(snap.rows)
        mark = 150 if statement else 0
        gap = 56
        measured, th = self._measure(self._blocks(snap), tw, 760 if not snap.rows else 360)
        avail = self.text_bottom - th - row_h - gap - mark
        scale = min(W / photo.width, avail / photo.height, MAX_UPSCALE)
        pw, ph = int(photo.width * scale), int(photo.height * scale)
        if ph < 300:
            raise RenderError("المحتوى والصورة لا يتسعان في القالب")
        start = self.header_bottom + 14
        free = avail - ph - start
        ptop = start + free // 2 if free > 0 else max(0, avail - ph)
        if pw < W - 2:
            self._band(img, photo, ptop, ph)
        self._paste_photo(img, photo, (W - pw) // 2, ptop, scale, lay)
        pbottom = ptop + ph
        if ptop < self.header_bottom:
            self._fade(deco, 0, self.header_bottom + 70, 200, 0)
        else:
            self._fade(deco, ptop, ptop + 70, 90, 0)
        self._fade(deco, pbottom - 170, pbottom, 0, 170)
        self._slashes(deco, pbottom - 11)
        top = pbottom + gap
        if statement:
            self._quote_mark(ink, top - 10, lay)
            y = self._draw_blocks(ink, measured, top + mark, lay)
        else:
            y = self._draw_news(ink, measured, top, lay)
        if snap.rows:
            self._rows(ink, snap.rows, y + 26, lay)
        return img, ink, deco

    def _render_stats(self, snap, photo, lay):
        img = self._background()
        ink, deco = Image.new("RGBA", (W, self.h)), Image.new("RGBA", (W, self.h))
        self._header(ink, snap, lay)
        measured, th = self._measure(self._blocks(snap), WIDTH, 820)
        top = self.header_bottom + 34
        if photo is not None:
            avail = min(620, self.text_bottom - th - 60 - top)
            scale = min(WIDTH / photo.width, avail / photo.height, MAX_UPSCALE)
            pw, ph = int(photo.width * scale), int(photo.height * scale)
            if ph < 260:
                raise RenderError("المحتوى والصورة لا يتسعان في القالب")
            ImageDraw.Draw(img).rounded_rectangle((LEFT, top, RIGHT, top + ph), 32, fill=PANEL)
            self._paste_photo(img, photo, (W - pw) // 2, top, scale, lay, radius=28)
            y = top + ph + 40
            self._slashes(deco, top + ph + 30)
        else:
            y = top + max(40, (self.text_bottom - top - th) // 3)
            self._slashes(deco, y + 20)
        self._draw_blocks(ink, measured, y, lay, align="center")
        if snap.number_caption:
            cap = next((b for n, b in lay.boxes if n == "text:number_caption"), None)
            if cap:
                ImageDraw.Draw(ink).rounded_rectangle((W / 2 - 70, cap[3] + 4, W / 2 + 70, cap[3] + 12), 4, fill=YELLOW)
        return img, ink, deco

    def _team_circle(self, ink, cx, cy, name, lay, key):
        d = ImageDraw.Draw(ink)
        r = 96
        ours = "النصر" in name
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=YELLOW if ours else (34, 40, 54),
                  outline=None if ours else MUTED, width=0 if ours else 6)
        self.font_path = self.black_path
        size, lines = self.fit(name, 2 * r - 40, 42, 22, 2)
        if size is None:
            raise RenderError("اسم الفريق أطول من مساحة الدائرة")
        h = len(lines) * self.line_h(size)
        y = cy - h / 2
        for line in lines:
            d.text((cx, y + self.line_h(size) / 2), self.display_text(line), font=self.font(size), anchor="mm",
                   direction="rtl", language="ar", fill=BG if ours else WHITE)
            y += self.line_h(size)
        self.font_path = self.bold_path
        size, lines = self.fit(name, 250, 42, 28, 2)
        if size is None:
            raise RenderError("اسم الفريق طويل")
        self._target = ink
        lay.fonts.add(self.black_path)
        return self.draw_lines_at(ink, lines, size, cy + r + 18, cx, lay, "text:" + key)

    def draw_lines_at(self, ink, lines, size, y, cx, lay, name):
        d = ImageDraw.Draw(ink)
        top, maxw = y, 0
        for line in lines:
            d.text((cx, y), self.display_text(line), font=self.font(size), anchor="mt",
                   direction="rtl", language="ar", fill=WHITE)
            maxw = max(maxw, self.width(line, size))
            lay.texts.append(line)
            y += self.line_h(size)
        lay.add(name, (cx - maxw / 2, top, cx + maxw / 2, y))
        return y

    def _render_result(self, snap, photo, lay):
        if not (snap.home and snap.away and snap.home_score and snap.away_score):
            raise RenderError("بيانات النتيجة ناقصة")
        img = self._background()
        ink, deco = Image.new("RGBA", (W, self.h)), Image.new("RGBA", (W, self.h))
        self._header(ink, snap, lay)
        d = ImageDraw.Draw(ink)
        y = self.header_bottom + 22
        if snap.competition:
            self.font_path = self.semibold_path
            size, lines = self.fit(snap.competition, WIDTH, 36, 28, 1)
            if size is None:
                raise RenderError("اسم البطولة طويل")
            y = self.draw_lines(d, lines, size, y, SOFT, lay, "text:competition", align="center") + 18
            self.font_path = self.bold_path
        board = (LEFT, y, RIGHT, y + 440)
        d.rounded_rectangle(board, 44, fill=(255, 255, 255, 22), outline=(255, 255, 255, 40), width=2)
        cy = y + 170
        # RTL: the home side reads first, on the right.
        self._team_circle(ink, RIGHT - 160, cy, snap.home, lay, "home")
        self._team_circle(ink, LEFT + 160, cy, snap.away, lay, "away")
        self.font_path = self.black_path
        lay.fonts.add(self.black_path)
        for x, value, key in ((W / 2 + 74, snap.home_score, "home_score"), (W / 2 - 74, snap.away_score, "away_score")):
            d.text((x, cy), value, font=self.font(170), anchor="mm", direction="ltr", fill=WHITE)
            lay.texts.append(value)
            wv = self.font(170).getlength(value)
            lay.add("text:" + key, (x - wv / 2, cy - 90, x + wv / 2, cy + 90))
        d.rounded_rectangle((W / 2 - 16, cy - 6, W / 2 + 16, cy + 6), 3, fill=YELLOW)
        label = "انتهت"
        lw = self.width(label, 32) + 64
        pill = (W / 2 - lw / 2, board[3] - 28, W / 2 + lw / 2, board[3] + 28)
        d.rounded_rectangle(pill, 28, fill=YELLOW)
        d.text((W / 2, board[3] - 2), label, font=self.font(32), anchor="mm", direction="rtl",
               language="ar", fill=BG)
        self.font_path = self.bold_path
        y = board[3] + 60
        if snap.rows:
            y = self._scorers(ink, snap, y, lay) + 40
        measured, th = self._measure(self._blocks(snap), WIDTH, max(0, self.text_bottom - y)) \
            if (snap.headline or snap.body) else ([], 0)
        if photo is not None:
            avail = self.text_bottom - y - th - (40 if th else 0)
            scale = min(WIDTH / photo.width, avail / photo.height, MAX_UPSCALE)
            pw, ph = int(photo.width * scale), int(photo.height * scale)
            if ph < 240:
                raise RenderError("المحتوى والصورة لا يتسعان في القالب")
            if th:
                y = self._draw_blocks(ink, measured, y, lay, align="center") + 40
            ImageDraw.Draw(img).rounded_rectangle((LEFT, y, RIGHT, y + ph), 28, fill=PANEL)
            self._paste_photo(img, photo, (W - pw) // 2, y, scale, lay, radius=28)
        elif th:
            self._slashes(deco, y + 4, side="right")
            self._draw_blocks(ink, measured, y + 50, lay, align="center")
        return img, ink, deco

    def _scorers(self, ink, snap, top, lay):
        """Two columns of scorers; each row is (team, scorer and minutes) from the source."""
        d = ImageDraw.Draw(ink)
        cols = {snap.home: [], snap.away: []}
        for team, who in snap.rows:
            side = snap.away if team and (team in snap.away or snap.away in team) else snap.home
            cols[side].append(who)
        cw = (WIDTH - 24) / 2
        bottom = top
        for i, (team, names) in enumerate(cols.items()):
            if not names:
                continue
            x1 = RIGHT - i * (cw + 24)
            heading = [("text:goals_head_%d" % i, "أهداف " + team, 32, 26, 1, YELLOW, 0, "black")]
            body = [("text:goals_%d" % i, "\n".join(names), 34, 26, 8, WHITE, 10, "bold")]
            m, h = self._measure(heading + body, cw - 56, 560)
            d.rounded_rectangle((x1 - cw, top, x1, top + h + 52), 28, fill=(255, 255, 255, 18))
            self._draw_blocks(ink, m, top + 22, lay, right=int(x1 - 28))
            bottom = max(bottom, top + h + 52)
        return bottom

    def _rows_height(self, rows):
        return len(rows) * 126 + (26 if rows else 0)

    def _rows(self, over, rows, top, lay):
        d = ImageDraw.Draw(over)
        for i, (label, value) in enumerate(rows):
            y = top + i * 126
            d.rounded_rectangle((LEFT, y, RIGHT, y + 108), 18, fill=(255, 255, 255, 20))
            d.rectangle((RIGHT - 6, y + 20, RIGHT, y + 88), fill=YELLOW)
            # Independent cells avoid bidi collisions between labels, prices,
            # parentheses and numeric ranges.
            label_lines, lh = self._measure([("text:row_label", label, 42, 30, 2, WHITE, 0, "bold")], 510, 90)
            self._draw_blocks(over, label_lines, y + (108 - lh) // 2, lay, right=RIGHT - 28)
            self.font_path = self.black_path
            size, lines = self.fit(value, 280, 42, 30, 2)
            if size is None:
                raise RenderError("قيمة الصف أطول من مساحة الخانة")
            h = len(lines) * self.line_h(size)
            self._target = over
            lay.fonts.add(self.black_path)
            self.draw_lines(d, lines, size, y + (108 - h) // 2, YELLOW, lay,
                            "text:row_value", align="right", x_right=LEFT + 304)
            self.font_path = self.bold_path

    def _render_text(self, snap, lay):
        if snap.template == "stats":
            return self._render_stats(snap, None, lay)
        if snap.template == "result":
            return self._render_result(snap, None, lay)
        img = self._background()
        ink, deco = Image.new("RGBA", (W, self.h)), Image.new("RGBA", (W, self.h))
        self._header(ink, snap, lay)
        statement = snap.template == "statement"
        row_h = self._rows_height(snap.rows)
        top = self.header_bottom + (90 if snap.rows else 150)
        mark = 150 if statement else 0
        tw = WIDTH if statement else WIDTH - BAR_GAP
        measured, th = self._measure(self._blocks(snap), tw, self.text_bottom - top - row_h - mark)
        if not snap.rows:
            # Short news sits in the upper third instead of hugging the header.
            top += max(0, (self.text_bottom - top - th - mark) // 3 - 40)
        self._slashes(deco, top - 64)
        if statement:
            self._quote_mark(ink, top - 20, lay)
            y = self._draw_blocks(ink, measured, top + mark, lay)
        else:
            y = self._draw_news(ink, measured, top, lay)
        if snap.rows:
            self._rows(ink, snap.rows, y + 26, lay)
        return img, ink, deco

    def _render_dhikr(self, snap, lay):
        img = self._background()
        ink, deco = Image.new("RGBA", (W, self.h)), Image.new("RGBA", (W, self.h))
        self._header(ink, snap, lay)
        d = ImageDraw.Draw(deco)
        frame = (LEFT, self.header_bottom + 40, RIGHT, self.text_bottom)
        d.rounded_rectangle(frame, 36, outline=GOLD + (200,), width=4)
        measured, th = self._measure(self._blocks(snap), WIDTH - 96, frame[3] - frame[1] - 80)
        top = frame[1] + max(40, (frame[3] - frame[1] - th) // 2)
        self._draw_blocks(ink, measured, top, lay, align="center")
        return img, ink, deco

    @staticmethod
    def _shadow(ink):
        alpha = ink.getchannel("A").filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.55))
        shadow = Image.new("RGBA", ink.size, (0, 0, 0, 0))
        shadow.paste(Image.new("RGBA", ink.size, (0, 0, 0, 255)), (0, 4), alpha)
        return shadow

    def render(self, snap: Snap):
        lay = Layout()
        lay.canvas, lay.safe_top, lay.footer_top = (W, self.h), self.safe, self.foot
        lay.fonts.add(self.bold_path)
        self.font_path = self.bold_path
        photo = self.load_photo(snap.image_path) if snap.template != "dhikr" else None
        if snap.template == "dhikr":
            img, ink, deco = self._render_dhikr(snap, lay)
        elif photo is not None:
            img, ink, deco = self._render_media(snap, photo, lay)
        else:
            img, ink, deco = self._render_text(snap, lay)
        self._footer(ink, snap, lay)
        over = deco
        over.alpha_composite(self._shadow(ink))
        over.alpha_composite(ink)
        lay.base, lay.overlay = img, over
        final = img.convert("RGBA")
        final.alpha_composite(over)
        return final.convert("RGB"), lay

    def render_post(self, snap: Snap):
        """Same design on a 4:5 canvas (1080×1350) for X / Instagram."""
        saved = self.h, self.safe, self.foot
        self.h, self.safe, self.foot = POST_H, 44, POST_H - 118
        try:
            return self.render(snap)
        finally:
            self.h, self.safe, self.foot = saved

    # Compatibility entry points used by older tests / callers.
    def _render_poster(self, snap, photo, lay, full=False):
        img, ink, deco = self._render_media(snap, photo, lay)
        deco.alpha_composite(ink)
        return img, deco

    def _render_card(self, snap, photo, lay):
        return self._render_poster(snap, photo, lay)


class LegacyDesigner(Designer):
    """Keep optional old themes while supporting structured news and pagination."""
    def __init__(self, cfg, emoji=None):
        super().__init__(cfg.font_path, cfg.logo_path, cfg.snap_handle, cfg.account_name, emoji=emoji)
        self.legacy = Renderer(cfg.font_path, cfg.logo_path, cfg.snap_handle, cfg.account_name,
                               emoji=emoji, style=cfg.design_style)

    def render(self, snap):
        if snap.template in ("tickets", "availability", "dhikr") or snap.rows:
            return super().render(snap)
        return self.legacy.render(snap)

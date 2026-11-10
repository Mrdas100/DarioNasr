"""Editorial Snapchat templates sharing one type scale, grid and safe area.

Real source media stays intact. Text, branding and video overlays share the
same measured geometry; overflow raises instead of silently cutting content.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .models import TEMPLATE_AR, Snap
from .render import FOOTER_TOP, H, SAFE_TOP, W, Layout, RenderError, Renderer

BLUE = (24, 58, 150)
NAVY = (9, 22, 58)
INK = (14, 24, 52)
YELLOW = (255, 204, 0)
RED = (215, 27, 48)
WHITE = (255, 255, 255)
MUTED = (89, 100, 121)
LIGHT = (243, 245, 249)
BORDER = (222, 227, 237)
GOLD = (190, 151, 68)
LEFT, RIGHT = 84, W - 84
WIDTH = RIGHT - LEFT
TEXT_BOTTOM = FOOTER_TOP - 42
MAX_UPSCALE = 2.1


def create_renderer(cfg, emoji=None):
    """The service and CLI must preview exactly the same selected renderer."""
    if cfg.design_style in ("clean", "cinema", "brand"):
        return LegacyDesigner(cfg, emoji)
    return Designer(cfg.font_path, cfg.logo_path, cfg.snap_handle, cfg.account_name, emoji=emoji)


class Designer(Renderer):
    def __init__(self, font_path: Path, logo_path, handle, account_name, emoji=None,
                 semibold_path: Path | None = None):
        super().__init__(font_path, logo_path, handle, account_name, emoji=emoji)
        self.bold_path = str(font_path)
        sb = Path(semibold_path) if semibold_path else Path(font_path).with_name(
            Path(font_path).name.replace("-Bold", "-SemiBold"))
        self.semibold_path = str(sb) if sb.exists() else self.bold_path

    @staticmethod
    def line_h(size):
        return int(size * 1.42)

    @staticmethod
    def _is_video(snap):
        from .video import video_of
        return video_of(snap.image_path) is not None

    def paginate(self, snap: Snap) -> list[Snap]:
        """Preserve every word / row on numbered pages rather than shrink to dust."""
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

    def _logo_img(self, max_w, max_h):
        if not self.logo_path:
            return None
        with Image.open(self.logo_path) as source:
            logo = source.convert("RGBA")
        box = logo.getchannel("A").getbbox()
        if box:
            logo = logo.crop(box)
        logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        return logo

    def _header(self, over, snap, lay, dark=False):
        d = ImageDraw.Draw(over)
        fg = WHITE if dark else INK
        d.rectangle((LEFT, SAFE_TOP + 12, LEFT + 72, SAFE_TOP + 20), fill=YELLOW)
        # A compact original logo, consistently sized across all templates.
        box = (RIGHT - 142, SAFE_TOP + 4, RIGHT, SAFE_TOP + 148)
        d.rounded_rectangle(box, 22, fill=NAVY)
        logo = self._logo_img(116, 122)
        if logo is not None:
            over.alpha_composite(logo, (box[0] + (142 - logo.width) // 2,
                                        box[1] + (144 - logo.height) // 2))
        else:
            d.text((RIGHT - 71, SAFE_TOP + 65), self.account_name, font=self.font(24),
                   anchor="mm", direction="rtl", language="ar", fill=WHITE)
        lay.add("logo", box)
        label = "" if snap.template == "comment" else TEMPLATE_AR.get(snap.template, "أخبار النصر")
        if snap.template == "availability" and any(t in snap.headline for t in ("إصابات", "اصابات")):
            label = "الإصابات"
        if label:
            width = max(145, int(self.width(label, 38)) + 58)
            bg = RED if snap.template == "breaking" else (YELLOW if snap.template == "tickets" else fg)
            color = WHITE if snap.template == "breaking" or not dark and snap.template != "tickets" else NAVY
            chip = (LEFT, SAFE_TOP + 58, LEFT + width, SAFE_TOP + 126)
            d.rounded_rectangle(chip, 14, fill=bg)
            d.text((LEFT + width / 2, SAFE_TOP + 92), label, font=self.font(38),
                   anchor="mm", direction="rtl", language="ar", fill=color)
            lay.add("chip:" + label, chip)
            lay.texts.append(label)
        d.line((LEFT, 328, RIGHT, 328), fill=(55, 70, 102) if dark else BORDER, width=2)

    def _footer(self, over, snap, lay, dark=False):
        d = ImageDraw.Draw(over)
        y = FOOTER_TOP + 36
        color = WHITE if dark else INK
        d.line((LEFT, FOOTER_TOP, RIGHT, FOOTER_TOP), fill=(55, 70, 102) if dark else BORDER, width=2)
        d.text((RIGHT, y), self.account_name, font=self.font(34), anchor="rm",
               direction="rtl", language="ar", fill=color)
        # Explicit LTR segment keeps the Latin username and numbers stable.
        d.text((LEFT, y), self.handle, font=self.font(38), anchor="lm", direction="ltr",
               fill=YELLOW if dark else BLUE)
        if snap.pages > 1:
            d.text((W // 2, y), f"{snap.page} / {snap.pages}", font=self.font(28),
                   anchor="mm", direction="ltr", fill=GOLD if dark else MUTED)
        lay.add("footer", (0, FOOTER_TOP, W, H))
        lay.texts.extend((self.handle, self.account_name))

    def _blocks(self, snap, dark=False):
        main, accent, muted = (WHITE, YELLOW, (208, 216, 232)) if dark else (INK, BLUE, MUTED)
        out = []
        def add(name, value, size, minimum, lines, color, gap=0, weight="bold"):
            if value:
                out.append(("text:" + name, value, size, minimum, lines, color, gap, weight))
        if snap.kicker and snap.kicker != TEMPLATE_AR.get(snap.template):
            add("kicker", snap.kicker, 36, 32, 2, accent)
        if snap.template == "statement":
            add("speaker", snap.speaker, 43, 36, 2, accent, 0)
            add("quote", snap.quote or snap.headline, 76, 48, 12, main, 24)
            add("body", snap.body, 44, 38, 5, muted, 30, "semi")
        elif snap.template == "stats":
            add("number", snap.number, 180, 120, 1, accent)
            add("number_caption", snap.number_caption, 45, 38, 2, muted, 8)
            add("headline", snap.headline, 69, 50, 4, main, 30)
            add("body", snap.body, 46, 38, 6, muted, 24, "semi")
        else:
            add("headline", snap.headline, 80 if not snap.rows else 70, 52, 5, main)
            add("body", snap.body, 48, 40, 9, muted, 30, "semi")
        return out

    def _measure(self, blocks, width, max_h):
        """Measure without polluting QA boxes. No cutting lines on failure."""
        original = self.font_path
        try:
            for scale in (1.0, .95, .9, .85, .8, .75, .7):
                result, height = [], 0
                for name, text, start, minimum, max_lines, color, gap, weight in blocks:
                    self.font_path = self.semibold_path if weight == "semi" else self.bold_path
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
            y += gap
            y = self.draw_lines(d, lines, size, y, color, lay, name, align=align, x_right=right)
        self.font_path = self.bold_path
        return y

    def _photo(self, img, photo, top, height, lay):
        """Contain source pixels within a neutral panel; never crop a face or crest."""
        scale = min(WIDTH / photo.width, height / photo.height, MAX_UPSCALE)
        pw, ph = max(1, int(photo.width * scale)), max(1, int(photo.height * scale))
        x, y = (W - pw) // 2, top + (height - ph) // 2
        ImageDraw.Draw(img).rounded_rectangle((LEFT, top, RIGHT, top + height), 24, fill=LIGHT)
        img.paste(photo.resize((pw, ph), Image.Resampling.LANCZOS), (x, y))
        lay.add("photo", (x, y, x + pw, y + ph))
        lay.image_used, lay.image_scale, lay.photo_radius = True, scale, 0

    def _render_media(self, snap, photo, lay):
        img, over = Image.new("RGB", (W, H), WHITE), Image.new("RGBA", (W, H))
        self._header(over, snap, lay)
        blocks = self._blocks(snap)
        measured, th = self._measure(blocks, WIDTH, 790 if not snap.rows else 380)
        # All text stays below source media. Portraits receive more of the
        # available space without forcing the title into Snapchat's reply bar.
        row_h = self._rows_height(snap.rows)
        photo_h = min(780 if photo.height > photo.width else 580,
                      TEXT_BOTTOM - 364 - th - row_h - 48)
        if photo_h < 260:
            raise RenderError("المحتوى والصورة لا يتسعان في القالب")
        self._photo(img, photo, 364, int(photo_h), lay)
        top = 364 + int(photo_h) + 48
        y = self._draw_blocks(over, measured, top, lay)
        if snap.rows:
            self._rows(over, snap.rows, y + 26, lay)
        return img, over

    def _render_poster(self, snap, photo, lay, full=False):
        # Public compatibility entry point. Video uses the exact same photo
        # box as the still so its geometry cannot cover the headline.
        return self._render_media(snap, photo, lay)

    def _render_card(self, snap, photo, lay):
        return self._render_media(snap, photo, lay)

    def _rows_height(self, rows):
        return len(rows) * 132 + (26 if rows else 0)

    def _rows(self, over, rows, top, lay):
        d = ImageDraw.Draw(over)
        for i, (label, value) in enumerate(rows):
            y = top + i * 132
            d.rounded_rectangle((LEFT, y, RIGHT, y + 114), 18, fill=LIGHT)
            d.rectangle((RIGHT - 5, y + 22, RIGHT, y + 92), fill=YELLOW)
            # Independent cells avoid bidi collisions between labels, prices,
            # parentheses and numeric ranges.
            label_lines, lh = self._measure([("text:row_label", label, 45, 32, 2, INK, 0, "bold")],
                                           510, 94)
            self._draw_blocks(over, label_lines, y + (114 - lh) // 2, lay, right=RIGHT - 28)
            self.font_path = self.bold_path
            size, lines = self.fit(value, 280, 43, 32, 2)
            if size is None:
                raise RenderError("قيمة الصف أطول من مساحة الخانة")
            h = len(lines) * self.line_h(size)
            self._target = over
            self.draw_lines(d, lines, size, y + (114 - h) // 2, BLUE, lay,
                            "text:row_value", align="right", x_right=LEFT + 304)

    def _render_text(self, snap, lay):
        img, over = Image.new("RGB", (W, H), WHITE), Image.new("RGBA", (W, H))
        self._header(over, snap, lay)
        blocks = self._blocks(snap)
        row_h = self._rows_height(snap.rows)
        top = 444 if snap.rows else 490
        measured, th = self._measure(blocks, WIDTH, TEXT_BOTTOM - top - row_h)
        # Anchor news to a consistent editorial grid instead of vertically
        # centering each post and producing enormous empty areas above it.
        if snap.template == "statement":
            d = ImageDraw.Draw(over)
            d.rounded_rectangle((LEFT, 378, LEFT + 92, 438), 12, fill=YELLOW)
            d.text((LEFT + 46, 410), "«", font=self.font(76), anchor="mm", fill=INK)
        self._draw_blocks(over, measured, top, lay)
        if snap.rows:
            self._rows(over, snap.rows, top + th + 26, lay)
        elif snap.template != "dhikr":
            d = ImageDraw.Draw(over)
            end = min(top + th + 72, TEXT_BOTTOM - 18)
            d.line((RIGHT - 96, end, RIGHT, end), fill=YELLOW, width=8)
        return img, over

    def _render_dhikr(self, snap, lay):
        img, over = Image.new("RGB", (W, H), NAVY), Image.new("RGBA", (W, H))
        self._header(over, snap, lay, dark=True)
        measured, th = self._measure(self._blocks(snap, dark=True), WIDTH - 64, 1070)
        top = 430 + max(0, (1120 - th) // 2)
        self._draw_blocks(over, measured, top, lay, align="center")
        return img, over

    def render(self, snap: Snap):
        lay = Layout()
        lay.fonts.add(self.bold_path)
        photo = self.load_photo(snap.image_path) if snap.template != "dhikr" else None
        if snap.template == "dhikr":
            img, over = self._render_dhikr(snap, lay)
        elif photo is not None:
            img, over = self._render_media(snap, photo, lay)
        else:
            img, over = self._render_text(snap, lay)
        self._footer(over, snap, lay, dark=snap.template == "dhikr")
        lay.base, lay.overlay = img, over
        final = img.convert("RGBA")
        final.alpha_composite(over)
        return final.convert("RGB"), lay


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

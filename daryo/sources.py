"""مصادر القراءة من قناة منبر النصر

مهم: Telegram Bot API لا يستطيع قراءة منشورات قناة عامة لا يكون البوت مشرفًا فيها،
لذلك يوجد طريقان مصرح بهما:
1) telethon: حساب تيليجرام خاص بك (عضو في القناة) عبر MTProto API الرسمي ببيانات
   api_id و api_hash من my.telegram.org. قراءة فقط. هذا الطريق الأدق والأفضل للصور بدقة كاملة
2) web: صفحة المعاينة العامة https://t.me/s/<channel> التي يتيحها تيليجرام لكل قناة عامة
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .models import SourcePost

log = logging.getLogger("daryo.source")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


class SourceError(Exception):
    pass


MAX_BOT_VIDEO = 20 * 1024 * 1024   # حد تحميل Bot API


def extract_frame(video: Path, out: Path) -> bool:
    """لقطة بالدقة الكاملة من فيديو الخبر الأصلي (ffmpeg)"""
    import subprocess
    for ss in ("1", "0"):
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", ss, "-i", str(video),
                            "-frames:v", "1", "-q:v", "2", str(out)], check=True, timeout=60)
            if out.exists() and out.stat().st_size > 1000:
                return True
        except Exception as e:
            log.warning("تعذر استخراج لقطة من الفيديو: %s", e)
    return False


def _save_media(kind: str, fetch, ref, thumb, dest: Path, stem: str) -> str | None:
    """fetch(ref) -> bytes. للفيديو: لقطة من الفيديو نفسه وإلا الصورة المصغرة"""
    if kind == "video":
        if ref is not None:
            try:
                vid = dest / f"{stem}.mp4"
                vid.write_bytes(fetch(ref))
                jpg = dest / f"{stem}.jpg"
                ok = extract_frame(vid, jpg)   # الفيديو يبقى بجانب اللقطة لسنابة الفيديو
                if not ok:
                    vid.unlink(missing_ok=True)
                if ok:
                    return str(jpg)
            except Exception as e:
                log.warning("تعذر تحميل الفيديو %s: %s", stem, e)
        if thumb is None:
            return None
        ref = thumb
    data = fetch(ref)
    p = dest / f"{stem}.jpg"
    p.write_bytes(data)
    return str(p)


class TelethonSource:
    name = "telethon"

    def __init__(self, cfg):
        from telethon import TelegramClient  # استيراد متأخر
        self.cfg = cfg
        self.client = TelegramClient(cfg.tg_session, cfg.tg_api_id, cfg.tg_api_hash,
                                     device_model="DaryoAlnasr", app_version="1.0")
        self.entity = None

    async def start(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise SourceError("جلسة تيليجرام غير مسجلة. شغّل: python -m daryo.cli login")
        self.entity = await self.client.get_entity(self.cfg.source_channel)

    async def stop(self):
        await self.client.disconnect()

    async def fetch_latest(self, limit: int = 40) -> list[SourcePost]:
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
        if not self.client.is_connected():
            await self.client.connect()
        msgs = await self.client.get_messages(self.entity, limit=limit)
        groups: dict = {}
        for m in sorted(msgs, key=lambda x: x.id):
            if m.action is not None:     # رسائل خدمة
                continue
            key = m.grouped_id or f"m{m.id}"
            p = groups.get(key)
            if p is None:
                p = SourcePost(msg_id=m.id, date=m.date, text="", grouped_id=m.grouped_id,
                               url=f"https://t.me/{self.cfg.source_channel}/{m.id}")
                groups[key] = p
            if m.message and not p.text:
                p.text = m.message
            p.msg_ids.append(m.id)
            p.is_forward = p.is_forward or bool(m.fwd_from)
            p.has_buttons = p.has_buttons or bool(m.reply_markup)
            p.edited = p.edited or bool(m.edit_date)
            if isinstance(m.media, MessageMediaPhoto):
                p.media_refs.append(("photo", m, None))
            elif isinstance(m.media, MessageMediaDocument) and m.file and m.file.mime_type:
                if m.file.mime_type.startswith("video"):
                    p.has_video = True
                    p.media_refs.append(("video", m, m))
                elif m.file.mime_type.startswith("image"):
                    p.media_refs.append(("photo", m, None))
        return list(groups.values())

    async def download(self, post: SourcePost, dest: Path) -> list[str]:
        out = []
        dest.mkdir(parents=True, exist_ok=True)
        for i, (kind, m, _) in enumerate(post.media_refs):
            target = dest / f"{post.msg_id}_{i}"
            try:
                if kind == "photo":
                    path = await self.client.download_media(m, file=str(target))
                else:
                    path = None
                    if (m.file.size or 0) <= 50 * 1024 * 1024:
                        vid = await self.client.download_media(m, file=str(target) + ".mp4")
                        jpg = Path(str(target) + ".jpg")
                        if vid and await asyncio.to_thread(extract_frame, Path(vid), jpg):
                            path = str(jpg)
                        elif vid:
                            Path(vid).unlink(missing_ok=True)
                    if not path:  # أكبر صورة مصغرة للفيديو كما نشرها المصدر
                        path = await self.client.download_media(m, file=str(target), thumb=-1)
                if path:
                    out.append(str(path))
            except Exception as e:
                log.warning("فشل تحميل وسائط %s: %s", post.msg_id, e)
        return out


class WebSource:
    name = "web"

    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

    async def start(self):
        pass

    async def stop(self):
        pass

    async def fetch_latest(self, limit: int = 40) -> list[SourcePost]:
        return await asyncio.to_thread(self._fetch)

    def _fetch(self) -> list[SourcePost]:
        url = f"https://t.me/s/{self.cfg.source_channel}"
        try:
            r = self.session.get(url, timeout=25)
        except requests.RequestException as e:
            raise SourceError(f"تعذر الوصول إلى {url}: {e}")
        if r.status_code != 200:
            raise SourceError(f"صفحة المعاينة أعادت {r.status_code}")
        posts = parse_preview_html(r.text, self.cfg.source_channel)
        if not posts and "tgme_channel_info" not in r.text:
            raise SourceError("صفحة المعاينة لا تحتوي منشورات. ربما عُطلت المعاينة للقناة")
        return posts

    async def download(self, post: SourcePost, dest: Path) -> list[str]:
        return await asyncio.to_thread(self._download, post, dest)

    def _download(self, post: SourcePost, dest: Path) -> list[str]:
        out = []
        dest.mkdir(parents=True, exist_ok=True)
        def fetch(link):
            r = self.session.get(link, timeout=60)
            r.raise_for_status()
            return r.content
        for i, (kind, link, thumb) in enumerate(post.media_refs):
            try:
                path = _save_media(kind, fetch, link, thumb, dest, f"{post.msg_id}_{i}")
                if path:
                    out.append(path)
            except Exception as e:
                log.warning("فشل تحميل صورة %s: %s", post.msg_id, e)
        return out


class BotSource:
    """البوت مشرف في القناة: يستقبل المنشورات فور نشرها بالدقة الكاملة عبر Bot API"""
    name = "bot"
    SETTLE_SEC = 8          # انتظار اكتمال صور الألبوم قبل المعالجة

    def __init__(self, cfg):
        self.cfg = cfg
        self.bot = None
        self.lock = threading.Lock()
        self.buffer: dict = {}       # key -> (SourcePost, last_update_monotonic)

    def attach(self, bot):
        self.bot = bot

    async def start(self):
        if self.bot is None:
            raise SourceError("وضع bot يحتاج BOT_TOKEN")

    async def stop(self):
        pass

    def _matches(self, chat: dict) -> bool:
        want = self.cfg.source_channel.lstrip("@").lower()
        return (chat.get("username") or "").lower() == want or str(chat.get("id")) == want

    def on_channel_post(self, m: dict, edited: bool):
        chat = m.get("chat") or {}
        if not self._matches(chat):
            log.info("تجاهل منشور من قناة أخرى: %s", chat.get("username") or chat.get("id"))
            return
        key = m.get("media_group_id") or f"m{m['message_id']}"
        log.info("استُقبل منشور من القناة %s%s", m["message_id"], " (تعديل)" if edited else "")
        with self.lock:
            entry = self.buffer.get(key)
            if entry is None or edited:
                old = entry[0] if entry else None
                p = SourcePost(msg_id=old.msg_id if old else m["message_id"],
                               date=datetime.fromtimestamp(m.get("date", time.time()), timezone.utc),
                               text="", url=f"https://t.me/{self.cfg.source_channel}/{m['message_id']}")
                if old and edited:
                    p.media_refs, p.text, p.date = old.media_refs, old.text, old.date
                    p.msg_ids = old.msg_ids
                p.edited = edited
            else:
                p = entry[0]
            p.msg_id = min(p.msg_id, m["message_id"])
            if m["message_id"] not in p.msg_ids:
                p.msg_ids.append(m["message_id"])
                p.msg_ids.sort()
            p.url = f"https://t.me/{self.cfg.source_channel}/{p.msg_id}"
            text = m.get("text") or m.get("caption") or ""
            if text and (edited or not p.text):
                p.text = text
            p.is_forward = p.is_forward or bool(m.get("forward_origin") or m.get("forward_from_chat"))
            p.has_buttons = p.has_buttons or bool(m.get("reply_markup"))
            if not edited:
                if m.get("photo"):
                    p.media_refs.append(("photo", m["photo"][-1]["file_id"], None))
                elif m.get("video") or m.get("animation"):
                    v = m.get("video") or m.get("animation")
                    p.has_video = True
                    th = v.get("thumbnail") or v.get("thumb")
                    vid = v["file_id"] if (v.get("file_size") or 0) <= MAX_BOT_VIDEO else None
                    if vid or th:
                        p.media_refs.append(("video", vid, th["file_id"] if th else None))
                elif (m.get("document") or {}).get("mime_type", "").startswith("image/"):
                    p.media_refs.append(("photo", m["document"]["file_id"], None))
            self.buffer[key] = (p, time.monotonic())
            # نحتفظ بآخر 100 منشور فقط
            if len(self.buffer) > 100:
                for k in sorted(self.buffer, key=lambda k: self.buffer[k][1])[:len(self.buffer) - 100]:
                    del self.buffer[k]

    async def fetch_latest(self, limit: int = 40) -> list[SourcePost]:
        now = time.monotonic()
        with self.lock:
            return [p for p, t in self.buffer.values() if now - t >= self.SETTLE_SEC]

    async def download(self, post: SourcePost, dest: Path) -> list[str]:
        return await asyncio.to_thread(self._download, post, dest)

    def _download(self, post: SourcePost, dest: Path) -> list[str]:
        out = []
        dest.mkdir(parents=True, exist_ok=True)
        for i, (kind, file_id, thumb) in enumerate(post.media_refs):
            try:
                path = _save_media(kind, self.bot.get_file_bytes, file_id, thumb, dest, f"{post.msg_id}_{i}")
                if path:
                    out.append(path)
            except Exception as e:
                log.warning("فشل تحميل صورة %s: %s", post.msg_id, e)
        return out


_BG = re.compile(r"background-image:url\('([^']+)'\)")


def parse_preview_html(html: str, channel: str) -> list[SourcePost]:
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        data_post = msg.get("data-post", "")
        try:
            msg_id = int(data_post.split("/")[-1])
        except ValueError:
            continue
        if "service_message" in (msg.get("class") or []):
            continue
        text_el = msg.select_one(".tgme_widget_message_text")
        text = ""
        if text_el:
            for br in text_el.find_all("br"):
                br.replace_with("\n")
            text = text_el.get_text()
        t = msg.select_one("time[datetime]")
        try:
            date = datetime.fromisoformat(t["datetime"]) if t else datetime.now(timezone.utc)
        except ValueError:
            date = datetime.now(timezone.utc)
        p = SourcePost(msg_id=msg_id, date=date, text=text.strip(),
                       url=f"https://t.me/{channel}/{msg_id}")
        p.is_forward = msg.select_one(".tgme_widget_message_forwarded_from") is not None
        p.has_buttons = msg.select_one(".tgme_widget_message_inline_keyboard") is not None
        p.edited = "edited" in (msg.select_one(".tgme_widget_message_meta") or soup.new_tag("i")).get_text()
        for a in msg.select("a.tgme_widget_message_photo_wrap"):
            m = _BG.search(a.get("style", ""))
            if m:
                p.media_refs.append(("photo", m.group(1), None))
        for wrap in msg.select(".tgme_widget_message_video_player"):
            p.has_video = True
            th = wrap.select_one("i.tgme_widget_message_video_thumb")
            m = _BG.search(th.get("style", "")) if th else None
            v = wrap.select_one("video[src]")
            if v or m:
                p.media_refs.append(("video", v["src"] if v else None, m.group(1) if m else None))
        if msg.select_one("video") is not None:
            p.has_video = True
        n = max(1, len(p.media_refs))
        p.msg_ids = list(range(msg_id, msg_id + n))
        posts.append(p)
    return posts


def make_source(cfg):
    mode = cfg.resolved_source_mode()
    if mode == "bot":
        return BotSource(cfg)
    if mode == "telethon":
        return TelethonSource(cfg)
    return WebSource(cfg)

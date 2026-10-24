"""الخدمة المستمرة: مراقبة ← فلترة ← كشف تكرار ← تحرير ← تصميم ← مراجعة ← إرسال"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import dedup
from .config import Config
from .db import DB, now_utc
from .editor import Editor, EditorError, to_snap
from .filters import reject_reason
from .models import TEMPLATE_AR, SourcePost
from .qa import QAError, check_image_file, check_render, check_snap_text, strip_unsupported, verify_font
from .render import RenderError, Renderer, save_png
from .schedule import in_hours, parse_hours
from .sources import BotSource, SourceError, WebSource, make_source
from .telegram_bot import Bot
from .textutil import normalize_ar

log = logging.getLogger("daryo")

HELP = """أوامر نظام داريو النصر:
/on تشغيل النظام
/off إيقاف النظام
/status الحالة
/hours 08:00-02:00 تحديد ساعات التشغيل (بتوقيت الرياض)
/hours 24 تشغيل طوال اليوم
/now فحص القناة فورًا
/last آخر 10 منشورات وحالتها
/latest 2 إعادة معالجة آخر منشورين في القناة
/test إرسال سنابة تجريبية"""


def text_hash(t: str) -> str:
    return hashlib.sha1(normalize_ar(t).encode()).hexdigest()


class Service:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.db = DB(cfg.db_path)
        self.dry_run = os.environ.get("DRY_RUN", "0") == "1" or not cfg.bot_token
        self.bot = None if self.dry_run else Bot(cfg.bot_token, cfg.owner_chat_id)
        self.source = make_source(cfg)
        if self.source.name == "bot":
            if not self.bot:
                raise SystemExit("وضع SOURCE_MODE=bot يحتاج BOT_TOKEN و OWNER_CHAT_ID")
            self.source.attach(self.bot)
        self.editor = Editor(cfg)
        self.renderer = Renderer(cfg.font_path, cfg.logo_path, cfg.snap_handle, cfg.account_name)
        self.wake = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.fail_count = 0
        self.alerted_down = False
        if self.db.get("enabled") is None:
            self.db.set("enabled", True)
        if self.db.get("hours") is None:
            self.db.set("hours", cfg.default_hours)

    # ---------- إشعارات ----------
    def alert(self, text: str):
        self.db.log("alert", text)
        log.error(text)
        if self.bot:
            self.bot.alert(text)

    def notify(self, text: str):
        log.info(text)
        if self.bot:
            try:
                self.bot.send_text(text)
            except Exception as e:
                log.error("تعذر إرسال رسالة: %s", e)

    # ---------- الأوامر ----------
    def handle_command(self, text: str) -> str:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/help"):
            return HELP
        if cmd == "/on":
            self.db.set("enabled", True)
            self._wake()
            return "✅ تم تشغيل النظام"
        if cmd == "/off":
            self.db.set("enabled", False)
            return "⏸ تم إيقاف النظام. لن تُصمم أخبار حتى /on"
        if cmd == "/hours":
            if not arg.strip():
                return f"ساعات التشغيل الحالية: {self.db.get('hours') or 'طوال اليوم'}"
            spec = arg.strip()
            parse_hours(spec)  # يرفع خطأ بصيغة مفهومة
            spec = "" if spec in ("24", "24h", "all", "off") else spec
            self.db.set("hours", spec)
            return f"🕘 ساعات التشغيل: {spec or 'طوال اليوم'} (توقيت الرياض)"
        if cmd == "/now":
            self._wake()
            return "🔎 جارٍ فحص القناة الآن"
        if cmd == "/status":
            return self.status_text()
        if cmd == "/last":
            rows = self.db.last_posts(10)
            if not rows:
                return "لا يوجد سجل بعد"
            return "\n".join(f"{r['msg_id']} | {r['status']} | {(r['headline'] or r['reason'] or (r['raw_text'] or '')[:40])}"
                             for r in rows)
        if cmd in ("/latest", "/retry"):
            n = int(arg) if arg.strip().isdigit() else 2
            asyncio.run_coroutine_threadsafe(self.reprocess_latest(min(n, 10)), self.loop)
            return f"🔁 جارٍ معالجة آخر {min(n, 10)} منشورات من القناة"
        if cmd == "/test":
            asyncio.run_coroutine_threadsafe(self.send_test(), self.loop)
            return "🧪 جارٍ تجهيز سنابة تجريبية"
        return "أمر غير معروف\n" + HELP

    def _wake(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.wake.set)

    def status_text(self) -> str:
        enabled = self.db.get("enabled")
        hours = self.db.get("hours") or ""
        active = in_hours(hours, self.cfg.timezone)
        st = self.db.stats_today()
        last = self.db.get("last_poll", "-")
        return (f"الحالة: {'يعمل' if enabled else 'موقوف يدويًا'}"
                f"{'' if active else ' (خارج ساعات التشغيل)'}\n"
                f"ساعات التشغيل: {hours or 'طوال اليوم'}\n"
                f"طريقة القراءة: {self.source.name}\n"
                f"التحرير: {'Claude' if self.editor.uses_llm else 'محرر محلي'}\n"
                f"آخر فحص: {last}\n"
                f"آخر 24 ساعة: أُرسل {st.get('sent', 0)} | مكرر {st.get('duplicate', 0)} | "
                f"مستبعد {st.get('skipped', 0)} | فشل {st.get('failed', 0)}")

    # ---------- التشغيل ----------
    async def run(self):
        self.loop = asyncio.get_running_loop()
        try:
            verify_font(self.cfg.font_path)
        except QAError as e:
            self.alert(f"توقف النظام: {e}")
            raise
        try:
            await self.source.start()
        except Exception as e:
            if self.source.name == "telethon":
                self.alert(f"تعذر تشغيل قراءة تيليجرام عبر الحساب ({e}). التحويل مؤقتًا إلى صفحة المعاينة العامة")
                self.source = WebSource(self.cfg)
            else:
                raise
        if self.bot:
            ch = self.source.on_channel_post if self.source.name == "bot" else None
            self.bot.start_command_loop(self.handle_command, ch)
        self.notify(f"🟢 بدأ نظام داريو النصر\n{self.status_text()}")
        await self.baseline()
        n = int(os.environ.get("REPROCESS_ON_START", "0") or 0)
        dep = os.environ.get("RAILWAY_DEPLOYMENT_ID", "local")
        if n > 0 and self.db.get("reprocessed_deploy") != dep:
            self.db.set("reprocessed_deploy", dep)
            await self.reprocess_latest(min(n, 10))
        while True:
            try:
                enabled = self.db.get("enabled")
                active = in_hours(self.db.get("hours") or "", self.cfg.timezone)
                if enabled and active:
                    await self.tick()
                else:
                    self.db.set("paused_since", self.db.get("paused_since") or now_utc().isoformat())
                self.db.set("heartbeat", now_utc().isoformat())
            except Exception as e:  # لا تسقط الخدمة أبدًا بسبب خبر واحد
                log.exception("خطأ غير متوقع")
                self.alert(f"خطأ غير متوقع في دورة الفحص: {e}")
            delay = random.randint(self.cfg.poll_min_sec, self.cfg.poll_max_sec)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    async def reprocess_latest(self, n: int):
        """يجلب آخر n منشورات من صفحة القناة العامة ويعالجها من جديد حتى لو سبق تسجيلها"""
        web = WebSource(self.cfg)
        try:
            posts = sorted(await web.fetch_latest(), key=lambda x: x.msg_id)[-n:]
        except Exception as e:
            self.alert(f"تعذر جلب آخر المنشورات: {e}")
            return
        lines = []
        for p in posts:
            try:
                await self.process(p, src=web)
            except Exception as e:
                log.exception("فشل إعادة المعالجة")
                self.alert(f"فشل معالجة {p.url}: {e}")
            row = self.db.known(p.msg_id)
            lines.append(f"{p.msg_id} | {row['status'] if row else '-'} | {(row['reason'] or row['headline'] or '') if row else ''}")
        self.notify("نتيجة إعادة المعالجة:\n" + ("\n".join(lines) or "لا توجد منشورات"))

    async def baseline(self):
        """أول تشغيل: لا نغرق المحادثة بالأخبار القديمة"""
        if self.db.get("baseline_done"):
            return
        posts = await self.source.fetch_latest()
        posts.sort(key=lambda p: p.msg_id)
        keep = posts[-self.cfg.initial_backfill:] if self.cfg.initial_backfill else []
        keep_ids = {p.msg_id for p in keep}
        for p in posts:
            if p.msg_id not in keep_ids:
                self.db.upsert_post(p.msg_id, posted_at=p.date.isoformat(), raw_text=p.text,
                                    norm_text=normalize_ar(p.text), text_hash=text_hash(p.text),
                                    status="baseline", reason="قبل بدء التشغيل")
        self.db.set("baseline_done", True)
        log.info("تم تسجيل %d منشور سابق كنقطة بداية", len(posts) - len(keep_ids))

    async def tick(self):
        try:
            posts = await self.source.fetch_latest()
            if self.fail_count >= self.cfg.alert_after_failures and self.alerted_down:
                self.notify("✅ عاد الاتصال بقناة المصدر")
            self.fail_count, self.alerted_down = 0, False
        except (SourceError, Exception) as e:
            self.fail_count += 1
            log.warning("فشل الفحص %d: %s", self.fail_count, e)
            if self.fail_count >= self.cfg.alert_after_failures and not self.alerted_down:
                self.alert(f"تعذر قراءة قناة المصدر {self.fail_count} مرات متتالية\n{e}")
                self.alerted_down = True
            return
        self.db.set("last_poll", datetime.now(ZoneInfo(self.cfg.timezone)).strftime("%Y-%m-%d %H:%M"))
        paused_since = self.db.get("paused_since")
        self.db.set("paused_since", None)
        cutoff = now_utc() - timedelta(minutes=self.cfg.catchup_max_age_min)
        for p in sorted(posts, key=lambda x: x.msg_id):
            row = self.db.known(p.msg_id)
            h = text_hash(p.text)
            if row is not None:
                if row["text_hash"] == h:
                    continue
                # المصدر عدّل المنشور: نعامله كتحديث إن تغير المعنى
                old_norm = row["norm_text"] or ""
                if row["status"] == "sent" and dedup.similarity(old_norm, normalize_ar(p.text)) < 0.9:
                    await self.process(p, edited_of=row)
                else:
                    self.db.upsert_post(p.msg_id, text_hash=h, raw_text=p.text, norm_text=normalize_ar(p.text))
                continue
            date = p.date if p.date.tzinfo else p.date.replace(tzinfo=timezone.utc)
            if date < cutoff:
                self.db.upsert_post(p.msg_id, posted_at=date.isoformat(), raw_text=p.text,
                                    norm_text=normalize_ar(p.text), text_hash=h, status="skipped",
                                    reason="منشور قديم (أثناء الإيقاف أو قبله)")
                continue
            await self.process(p)

    async def process(self, p: SourcePost, edited_of=None, src=None):
        raw = p.text or ""
        norm = normalize_ar(raw)
        base = dict(posted_at=p.date.isoformat(), raw_text=raw, norm_text=norm, text_hash=text_hash(raw))
        msg_id = p.msg_id
        reason = reject_reason(p)
        log.info("منشور %s: %s", msg_id, (raw or "[بدون نص]")[:60].replace("\n", " "))
        if reason:
            log.info("استبعاد %s: %s", msg_id, reason)
            self.db.upsert_post(msg_id, status="skipped", reason=reason, **base)
            return
        history = [r for r in self.db.recent_published(self.cfg.dedup_window_hours) if r["msg_id"] != msg_id]
        heur, cands = dedup.heuristic(raw, norm, history)
        if heur.relation == "duplicate" and heur.score >= 0.8:
            self.db.upsert_post(msg_id, status="duplicate", reason=heur.reason, dup_of=heur.ref_id, **base)
            return
        try:
            res, method = await asyncio.to_thread(self.editor.edit, raw, cands)
        except EditorError as e:
            self.db.upsert_post(msg_id, status="failed", reason=f"تحرير: {e}", **base)
            self.alert(f"فشل تحرير خبر ولم يُرسل شيء\nالسبب: {e}\n{p.url}")
            return
        if not res.publishable:
            self.db.upsert_post(msg_id, status="skipped", reason=res.skip_reason or "غير صالح للنشر", **base)
            return

        relation, ref = heur.relation, (heur.ref_id, heur.ref_msg_id)
        if method == "llm" and cands:
            relation = res.relation
            if 0 <= res.related_index < len(cands):
                r = cands[res.related_index][1]
                ref = (r["id"], r["msg_id"])
            elif relation != "new":
                ref = (cands[0][1]["id"], cands[0][1]["msg_id"])
        if edited_of is not None:
            relation, ref = "update", (edited_of["id"], edited_of["msg_id"])
        if relation == "duplicate":
            self.db.upsert_post(msg_id, status="duplicate", reason="نفس خبر سابق بصياغة مختلفة",
                                dup_of=ref[0], **base)
            return
        is_update = relation == "update"
        old_headline = ""
        if is_update and ref[1]:
            old = self.db.known(ref[1])
            old_headline = (old["headline"] if old else "") or ""

        # الصور الأصلية من المصدر
        photos: list[str] = []
        img_note = ""
        if self.cfg.use_source_images and p.media_refs:
            downloaded = await (src or self.source).download(p, self.cfg.media_dir)
            for ph in downloaded:
                try:
                    check_image_file(ph)
                    photos.append(ph)
                except QAError as e:
                    img_note = f"تم تجاهل صورة: {e}"
            if p.media_refs and not photos:
                img_note = img_note or "تعذر تحميل صورة المصدر فاستُخدم القالب النصي"
        targets = photos if (self.cfg.album_mode == "each" and photos) else [photos[0] if photos else None]

        clean = lambda s: strip_unsupported(s, self.cfg.font_path)
        sent_paths = []
        for i, photo in enumerate(targets):
            snap = to_snap(res, photo, p.url, is_update, clean)
            try:
                path = await asyncio.to_thread(self._design, snap, msg_id, i)
            except (RenderError, QAError) as e:
                if photo is not None:
                    # الصورة لا تتسع بشكل سليم: نجرب القالب النصي بدل إرسال تصميم ناقص
                    try:
                        snap.image_path = None
                        path = await asyncio.to_thread(self._design, snap, msg_id, i)
                        img_note = f"استُخدم القالب النصي لأن الصورة لم تجتز الفحص ({e})"
                    except (RenderError, QAError) as e2:
                        self._design_failed(msg_id, base, p, e2)
                        return
                else:
                    self._design_failed(msg_id, base, p, e)
                    return
            caption = self.caption(snap, res, method, old_headline, img_note, len(photos))
            if self.bot:
                try:
                    await asyncio.to_thread(self.bot.send_png, path, caption)
                except Exception as e:
                    self.db.upsert_post(msg_id, status="failed", reason=f"إرسال: {e}", png_path=str(path), **base)
                    self.alert(f"التصميم جاهز لكن فشل إرساله\n{e}\n{p.url}")
                    return
            sent_paths.append(str(path))
        self.db.upsert_post(msg_id, status="sent", reason=None, template=res.template, headline=res.headline,
                            body=res.body, update_of=ref[0] if is_update else None,
                            png_path=";".join(sent_paths), sent_at=now_utc().isoformat(), **base)
        log.info("أُرسل %s: %s", msg_id, res.headline)

    def _design(self, snap, msg_id: int, idx: int) -> Path:
        check_snap_text(snap, self.cfg.font_path)
        img, lay = self.renderer.render(snap)
        problems = check_render(img, lay, snap)
        if problems:
            raise QAError("؛ ".join(problems))
        stamp = datetime.now(ZoneInfo(self.cfg.timezone)).strftime("%Y%m%d_%H%M")
        return save_png(img, self.cfg.out_dir / f"daryo_{stamp}_{msg_id}_{idx}.png")

    def _design_failed(self, msg_id, base, p, e):
        self.db.upsert_post(msg_id, status="failed", reason=f"تصميم: {e}", **base)
        self.alert(f"فشل تصميم خبر ولم تُرسل أي صورة\nالسبب: {e}\n{p.url}")

    def caption(self, snap, res, method, old_headline, img_note, n_photos) -> str:
        tags = [TEMPLATE_AR.get(snap.template, "")]
        if snap.is_update:
            tags.insert(0, "🔄 تحديث")
        if snap.is_rumor:
            tags.append("غير رسمي")
        lines = [" | ".join(t for t in tags if t), "", res.telegram_caption or snap.headline, ""]
        if snap.is_update and old_headline:
            lines.append(f"الخبر السابق: {old_headline}")
        if n_photos > 1 and self.cfg.album_mode == "first":
            lines.append(f"الألبوم فيه {n_photos} صور واستُخدمت الأولى")
        if img_note:
            lines.append(img_note)
        lines.append(f"المصدر: {snap.source_url}")
        lines.append(f"التحرير: {'Claude' if method == 'llm' else 'محرر محلي'} | للنشر اليدوي في {self.cfg.snap_handle}")
        return "\n".join(lines)

    async def send_test(self):
        from .samples import SAMPLES
        snap = SAMPLES["1_breaking"]
        try:
            path = await asyncio.to_thread(self._design, snap, 0, 0)
            if self.bot:
                await asyncio.to_thread(self.bot.send_png, path, "🧪 سنابة تجريبية (خبر وهمي للاختبار فقط)")
        except Exception as e:
            self.alert(f"فشل الاختبار: {e}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    svc = Service(cfg)
    asyncio.run(svc.run())


if __name__ == "__main__":
    main()

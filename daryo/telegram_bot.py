"""بوت التسليم والتحكم: يرسل PNG كملف غير مضغوط ويستقبل أوامر المالك فقط"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import requests

log = logging.getLogger("daryo.bot")


class BotError(Exception):
    pass


class Bot:
    def __init__(self, token: str, owner_chat_id: int):
        if not token or not owner_chat_id:
            raise BotError("BOT_TOKEN و OWNER_CHAT_ID مطلوبان")
        self.base = f"https://api.telegram.org/bot{token}"
        self.owner = owner_chat_id
        self.groups: list[int] = []      # مجموعات تصلها التصاميم أيضًا (يضيفها المالك)
        self.group_handler = None
        self.s = requests.Session()

    def _call(self, method: str, timeout: int = 60, **kw):
        last = None
        for attempt in range(4):
            try:
                r = self.s.post(f"{self.base}/{method}", timeout=timeout, **kw)
                data = r.json()
                if data.get("ok"):
                    return data["result"]
                if r.status_code == 429:
                    time.sleep(int(data.get("parameters", {}).get("retry_after", 5)) + 1)
                    continue
                raise BotError(f"{method}: {data.get('description')}")
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise BotError(f"{method} فشل بعد عدة محاولات: {last}")

    def send_text(self, text: str, chat_id: int | None = None):
        return self._call("sendMessage", data={"chat_id": chat_id or self.owner, "text": text[:4000],
                                               "disable_web_page_preview": True})

    def _to_groups(self, send):
        """نسخة لكل مجموعة؛ فشل مجموعة لا يوقف الإرسال للمالك"""
        for g in list(self.groups):
            try:
                send(g)
            except Exception as e:
                log.warning("تعذر الإرسال للمجموعة %s: %s", g, e)
                self.alert(f"تعذر إرسال التصميم للمجموعة {g}: {e}")

    def send_png(self, path: Path, caption: str = ""):
        """sendDocument يحافظ على الملف كما هو دون ضغط تيليجرام"""
        def send(chat):
            data = {"chat_id": chat, "disable_content_type_detection": True}
            if caption:
                data["caption"] = caption[:1024]
            with open(path, "rb") as f:
                return self._call("sendDocument", timeout=120, data=data,
                                  files={"document": (Path(path).name, f, "image/png")})
        res = send(self.owner)
        self._to_groups(send)
        return res

    def send_video(self, path: Path):
        """سنابة الفيديو جاهزة للحفظ مباشرة بدون أي نص"""
        def send(chat):
            with open(path, "rb") as f:
                return self._call("sendVideo", timeout=300,
                                  data={"chat_id": chat, "width": 1080, "height": 1920,
                                        "supports_streaming": True},
                                  files={"video": (Path(path).name, f, "video/mp4")})
        res = send(self.owner)
        self._to_groups(send)
        return res

    def copy_originals(self, from_chat: str, msg_ids: list[int]):
        """ينسخ رسائل المصدر نفسها (الصور والفيديو الأصلية) إلى محادثتك بدون اسم القناة"""
        import json
        return self._call("copyMessages", data={"chat_id": self.owner, "from_chat_id": from_chat,
                                                "message_ids": json.dumps(sorted(msg_ids)[:10]),
                                                "remove_caption": True})

    def send_photo_files(self, paths: list[str]):
        """بديل: يرفع الصور الأصلية المحمّلة كألبوم"""
        import json
        paths = paths[:10]
        if len(paths) == 1:
            with open(paths[0], "rb") as f:
                return self._call("sendPhoto", timeout=120, data={"chat_id": self.owner},
                                  files={"photo": f})
        files = {f"p{i}": open(p, "rb") for i, p in enumerate(paths)}
        try:
            media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(paths))]
            return self._call("sendMediaGroup", timeout=120,
                              data={"chat_id": self.owner, "media": json.dumps(media)}, files=files)
        finally:
            for f in files.values():
                f.close()

    def get_file_bytes(self, file_id: str) -> bytes:
        info = self._call("getFile", data={"file_id": file_id})
        token = self.base.rsplit("/bot", 1)[1]
        r = self.s.get(f"https://api.telegram.org/file/bot{token}/{info['file_path']}", timeout=60)
        r.raise_for_status()
        return r.content

    def alert(self, text: str):
        try:
            self.send_text(f"⚠️ تنبيه نظام داريو النصر\n{text}")
        except Exception as e:  # لا نوقف الخدمة بسبب فشل التنبيه
            log.error("تعذر إرسال التنبيه: %s", e)

    def _membership(self, mem):
        """إضافة البوت لمجموعة من المالك = تفعيل إرسال التصاميم لها، وإخراجه = إيقافها"""
        chat = mem.get("chat") or {}
        if chat.get("type") not in ("group", "supergroup") or not self.group_handler:
            return
        status = (mem.get("new_chat_member") or {}).get("status")
        by = (mem.get("from") or {}).get("id")
        if status in ("member", "administrator"):
            if by == self.owner:
                self.group_handler(chat["id"], chat.get("title", ""), True)
            else:
                log.warning("أُضيف البوت لمجموعة من غير المالك: %s", chat.get("id"))
        elif status in ("left", "kicked"):
            self.group_handler(chat["id"], chat.get("title", ""), False)

    # ---------- استقبال الأوامر ----------
    def start_command_loop(self, handler, channel_handler=None):
        self.channel_handler = channel_handler
        t = threading.Thread(target=self._loop, args=(handler,), daemon=True, name="bot-updates")
        t.start()
        return t

    def _loop(self, handler):
        offset = None
        while True:
            try:
                params = {"timeout": 50,
                          "allowed_updates": '["message","channel_post","edited_channel_post","my_chat_member"]'}
                if offset:
                    params["offset"] = offset
                r = self.s.get(f"{self.base}/getUpdates", params=params, timeout=65)
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    ch = upd.get("channel_post") or upd.get("edited_channel_post")
                    if ch is not None:
                        if getattr(self, "channel_handler", None):
                            try:
                                self.channel_handler(ch, "edited_channel_post" in upd)
                            except Exception as e:
                                log.warning("تعذر قراءة منشور القناة: %s", e)
                        continue
                    mem = upd.get("my_chat_member")
                    if mem is not None:
                        self._membership(mem)
                        continue
                    msg = upd.get("message") or {}
                    chat = (msg.get("chat") or {}).get("id")
                    text = (msg.get("text") or "").strip()
                    if not text.startswith("/"):
                        continue
                    sender = (msg.get("from") or {}).get("id")
                    if (chat != self.owner and sender == self.owner and self.group_handler
                            and text.split("@")[0].split()[0].lower() == "/group"):
                        # بديل يدوي: المالك يكتب /group داخل المجموعة
                        self.group_handler(chat, (msg.get("chat") or {}).get("title", ""), True)
                        continue
                    if chat != self.owner:
                        log.warning("أمر من محادثة غير مصرح بها: %s", chat)
                        continue
                    try:
                        reply = handler(text)
                    except Exception as e:
                        reply = f"خطأ في تنفيذ الأمر: {e}"
                    if reply:
                        self.send_text(reply)
            except Exception as e:
                log.warning("انقطاع في استقبال الأوامر: %s", e)
                time.sleep(5)

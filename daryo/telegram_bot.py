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

    def send_png(self, path: Path, caption: str):
        """sendDocument يحافظ على الملف كما هو دون ضغط تيليجرام"""
        with open(path, "rb") as f:
            return self._call("sendDocument", timeout=120,
                              data={"chat_id": self.owner, "caption": caption[:1024],
                                    "disable_content_type_detection": True},
                              files={"document": (Path(path).name, f, "image/png")})

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
                          "allowed_updates": '["message","channel_post","edited_channel_post"]'}
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
                    msg = upd.get("message") or {}
                    chat = (msg.get("chat") or {}).get("id")
                    text = (msg.get("text") or "").strip()
                    if not text.startswith("/"):
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

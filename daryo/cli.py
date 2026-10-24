"""أدوات سطر الأوامر

python -m daryo.cli login        تسجيل حساب تيليجرام للقراءة (مرة واحدة)
python -m daryo.cli check        فحص الإعدادات والاتصال
python -m daryo.cli chatid       معرفة رقم محادثتك الخاصة مع البوت
python -m daryo.cli samples      توليد نماذج القوالب في مجلد samples
python -m daryo.cli on|off|status|hours 08:00-02:00
python -m daryo.cli health       فحص صحة الخدمة (لـ Docker)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, Config
from .db import DB


async def _login(cfg: Config):
    from telethon import TelegramClient
    if not (cfg.tg_api_id and cfg.tg_api_hash):
        sys.exit("ضع TG_API_ID و TG_API_HASH في ملف .env أولًا (من my.telegram.org)")
    Path(cfg.tg_session).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(cfg.tg_session, cfg.tg_api_id, cfg.tg_api_hash,
                            device_model="DaryoAlnasr", app_version="1.0")
    await client.start()  # يطلب رقم الجوال ورمز التحقق وكلمة مرور التحقق بخطوتين إن وجدت
    me = await client.get_me()
    ent = await client.get_entity(cfg.source_channel)
    msgs = await client.get_messages(ent, limit=1)
    print(f"تم تسجيل الدخول باسم {me.first_name}. آخر منشور في {cfg.source_channel}: {msgs[0].id if msgs else '-'}")
    await client.disconnect()


async def _check(cfg: Config):
    from .qa import verify_font
    from .sources import make_source
    from .telegram_bot import Bot
    ok = True
    try:
        verify_font(cfg.font_path)
        print("✓ الخط Arial Bold المعتمد")
    except Exception as e:
        ok = False
        print("✗", e)
    print(f"• الشعار: {'موجود' if cfg.logo_path.exists() else 'غير موجود، سيُستخدم شعار نصي مؤقت'}")
    src = make_source(cfg)
    try:
        await src.start()
        posts = await src.fetch_latest()
        print(f"✓ القراءة عبر {src.name}: {len(posts)} منشور، آخرها {max((p.msg_id for p in posts), default='-')}")
        await src.stop()
    except Exception as e:
        ok = False
        print(f"✗ القراءة عبر {src.name}: {e}")
    if cfg.bot_token and cfg.owner_chat_id:
        try:
            Bot(cfg.bot_token, cfg.owner_chat_id).send_text("✅ اختبار اتصال نظام داريو النصر")
            print("✓ البوت أرسل رسالة اختبار لمحادثتك")
        except Exception as e:
            ok = False
            print("✗ البوت:", e)
    else:
        print("✗ BOT_TOKEN أو OWNER_CHAT_ID غير مضبوط")
        ok = False
    if cfg.anthropic_api_key:
        try:
            from .editor import Editor
            res, method = Editor(cfg).edit("عاجل: النصر يعلن رسميًا تجديد عقد اللاعب حتى 2027", [])
            print(f"✓ التحرير بـ {method}: {res.headline}")
        except Exception as e:
            print("✗ Claude:", e)
    else:
        print("• لا يوجد ANTHROPIC_API_KEY: سيعمل المحرر المحلي (أقل جودة في الصياغة وكشف التكرار بالمعنى)")
    sys.exit(0 if ok else 1)


def _chatid(cfg: Config):
    import requests
    if not cfg.bot_token:
        sys.exit("ضع BOT_TOKEN أولًا ثم أرسل /start لبوتك في تيليجرام")
    r = requests.get(f"https://api.telegram.org/bot{cfg.bot_token}/getUpdates", timeout=30).json()
    seen = {}
    for u in r.get("result", []):
        chat = (u.get("message") or {}).get("chat")
        if chat:
            seen[chat["id"]] = chat.get("first_name") or chat.get("title")
    if not seen:
        print("لا توجد رسائل. أرسل /start لبوتك ثم أعد المحاولة")
    for cid, name in seen.items():
        print(f"OWNER_CHAT_ID={cid}   ({name})")


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    cfg = Config()
    cfg.ensure_dirs()
    cmd = argv[0]
    if cmd == "login":
        asyncio.run(_login(cfg))
    elif cmd == "check":
        asyncio.run(_check(cfg))
    elif cmd == "chatid":
        _chatid(cfg)
    elif cmd == "samples":
        from .samples import build_samples
        out = Path(argv[1]) if len(argv) > 1 else ROOT / "samples"
        for p in build_samples(cfg, out):
            print(p)
    elif cmd in ("on", "off"):
        DB(cfg.db_path).set("enabled", cmd == "on")
        print("تم التشغيل" if cmd == "on" else "تم الإيقاف")
    elif cmd == "hours":
        from .schedule import parse_hours
        spec = argv[1] if len(argv) > 1 else ""
        parse_hours(spec)
        DB(cfg.db_path).set("hours", "" if spec in ("24", "all") else spec)
        print("ساعات التشغيل:", spec or "طوال اليوم")
    elif cmd == "status":
        db = DB(cfg.db_path)
        print("enabled:", db.get("enabled"), "| hours:", db.get("hours") or "24h",
              "| last_poll:", db.get("last_poll"), "| 24h:", db.stats_today())
    elif cmd == "health":
        hb = DB(cfg.db_path).get("heartbeat")
        if not hb or datetime.fromisoformat(hb) < datetime.now(timezone.utc) - timedelta(minutes=10):
            sys.exit(1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

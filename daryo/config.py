"""إعدادات النظام: تُقرأ من متغيرات البيئة أو ملف .env"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    v = _env(name, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "on")


@dataclass
class Config:
    # هوية الحساب
    account_name: str = field(default_factory=lambda: _env("ACCOUNT_NAME", "داريو النصر"))
    snap_handle: str = field(default_factory=lambda: _env("SNAP_HANDLE", "N9rfc1"))

    # مصدر الأخبار
    source_channel: str = field(default_factory=lambda: _env("SOURCE_CHANNEL", "n9rfc"))
    # bot = البوت مشرف في القناة (الأفضل لمالك القناة) | telethon = حساب تيليجرام عبر MTProto
    # web = صفحة المعاينة العامة t.me/s | auto
    source_mode: str = field(default_factory=lambda: _env("SOURCE_MODE", "auto"))
    tg_api_id: int = field(default_factory=lambda: int(_env("TG_API_ID", "0") or 0))
    tg_api_hash: str = field(default_factory=lambda: _env("TG_API_HASH"))
    tg_session: str = field(default_factory=lambda: _env("TG_SESSION", str(ROOT / "data" / "daryo_user")))

    # بوت التسليم
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN"))
    owner_chat_id: int = field(default_factory=lambda: int(_env("OWNER_CHAT_ID", "0") or 0))

    # الذكاء الاصطناعي للتحرير وكشف التكرار بالمعنى (اختياري لكنه موصى به)
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "claude-opus-5-5"))
    llm_effort: str = field(default_factory=lambda: _env("LLM_EFFORT", "medium"))

    # الجدولة
    poll_min_sec: int = field(default_factory=lambda: int(_env("POLL_MIN_SEC", "120")))
    poll_max_sec: int = field(default_factory=lambda: int(_env("POLL_MAX_SEC", "180")))
    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Asia/Riyadh"))
    # ساعات التشغيل الافتراضية، تتغير لاحقًا من البوت بـ /hours. فارغ = 24 ساعة
    default_hours: str = field(default_factory=lambda: _env("ACTIVE_HOURS", ""))
    # الأخبار الأقدم من هذا (بالدقائق) عند العودة من الإيقاف تُسجّل ولا تُصمم
    catchup_max_age_min: int = field(default_factory=lambda: int(_env("CATCHUP_MAX_AGE_MIN", "60")))
    # عند أول تشغيل: كم منشورًا أخيرًا يُعالج (0 = لا شيء، فقط يبدأ المراقبة من الآن)
    initial_backfill: int = field(default_factory=lambda: int(_env("INITIAL_BACKFILL", "0")))
    # first = سنابة واحدة للألبوم بأول صورة | each = سنابة لكل صورة
    album_mode: str = field(default_factory=lambda: _env("ALBUM_MODE", "first"))
    design_style: str = field(default_factory=lambda: _env("DESIGN_STYLE", "clean"))   # clean | cinema | brand
    use_source_images: bool = field(default_factory=lambda: _bool("USE_SOURCE_IMAGES", True))
    dedup_window_hours: int = field(default_factory=lambda: int(_env("DEDUP_WINDOW_HOURS", "72")))
    alert_after_failures: int = field(default_factory=lambda: int(_env("ALERT_AFTER_FAILURES", "3")))

    # المسارات
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT / "data"))))
    font_path: Path = field(default_factory=lambda: Path(_env("FONT_PATH", str(ROOT / "assets" / "fonts" / "arial-bold.ttf"))))
    logo_path: Path = field(default_factory=lambda: Path(_env("LOGO_PATH", str(ROOT / "assets" / "logo.png"))))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "daryo.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def out_dir(self) -> Path:
        return self.data_dir / "snaps"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.media_dir, self.out_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_source_mode(self) -> str:
        if self.source_mode in ("bot", "telethon", "web"):
            return self.source_mode
        session_file = Path(self.tg_session + ".session")
        if self.tg_api_id and self.tg_api_hash and session_file.exists():
            return "telethon"
        return "web"


# بصمة ملف Arial Bold المعتمد. أي ملف آخر يُرفض ولا يُصمم به
APPROVED_FONT_SHA256 = "0d5d1482307b800ec9c49f77cb6648666f88bcf2d0ce957f52af4e0fc3c6fcf8"

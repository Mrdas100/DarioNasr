from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

TEMPLATES = ("breaking", "statement", "stats", "transfer", "general")
TEMPLATE_AR = {
    "breaking": "عاجل",
    "statement": "تصريح",
    "stats": "بالأرقام",
    "transfer": "سوق الانتقالات",
    "general": "أخبار النصر",
    "comment": "تعليق",
    "dhikr": "ذكر",
}


@dataclass
class SourcePost:
    """منشور (أو ألبوم) من قناة المصدر"""
    msg_id: int
    date: datetime
    text: str
    photos: list[str] = field(default_factory=list)   # مسارات الصور المحمّلة محليًا
    has_video: bool = False
    grouped_id: int | None = None
    url: str = ""
    is_forward: bool = False
    has_buttons: bool = False
    media_refs: list = field(default_factory=list)   # مراجع الوسائط قبل التحميل (رسائل Telethon أو روابط)
    edited: bool = False
    msg_ids: list[int] = field(default_factory=list)   # كل رسائل الألبوم لإرفاق الوسائط الأصلية


@dataclass
class Snap:
    """محتوى سنابة واحدة بعد التحرير"""
    template: str
    headline: str
    body: str = ""
    kicker: str = ""
    number: str = ""
    number_caption: str = ""
    speaker: str = ""
    quote: str = ""
    transfer_status: str = ""       # official | rumor | ""
    is_rumor: bool = False
    is_update: bool = False
    image_path: str | None = None
    caption: str = ""               # نص الخبر المرافق في تيليجرام
    source_url: str = ""

    def all_text(self) -> list[str]:
        return [s for s in (self.headline, self.body, self.kicker, self.number,
                            self.number_caption, self.speaker, self.quote) if s]

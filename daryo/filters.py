"""استبعاد الإعلانات والمنشورات غير المناسبة قبل التحرير"""
from __future__ import annotations

import re

from .models import SourcePost
from .textutil import normalize_ar, strip_decor

AD_PATTERNS = [
    r"للاعلان", r"للإعلان", r"اعلان مدفوع", r"إعلان مدفوع", r"\bاعلان\b", r"\bإعلان\b",
    r"واتساب", r"واتس اب", r"wa\.me", r"كود خصم", r"كود الخصم", r"خصم \d+", r"(?<!\w)(?:و?ال|و)?متجر",
    r"اشترك الان", r"اشترك الآن", r"سجل الان", r"سجّل الآن", r"رابط التسجيل",
    r"مراهن", r"1xbet", r"melbet", r"كازينو", r"ربح مضمون", r"(?<!\w)(?:و?ال|و)?توصيات", r"(?<!\w)(?:و?ال|و)?تداول",
    # كلمات عامة: بأداة تعريف أو واو فقط حتى لا تطابق "معروضة" و"يتداول"
    r"(?<!\w)(?:و?ال|و)?عروض", r"(?<!\w)(?:و?ال|و)?تخفيضات", r"احجز الان", r"احجز الآن", r"اطلب الان", r"اطلب الآن",
    r"قناتنا الثانية", r"تابعونا على", r"تابعوا حسابنا", r"رابط القناة",
]
# منشورات تفاعلية لا تصلح خبرًا
NON_NEWS = [r"^رايكم", r"^رأيكم", r"^ايش رايكم", r"^توقعاتكم", r"^صوتوا", r"^تصويت",
            r"^صباح الخير", r"^مساء الخير", r"^جمعة مباركة", r"^سؤال"]
OFFENSIVE = [r"\bزق\b", r"\bتف\b", r"حقير", r"كلب", r"وسخ", r"خنزير"]

_AD = re.compile("|".join(AD_PATTERNS), re.I)
_NON = re.compile("|".join(normalize_ar(p.replace("^", "")) for p in NON_NEWS))
_OFF = re.compile("|".join(OFFENSIVE))


def strip_ad_lines(raw: str) -> str:
    """يحذف أسطر الإعلان الملحقة بالمنشور (رابط، واتساب...)"""
    return "\n".join(x for x in raw.splitlines() if not _AD.search(x))


def reject_reason(post: SourcePost) -> str | None:
    from .editor import is_dhikr
    raw = post.text or ""
    if is_dhikr(raw):
        # الأذكار تُنشر بقالبها الخاص حتى لو ألحق بها سطر إعلان (يُحذف عند التحرير)
        return None if len(strip_decor(strip_ad_lines(raw))) >= 8 else "لا يوجد نص كافٍ"
    clean = strip_decor(raw)
    norm = normalize_ar(raw)
    if _AD.search(raw):
        return "إعلان"
    if post.has_buttons and len(clean) < 200:
        return "منشور بأزرار (غالبًا إعلان)"
    if _OFF.search(clean):
        return "ألفاظ غير مناسبة"
    if norm and _NON.match(norm):
        return "منشور تفاعلي وليس خبرًا"
    if len(clean) < 12 and not (post.media_refs and len(clean.split()) >= 2):
        # بلا نص كافٍ لا يُكتب خبر دون اختلاق، إلا منشور صور بوصف قصير مثل "تدريب جديد"
        return "لا يوجد نص كافٍ لصياغة خبر"
    if clean.endswith(("؟", "?")) and len(clean) < 70:
        return "سؤال للجمهور وليس خبرًا"
    return None

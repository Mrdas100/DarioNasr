"""استبعاد الإعلانات والمنشورات غير المناسبة قبل التحرير"""
from __future__ import annotations

import re

from .models import SourcePost
from .textutil import normalize_ar, strip_decor

AD_PATTERNS = [
    r"للاعلان", r"للإعلان", r"اعلان مدفوع", r"إعلان مدفوع", r"\bاعلان\b", r"\bإعلان\b",
    r"واتساب", r"واتس اب", r"wa\.me", r"كود خصم", r"كود الخصم", r"خصم \d+", r"متجر",
    r"اشترك الان", r"اشترك الآن", r"سجل الان", r"سجّل الآن", r"رابط التسجيل",
    r"مراهن", r"1xbet", r"melbet", r"كازينو", r"ربح مضمون", r"توصيات", r"تداول",
    r"عروض", r"تخفيضات", r"احجز الان", r"احجز الآن", r"اطلب الان", r"اطلب الآن",
    r"قناتنا الثانية", r"تابعونا على", r"تابعوا حسابنا", r"رابط القناة",
]
# منشورات تفاعلية لا تصلح خبرًا
NON_NEWS = [r"^رايكم", r"^رأيكم", r"^ايش رايكم", r"^توقعاتكم", r"^صوتوا", r"^تصويت",
            r"^صباح الخير", r"^مساء الخير", r"^جمعة مباركة", r"^سؤال"]
OFFENSIVE = [r"\bزق\b", r"\bتف\b", r"حقير", r"كلب", r"وسخ", r"خنزير"]

_AD = re.compile("|".join(AD_PATTERNS), re.I)
_NON = re.compile("|".join(normalize_ar(p.replace("^", "")) for p in NON_NEWS))
_OFF = re.compile("|".join(OFFENSIVE))


def reject_reason(post: SourcePost) -> str | None:
    raw = post.text or ""
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
    if len(clean) < 12:
        # صورة بلا نص كافٍ: لا يمكن كتابة خبر دقيق عنها دون اختلاق
        return "لا يوجد نص كافٍ لصياغة خبر"
    if clean.endswith(("؟", "?")) and len(clean) < 70:
        return "سؤال للجمهور وليس خبرًا"
    return None

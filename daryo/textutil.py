"""أدوات نصوص عربية: تنظيف وتطبيع واستخراج أرقام"""
from __future__ import annotations

import re
import unicodedata

AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
TATWEEL = "ـ"
URL_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+)", re.I)
MENTION_RE = re.compile(r"@\w+")
HASHTAG_RE = re.compile(r"#(\S+)")
# الرموز التعبيرية والأشكال الزخرفية
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U000020E3"
    "\U0001F1E6-\U0001F1FF⌀-⏿■-◿✀-➿]+"
)
AR_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
NUM_RE = re.compile(r"\d+(?:[.,٫]\d+)?")


def strip_decor(text: str) -> str:
    """يحذف الروابط والمعرفات والإيموجي ويحوّل الوسوم إلى كلمات"""
    t = URL_RE.sub(" ", text or "")
    t = MENTION_RE.sub(" ", t)
    t = HASHTAG_RE.sub(lambda m: m.group(1).replace("_", " "), t)
    t = EMOJI_RE.sub(" ", t)
    t = t.replace(TATWEEL, "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def normalize_ar(text: str) -> str:
    """تطبيع للمقارنة فقط (ليس للعرض)"""
    t = strip_decor(text).lower()
    t = unicodedata.normalize("NFKC", t)
    t = AR_DIACRITICS.sub("", t)
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = t.translate(AR_INDIC)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def numbers(text: str) -> set[str]:
    t = (text or "").translate(AR_INDIC).replace("٫", ".").replace(",", ".")
    return {n.lstrip("0") or "0" for n in NUM_RE.findall(t)}


def tidy_punct(text: str) -> str:
    """يزيل الفواصل والنقاط غير الضرورية في العناوين"""
    t = re.sub(r"[.…]{2,}", " ", text)
    t = re.sub(r"\s*[،,]\s*$", "", t)
    t = re.sub(r"[.!؟?]+$", "", t.strip())
    t = re.sub(r"\s+([،,:])", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip(" -–—|:")


def word_count(text: str) -> int:
    return len(text.split())


def clip_words(text: str, n: int) -> str:
    w = text.split()
    return " ".join(w[:n])

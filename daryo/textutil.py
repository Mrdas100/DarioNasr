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
BIDI_RE = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c]")
NUM_RE = re.compile(r"\d+(?:[.,٫]\d+)?")


def unescape_html(text: str) -> str:
    """رموز HTML من المصدر مثل &amp;amp; تُعاد لأصلها (حتى المرمّزة أكثر من مرة)"""
    import html
    for _ in range(4):
        new = html.unescape(text)
        if new == text:
            break
        text = new
    return text


def strip_decor(text: str, keep_emoji: bool = False) -> str:
    """يحذف الروابط والمعرفات والإيموجي ويحوّل الوسوم إلى كلمات.
    keep_emoji: يُبقي الإيموجي داخل الجملة لعرضه بصور أبل (وتُحذف زخارف بداية السطر)"""
    t = URL_RE.sub(" ", text or "")
    t = MENTION_RE.sub(" ", t)
    t = HASHTAG_RE.sub(lambda m: m.group(1).replace("_", " "), t)
    if keep_emoji:
        from .emoji import tidy
        t = tidy(t)
    else:
        t = EMOJI_RE.sub(" ", t)
    t = t.replace(TATWEEL, "")
    t = BIDI_RE.sub("", t)
    # الحروف الممطوطة مثل عاااااجل ← عاجل
    t = re.sub(r"([\u0621-\u064A])\1{2,}", r"\1", t)
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


def message_chunks(text: str, limit: int = 3500) -> list[str]:
    """Split Telegram text on word boundaries, keeping booking URLs intact."""
    chunks, current = [], ""
    for token in re.findall(r"\S+\s*", text):
        if len(token.encode('utf-16-le')) // 2 > limit:
            raise ValueError("كلمة أو رابط أطول من حد رسالة تيليجرام")
        trial = current + token
        if len(trial.encode('utf-16-le')) // 2 > limit:
            chunks.append(current.rstrip())
            current = token
        else:
            current = trial
    if current:
        chunks.append(current.rstrip())
    return chunks

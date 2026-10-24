"""كشف التكرار بالمعنى وتمييز الأخبار المحدّثة

طبقتان:
1) تشابه معجمي سريع بعد تطبيع العربية (مقاطع حروف ثلاثية + كلمات)
2) حكم دلالي من نموذج اللغة للحالات المتقاربة (إن توفر مفتاح API)
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .textutil import normalize_ar, numbers

STOP = set("في من على الى عن مع ان او ثم قد لقد هذا هذه ذلك تلك التي الذي بعد قبل عند كل حتى منذ و يا ما لا لم لن هو هي هم".split())
# كلمات تدل على تطور الخبر نفسه (عاجل والآن ليست تحديثًا)
UPDATE_WORDS = ["رسميا", "رسمي", "تحديث", "محدث", "تأكيد", "تاكيد", "اكتمل", "اكتملت", "حسم", "نفي", "ينفي",
                "تراجع", "مستجدات", "نهائي", "بشكل نهائي"]


def _grams(t: str) -> Counter:
    t = f" {t} "
    return Counter(t[i:i + 3] for i in range(len(t) - 2))


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def _tokens(t: str) -> set[str]:
    out = set()
    for w in t.split():
        if w in STOP or len(w) < 2:
            continue
        w = re.sub(r"^(وال|بال|كال|فال|لل|ال|و)", "", w) or w
        out.add(w)
    return out


def similarity(a_norm: str, b_norm: str) -> float:
    c = _cos(_grams(a_norm), _grams(b_norm))
    ta, tb = _tokens(a_norm), _tokens(b_norm)
    j = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return 0.55 * c + 0.45 * j


@dataclass
class DedupResult:
    relation: str            # new | duplicate | update
    ref_id: int | None = None
    ref_msg_id: int | None = None
    score: float = 0.0
    reason: str = ""


def candidates(norm: str, history, top: int = 4):
    scored = []
    for row in history:
        if not row["norm_text"]:
            continue
        scored.append((similarity(norm, row["norm_text"]), row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top]


def heuristic(raw: str, norm: str, history) -> tuple[DedupResult, list]:
    cands = candidates(norm, history)
    if not cands or cands[0][0] < 0.33:
        return DedupResult("new", score=cands[0][0] if cands else 0.0), cands
    score, row = cands[0]
    new_nums, old_nums = numbers(raw), numbers(row["raw_text"] or "")
    has_update_word = any(w in norm for w in UPDATE_WORDS) and not any(w in row["norm_text"] for w in UPDATE_WORDS)
    if score >= 0.62:
        if (new_nums - old_nums) or has_update_word:
            return DedupResult("update", row["id"], row["msg_id"], score, "تفاصيل أو أرقام جديدة"), cands
        return DedupResult("duplicate", row["id"], row["msg_id"], score, "نفس الخبر بصياغة أخرى"), cands
    if score >= 0.5 and has_update_word:
        return DedupResult("update", row["id"], row["msg_id"], score, "تطور لخبر سابق"), cands
    # منطقة رمادية: يحسمها نموذج اللغة إن توفر
    return DedupResult("new", score=score, reason="غير محسوم"), cands

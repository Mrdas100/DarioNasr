"""التحرير الإخباري: اختصار وإعادة صياغة واختيار القالب

يستخدم Claude عند توفر ANTHROPIC_API_KEY، وإلا يعمل محرر قواعد محلي محافظ
يقتبس من نص المصدر حرفيًا دون إضافة أي معلومة.
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from .models import Snap
from .textutil import clip_words, normalize_ar, numbers, strip_decor, tidy_punct

log = logging.getLogger("daryo.editor")

RUMOR_SIGNS = ["مصادر", "مصدر", "تقارير", "تقرير", "حسب", "وفقا", "وفق", "انباء", "أنباء", "صحيفه", "صحيفة",
               "يقترب", "قريب من", "مفاوضات", "يدرس", "مهتم", "اهتمام", "عرض", "شائعات", "تسريب", "مرشح",
               "قد ", "ربما", "يتوقع", "متوقع", "علمت", "خاص"]
OFFICIAL_SIGNS = ["رسميا", "رسمي", "يعلن", "اعلن", "أعلن", "بيان", "النادي يعلن", "المركز الاعلامي"]
TRANSFER_SIGNS = ["انتقال", "صفقه", "صفقة", "توقيع", "يوقع", "عقد", "تجديد", "اعاره", "إعارة", "التعاقد",
                  "الميركاتو", "يرحل", "رحيل", "فسخ", "الانضمام", "ينضم", "مفاوضات", "شرط جزائي"]
STATEMENT_SIGNS = ["قال", "صرح", "تصريح", "يقول", "اكد", "أكد", "مؤتمر", "حديث", "في حديثه", ":", "«", '"']
# ما يدل على أن للمنشور مصدرًا (صحيفة، حساب، بيان، تصريح). بدونه يُصنف المنشور "تعليق" لا "خبر"
SOURCE_SIGNS = OFFICIAL_SIGNS + ["عبر", "مصدر", "مصادر", "صحيفه", "صحيفة", "حسب", "وفق", "وفقا", "نقلا", "تقارير",
                                 "تقرير", "موقع", "حساب", "الصحفي", "الاعلامي", "الإعلامي", "قال", "صرح", "تصريح",
                                 "مؤتمر", "في حديثه", "كشف", "افاد", "أفاد", "ذكرت", "ذكر", "اكدت", "أكدت", "عاجل",
                                 "خاص", "رسميًا", "(ig)", "@"]
BREAKING_SIGNS = ["عاجل", "🚨", "‼", "الان", "الآن"]
STATS_SIGNS = ["ارقام", "أرقام", "احصائ", "إحصائ", "هدف", "اهداف", "أهداف", "مباراه", "مباراة", "%", "رقم",
               "صناعه", "صناعة", "سجل", "تمريره", "تمريرة", "دقيقه", "دقيقة"]

PREFIXES = {"و", "ف", "ب", "ل", "ال", "وال", "بال", "فال", "لل", "ولل"}
SOURCE_SIGNATURES = re.compile(r"(منبر\s*النصر|n9rfc|قناة\s*منبر\s*النصر)", re.I)

SYSTEM_PROMPT = """أنت محرر أخبار رياضية سعودي لحساب "داريو النصر" على سناب شات (المعرف N9rfc1).
تستقبل منشورًا من قناة منبر النصر في تيليجرام وتحوّله إلى محتوى سنابة واحدة.

قواعد صارمة:
- اختصر دون تغيير المعنى. لا تضف أي معلومة غير موجودة في النص الأصلي إطلاقًا.
- حافظ على الأرقام والأسماء كما وردت حرفيًا. لا تحسب أرقامًا جديدة.
- لا تحوّل التسريبات أو أخبار المصادر والتقارير والمفاوضات إلى أخبار رسمية. إن كان الخبر غير مؤكد فاجعل is_rumor=true ولا تكتب "رسميًا".
- لا تستخدم kicker "رسميًا" إلا إذا ذكر النص الأصلي أن الأمر رسمي أو صدر في بيان.
- أسلوب سعودي قوي وسريع القراءة. أبرز أهم معلومة في العنوان.
- العنوان من 4 إلى 9 كلمات. النص الفرعي اختياري حتى 16 كلمة.
- تجنب الفواصل والنقاط غير الضرورية ولا تضع نقطة في آخر العنوان. لا إيموجي ولا وسوم ولا روابط.
- لا تذكر اسم قناة المصدر في التصميم.
- اختر القالب: breaking للعاجل المهم، statement للتصريحات (speaker = صاحب التصريح، quote = جوهر كلامه بنصه أو باختصار أمين)، stats للأرقام والإحصائيات (number = الرقم الأبرز كما ورد، number_caption = ماذا يعني)، transfer للانتقالات والعقود، general لغير ذلك.
- publishable=false للإعلانات أو المنشورات التفاعلية أو الأسئلة للجمهور أو النكت أو ما لا يحمل خبرًا، أو إذا لم يكن في النص معلومة كافية.
- telegram_caption: الخبر مختصرًا في سطرين بنفس القواعد.
- علاقة الخبر بالأخبار السابقة المرفقة: duplicate إذا كان نفس الخبر بصياغة أخرى دون جديد، update إذا كان نفس الموضوع مع معلومة جديدة أو تغير في الحالة (مثل تأكيد رسمي أو رقم جديد أو نفي)، new إذا كان خبرًا مختلفًا. related_index رقم الخبر السابق المقصود أو -1.
"""


class EditResult(BaseModel):
    publishable: bool
    skip_reason: str = ""
    template: Literal["breaking", "statement", "stats", "transfer", "general", "comment", "dhikr"]
    headline: str
    body: str = ""
    kicker: str = Field("", description="كلمة أو كلمتان مثل الآن أو رسميًا، أو فارغ")
    number: str = ""
    number_caption: str = ""
    speaker: str = ""
    quote: str = ""
    is_rumor: bool
    transfer_status: Literal["official", "rumor", "none"] = "none"
    relation: Literal["new", "duplicate", "update"] = "new"
    related_index: int = -1
    telegram_caption: str = ""


class EditorError(Exception):
    pass


def _has_any(norm: str, signs) -> bool:
    words = norm.split()
    for s in signs:
        n = normalize_ar(s)
        if not n:
            continue
        if len(n) <= 4 and " " not in n:
            # الكلمات القصيرة تُطابق ككلمة كاملة: "قد" لا تطابق "قدمه" و"عرض" لا تطابق "معرض"
            if any(w == n or (w.endswith(n) and w[:-len(n)] in PREFIXES) for w in words):
                return True
        elif n in norm:
            return True
    return False


# أذكار وأحاديث ومنشورات الجمعة: لها قالب خاص وتُنقل بنصها كما هو
DHIKR_SIGNS = ["صلى الله عليه وسلم", "ﷺ", "اللهم", "سبحان الله", "استغفر الله", "أستغفر الله", "قال تعالى",
               "قال الله تعالى", "لا إله إلا الله", "لا اله الا الله", "الصلاة على النبي", "الصلاة علي",
               "سورة الكهف", "جمعة مباركة", "جمعه مباركه", "الحمد لله رب", "لا حول ولا قوة", "أذكار", "اذكار",
               "قال رسول الله", "قال النبي"]


def is_dhikr(raw: str) -> bool:
    if "ﷺ" in raw:
        return True
    norm = normalize_ar(raw)
    return any(normalize_ar(x) in norm for x in DHIKR_SIGNS if x != "ﷺ")


def dhikr_result(raw: str) -> "EditResult":
    """النص كما ورد بلا قص ولا صياغة (ما عدا تنظيف الزخرفة والوسوم)"""
    from .filters import strip_ad_lines
    lines = [x for x in strip_ad_lines(raw).splitlines() if not re.fullmatch(r"\W*(#\S+\s*)+", x.strip())]
    lines = [x for x in (strip_decor(x, keep_emoji=True).strip() for x in lines) if x]
    # "قال النبي ﷺ" في سطر مستقل يتبعه نص الحديث
    lines = [x + ":" if x.startswith("قال") and i < len(lines) - 1 and not x.endswith(":") else x
             for i, x in enumerate(lines)]
    text = " ".join(lines).replace("ﷺ", "صلى الله عليه وسلم")
    text = re.sub(r"#(\S+)", lambda m: m.group(1).replace("_", " "), text)
    text = tidy_punct(clip_words(text, 70))
    return EditResult(publishable=bool(text), skip_reason="" if text else "لا يوجد نص", template="dhikr",
                      headline=text, is_rumor=False, telegram_caption=text)


def has_source(raw: str) -> bool:
    norm = normalize_ar(raw)
    return "@" in raw or "(IG)" in raw.upper() or _has_any(norm, SOURCE_SIGNS)


def as_comment(res: "EditResult", raw: str) -> "EditResult":
    """منشور عام بلا مصدر يُعرض «تعليق» بدل «خبر»"""
    if res.template == "general" and not has_source(raw):
        return res.model_copy(update={"template": "comment"})
    return res


def classify(raw: str) -> str:
    norm = normalize_ar(raw)
    if _has_any(norm, TRANSFER_SIGNS):
        return "transfer"
    if any(s in raw for s in ("🚨", "‼")) or "عاجل" in norm:
        return "breaking"
    if re.search(r"^[^\n:]{3,40}:", strip_decor(raw)) or _has_any(norm, ["صرح", "تصريح", "في حديثه", "مؤتمر"]):
        return "statement"
    nums = numbers(raw)
    if len(nums) >= 2 and _has_any(norm, STATS_SIGNS):
        return "stats"
    return "general"


def is_rumor_text(raw: str) -> bool:
    norm = normalize_ar(raw)
    return _has_any(norm, RUMOR_SIGNS) and not _has_any(norm, ["رسميا", "بيان رسمي", "النادي يعلن"])


MEDIUM_BREAKS = {"بسبب", "بعد", "قبل", "لمدة", "حتى", "خلال", "رغم", "إثر", "اثر", "مقابل"}
WEAK_BREAKS = {"في", "عن", "مع", "عبر", "وسط", "على"}


def _natural_cut(words: list[str]) -> int:
    """موضع قطع العنوان عند حرف عطف أو سبب بدل منتصف العبارة"""
    found = {3: None, 2: None, 1: None}
    for i in range(5, min(11, len(words))):
        w = words[i]
        if w.startswith("و") and w[1:3] == "ال" and len(w) > 4:
            found[3] = found[3] or i          # أول عطف
        elif w in MEDIUM_BREAKS or (w.startswith("و") and len(w) >= 3 and found[2] is None):
            found[2] = found[2] or i
        elif w in WEAK_BREAKS:
            found[1] = i
    for level in (3, 2, 1):
        if found[level]:
            return found[level]
    return min(9, len(words))


BODY_MAX = 46


def _body_from(rest: str) -> str:
    """تفاصيل الخبر حرفيًا من المصدر، وإن طالت نقف عند نهاية جملة أو عبارة بدل حذفها"""
    rest = re.sub(r"\s+", " ", rest or "").strip()
    rest = re.sub(r"^و(?=في |هو |هي |كان |قد |ي|ت)", "", rest)   # لا تبدأ التفاصيل بحرف عطف
    rest = re.sub(r"[.…]{2,}", "", rest)
    if not rest:
        return ""
    words = rest.split()
    if len(words) <= BODY_MAX:
        return tidy_punct(rest)
    clipped = " ".join(words[:BODY_MAX])
    cut = max(clipped.rfind(c) for c in (".", "!", "؟", "?", "،", ","))
    if cut >= len(clipped) // 2:
        return tidy_punct(clipped[:cut])
    w = words[:BODY_MAX]
    for i in range(len(w) - 1, len(w) // 2, -1):
        if w[i].startswith("و") and len(w[i]) >= 3:
            return tidy_punct(" ".join(w[:i]))
    return tidy_punct(clipped)


def rule_based(raw: str) -> EditResult:
    """محرر احتياطي محافظ: يقتطع من نص المصدر حرفيًا"""
    # أسطر لا تخص الخبر: وسوم فقط، روابط حجز/متجر، أسطر تنتهي بنقطتين بلا محتوى
    kept = []
    for line in (raw or "").split("\n"):
        bare = re.sub(r"#\S+", "", strip_decor(re.sub(r"#\S+", "", line))).strip(" :.-|!")
        if not bare or re.match(r"^(رابط|للحجز|الحجز|للتذاكر|التذاكر|المتجر|للاشتراك)\b", bare):
            continue
        kept.append(line)  # الوسوم داخل الجملة تبقى كلمات (#النصر_الخلود ← النصر الخلود)
    text = SOURCE_SIGNATURES.sub(" ", strip_decor("\n".join(kept), keep_emoji=True))
    # علامات التنصيص المستقيمة تنكسر في الاتجاه العربي وتُقطع عند تقسيم العنوان
    text = re.sub(r'\s*"\s*', " ", text).replace(" \n", "\n")
    # وسوم بداية الخبر مثل "عاجل — رسمياً:" قد تتكرر
    label = r"^\s*(عاجل|خاص|رسمي[اًً]*|مصادر|مصدر|تقارير)\s*[:\-|—–]+\s*"
    while re.match(label, text):
        text = re.sub(label, "", text, count=1)
    text = re.sub(r"^\s*(عاجل|خاص)\s+", "", text)
    lines = [l.strip(" -–•|") for l in text.split("\n") if l.strip(" -–•|")]
    if not lines:
        return EditResult(publishable=False, skip_reason="لا يوجد نص", template="general", headline="", is_rumor=False)
    # سطر نداء قصير مثل "ياعالمين !!!" ليس عنوانًا: العنوان من السطر الذي بعده
    if len(lines) > 1 and len(tidy_punct(lines[0]).split()) < 3:
        lines = lines[1:]
    first = lines[0]
    sentences = re.split(r"(?<=[.!؟?])\s+|\s+[-–]\s+", first)
    headline = tidy_punct(sentences[0])
    parts = [re.sub(r"\s*[.…]{2,}\s*$", "", x.strip()) for x in sentences[1:] + lines[1:]]
    parts = [x for x in parts if x]
    # كل سطر في المصدر جملة مستقلة: نفصلها بفاصلة حتى لا تلتصق الأرقام بما قبلها
    rest = " ".join(x if re.search(r"[.!؟?،,:]$", x.strip()) or i == len(parts) - 1 else x.strip() + "،"
                    for i, x in enumerate(parts))
    if len(headline.split()) > 13:  # جملة قصيرة نسبيًا تبقى كاملة بدل قطعها
        words = headline.split()
        # أفضل قطع: عند أول فاصلة تنهي عبارة كاملة
        commas = [i + 1 for i, w in enumerate(words[:14]) if w.endswith(("،", ",")) and i >= 3]
        cut = commas[0] if commas else _natural_cut(words)
        words = [w.rstrip("،,") if i == cut - 1 else w for i, w in enumerate(words)]
        tail = re.sub(r"\s*[.…]{2,}\s*$", "", " ".join(words[cut:]))
        if rest and not re.search(r"[.!؟?،,:]$", tail):
            tail += "،"
        headline, rest = " ".join(words[:cut]), (tail + " " + rest).strip()
    body = _body_from(rest)
    template = classify(raw)
    rumor = is_rumor_text(raw)
    norm = normalize_ar(raw)
    kicker = ""
    if not rumor and _has_any(norm, ["رسميا"]):
        kicker = "رسميًا"
    if kicker:  # "رسميًا" تظهر مرة واحدة فوق العنوان
        headline = re.sub(r"^\s*رسمي[اًً]*\s*[:\-|—–]*\s*", "", headline) or headline
    speaker = quote = number = number_caption = ""
    if len(lines) >= 2 and lines[0].rstrip().endswith(":"):
        template = "statement"
    if template == "statement":
        joined = " ".join(lines)
        short = re.match(r"^([^:\n]{3,40}):\s*(.+)$", joined, re.S)          # "المدرب: نص"
        long_ = re.match(r"^([^:\n]{3,160}?)\s*:\s*(.+)$", joined, re.S)     # "فلان يتحدث عن كذا :\nنص"
        m = short or (long_ if lines[0].rstrip().endswith(":") else None)
        if m:
            words = tidy_punct(m.group(1)).split()
            speaker = " ".join(words[:_natural_cut(words)]) if len(words) > 10 else " ".join(words)
            quote = tidy_punct(clip_words(m.group(2).strip(" \"«»"), 12))
            headline, body = quote, ""
        else:
            template = "general"
    if template == "stats":
        nums = re.findall(r"\d+(?:[.,]\d+)?%?", text)
        if nums:
            number = nums[0]
    caption = tidy_punct(" ".join(lines)[:600])
    return EditResult(publishable=True, template=template, headline=headline, body=body, kicker=kicker,
                      number=number, number_caption=number_caption, speaker=speaker, quote=quote,
                      is_rumor=rumor, transfer_status="rumor" if (template == "transfer" and rumor) else
                      ("official" if kicker else "none"), telegram_caption=caption)


class Editor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = None
        if cfg.anthropic_api_key:
            import anthropic
            self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, max_retries=3, timeout=120)

    @property
    def uses_llm(self) -> bool:
        return self.client is not None

    def edit(self, raw: str, history_cands: list) -> tuple[EditResult, str]:
        """يعيد (النتيجة، الطريقة). يرفع EditorError عند الفشل الكامل"""
        if is_dhikr(raw):
            return dhikr_result(raw), "rules"
        if self.client:
            try:
                res = self._llm(raw, history_cands)
                problems = validate(res, raw)
                if not problems:
                    return as_comment(res, raw), "llm"
                log.warning("مخرجات النموذج رُفضت: %s", problems)
            except Exception as e:
                log.warning("فشل نموذج اللغة، سيستخدم المحرر المحلي: %s", e)
        res = rule_based(raw)
        problems = validate(res, raw)
        if problems:
            raise EditorError("؛ ".join(problems))
        return as_comment(res, raw), "rules"

    def _llm(self, raw: str, cands: list) -> EditResult:
        import anthropic
        prev = "\n".join(f"[{i}] {row['headline'] or ''} | {(row['raw_text'] or '')[:300]}"
                         for i, (_, row) in enumerate(cands)) or "لا يوجد"
        user = f"المنشور الجديد:\n<<<\n{raw}\n>>>\n\nأخبار سابقة مشابهة أرسلناها:\n{prev}"
        resp = self.client.messages.parse(
            model=self.cfg.llm_model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            output_config={"effort": self.cfg.llm_effort},
            messages=[{"role": "user", "content": user}],
            output_format=EditResult,
        )
        if resp.stop_reason == "refusal":
            raise EditorError("النموذج رفض الطلب")
        if resp.parsed_output is None:
            raise EditorError("لم يُرجع النموذج مخرجات صالحة")
        return resp.parsed_output


def validate(res: EditResult, raw: str) -> list[str]:
    """حواجز الدقة: الأرقام والرسمية وطول النصوص"""
    if not res.publishable:
        return []
    problems = []
    src_nums = numbers(raw)
    for field_name in ("headline", "body", "number", "number_caption", "quote", "kicker"):
        val = getattr(res, field_name)
        extra = numbers(val) - src_nums
        if extra:
            problems.append(f"رقم غير موجود في المصدر في {field_name}: {extra}")
    norm = normalize_ar(raw)
    if "رسمي" in normalize_ar(res.kicker + " " + res.headline) and not _has_any(norm, OFFICIAL_SIGNS):
        problems.append("وصف الخبر بالرسمي والمصدر لا يذكر ذلك")
    if res.transfer_status == "official" and is_rumor_text(raw):
        problems.append("خبر انتقال غير مؤكد وُصف بالرسمي")
    if not (res.headline or res.quote):
        problems.append("لا يوجد عنوان")
    if len(res.headline.split()) > 14:
        problems.append("العنوان طويل")
    return problems


def to_snap(res: EditResult, image_path: str | None, source_url: str, is_update: bool,
            clean) -> Snap:
    """تحويل نتيجة التحرير إلى سنابة مع تنظيف الحروف غير المدعومة في الخط"""
    rumor = res.is_rumor or res.transfer_status == "rumor"
    return Snap(
        template=res.template,
        headline=clean(tidy_punct(res.headline)),
        body=clean(tidy_punct(res.body)),
        kicker=clean(tidy_punct(res.kicker)) if not rumor else "",
        number=clean(res.number.strip()),
        number_caption=clean(tidy_punct(res.number_caption)),
        speaker=clean(tidy_punct(res.speaker)),
        quote=clean(tidy_punct(res.quote)),
        transfer_status=res.transfer_status if res.transfer_status != "none" else "",
        is_rumor=rumor,
        is_update=is_update,
        image_path=image_path,
        caption=res.telegram_caption or res.headline,
        source_url=source_url,
    )

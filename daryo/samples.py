"""يولّد نماذج لكل القوالب للمراجعة: python -m daryo.cli samples"""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from .config import ROOT, Config
from .models import Snap
from .qa import check_render, check_snap_text, verify_font
from .render import RenderError, save_png
from .design import Designer, create_renderer

WIDE = str(ROOT / "assets" / "sample_photo_wide.jpg")
TALL = str(ROOT / "assets" / "sample_photo_tall.jpg")

# أخبار تجريبية للعرض فقط وليست أخبارًا حقيقية
SAMPLES = {
    "1_breaking": Snap("breaking", "رونالدو يغيب عن مواجهة الهلال",
                       "إصابة في العضلة الخلفية والجهاز الطبي يحدد مدة الغياب غدًا",
                       kicker="الآن", image_path=WIDE),
    "2_statement": Snap("statement", "", speaker="مدرب النصر",
                        quote="الفريق جاهز للديربي ولا نخاف من أحد",
                        body="في المؤتمر الصحفي قبل مباراة الهلال", image_path=TALL),
    "3_stats": Snap("stats", "رونالدو يواصل كتابة التاريخ مع النصر", number="100",
                    number_caption="هدف بقميص النصر", image_path=WIDE),
    "4_transfer_rumor": Snap("transfer", "النصر يقترب من حسم صفقة المهاجم الجديد",
                             "المفاوضات في مراحلها الأخيرة حسب تقارير صحفية", is_rumor=True,
                             transfer_status="rumor", image_path=WIDE),
    "5_general_update": Snap("general", "النصر يستأنف تدريباته استعدادًا للديربي",
                             "حصة مسائية في الأول بارك بمشاركة جميع اللاعبين", is_update=True,
                             image_path=WIDE),
    "6_text_only": Snap("breaking", "النصر يعلن رسميًا تمديد عقد قائد الفريق حتى 2028",
                        "البيان صدر عبر الحسابات الرسمية للنادي", kicker="رسميًا"),
    "7_transfer_official": Snap("transfer", "النصر يعلن التعاقد مع المدافع الجديد حتى 2029",
                                "الصفقة انتقال حر بعد نهاية عقده", kicker="رسميًا",
                                transfer_status="official"),
}


# These are layout fixtures, not verified current news. No publishing involved.
SAMPLES.update({
    "8_ticket_prices": Snap("tickets", "أسعار تذاكر لقاء الأهلي والنصر",
                            rows=[("الواجهة", "60 ريال"), ("خلف المرمى", "40 ريال"),
                                  ("الزوايا", "50 ريال"), ("الدور الثالث", "25–35 ريال")]),
    "9_ticket_release": Snap("tickets", "طرح تذاكر الأهلي والنصر لأصحاب التذاكر الموسمية",
                             "الجمعة 20 نوفمبر\nالساعة 8:30 مساءً\nملعب الإنماء في جدة"),
    "10_availability": Snap("availability", "إصابات الأهلي قبل لقاء النصر القادم",
                            "تبقى على لقاء النصر 11 يوم",
                            rows=[("مريح ديميرال", "مصاب"), ("زكريا هوساوي", "مصاب"),
                                  ("صالح أبو الشامات", "مصاب"), ("نايف مسعود", "مصاب"),
                                  ("إدوارد سيبيرتسيان", "مصاب"), ("فالنتين أتانغانا", "مصاب")]),
    "11_long_quote": Snap("statement", "", speaker="تصريح تجريبي لاختبار القراءة",
                          quote=" ".join(["نستعد للمواجهة القادمة بكل تركيز ونعمل يوميًا على تطوير أداء الفريق"] * 7)),
})


SAMPLES.update({
    "12_match_result": Snap("result", "النصر يحقق فوزه الخامس توالياً ويتصدر مؤقتاً",
                            home="النصر", away="الاتفاق", home_score="3", away_score="1",
                            competition="دوري روشن السعودي • الجولة 11",
                            rows=[("النصر", "رونالدو 12' 67'"), ("النصر", "ماني 81'"),
                                  ("الاتفاق", "لاعب الاتفاق 44'")]),
    "13_statement_text": Snap("statement", "", speaker="مدرب النصر",
                              quote="الفريق جاهز للديربي ولا نخاف من أحد، هدفنا النقاط الثلاث فقط",
                              body="في المؤتمر الصحفي قبل مباراة الهلال"),
})


def build_samples(cfg: Config, out: Path) -> list[Path]:
    with_post = cfg.post_format
    verify_font(cfg.font_path)
    r = create_renderer(cfg)
    paths = []
    for name, snap in SAMPLES.items():
        snap = replace(snap, kicker="معاينة قالب")
        for page in r.paginate(snap) if isinstance(r, Designer) else [snap]:
            check_snap_text(page, cfg.font_path)
            img, lay = r.render(page)
            problems = check_render(img, lay, page)
            if problems:
                raise SystemExit(f"{name}: {problems}")
            suffix = f"_{page.page}" if page.pages > 1 else ""
            paths.append(save_png(img, out / f"{name}{suffix}.png"))
            if with_post and page.pages == 1 and hasattr(r, "render_post"):
                try:
                    post, play = r.render_post(page)
                except RenderError:
                    continue   # long lists stay 9:16 only
                problems = check_render(post, play, page)
                if problems:
                    raise SystemExit(f"{name} (4:5): {problems}")
                paths.append(save_png(post, out / f"{name}_post.png"))
    return paths

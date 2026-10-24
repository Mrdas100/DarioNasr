"""يولّد نماذج لكل القوالب للمراجعة: python -m daryo.cli samples"""
from __future__ import annotations

from pathlib import Path

from .config import ROOT, Config
from .models import Snap
from .qa import check_render, check_snap_text, verify_font
from .render import Renderer, save_png

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


def build_samples(cfg: Config, out: Path) -> list[Path]:
    verify_font(cfg.font_path)
    r = Renderer(cfg.font_path, cfg.logo_path, cfg.snap_handle, cfg.account_name)
    paths = []
    for name, snap in SAMPLES.items():
        check_snap_text(snap, cfg.font_path)
        img, lay = r.render(snap)
        problems = check_render(img, lay, snap)
        if problems:
            raise SystemExit(f"{name}: {problems}")
        paths.append(save_png(img, out / f"{name}.png"))
    return paths

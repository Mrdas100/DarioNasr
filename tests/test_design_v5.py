from pathlib import Path

import pytest

from daryo.config import Config
from daryo.design import POST_H, Designer
from daryo.editor import rule_based, to_snap, validate
from daryo.models import Snap
from daryo.qa import check_render, verify_font

PHOTO = str(Path(__file__).resolve().parent.parent / 'assets' / 'sample_photo_wide.jpg')
TALL = str(Path(__file__).resolve().parent.parent / 'assets' / 'sample_photo_tall.jpg')
RESULT = 'نهاية المباراة\nالنصر 3-1 الاتفاق\nالنصر يحقق فوزه الخامس توالياً'


@pytest.fixture
def designer():
    c = Config()
    return Designer(c.font_path, c.logo_path, c.snap_handle, c.account_name)


def test_default_font_is_approved_noto_family(designer):
    c = Config()
    assert 'NotoSansArabic' in c.font_path.name
    for path in (designer.bold_path, designer.semibold_path, designer.black_path):
        verify_font(Path(path))
    assert len({designer.bold_path, designer.semibold_path, designer.black_path}) == 3


def test_result_extracted_only_with_full_time_marker():
    r = rule_based(RESULT)
    assert (r.template, r.home_team, r.away_team, r.home_score, r.away_score) == \
        ('result', 'النصر', 'الاتفاق', '3', '1')
    assert validate(r, RESULT) == []
    assert rule_based('النصر يواجه الاتفاق 3-1 في الذهاب').template != 'result'


@pytest.mark.parametrize('photo', [None, PHOTO])
def test_result_renders_scoreboard_with_qa(designer, photo):
    snap = to_snap(rule_based(RESULT), photo, 'u', False, lambda s: s)
    img, lay = designer.render(snap)
    assert check_render(img, lay, snap) == []
    assert {'text:home', 'text:away', 'text:home_score', 'text:away_score'} <= {n for n, _ in lay.boxes}


def test_unfittable_result_falls_back_to_news(designer):
    snap = Snap('result', '', home='النصر', away=' '.join(['فريق'] * 8), home_score='1', away_score='0')
    pages = designer.paginate(snap)
    assert pages[0].template == 'general' and 'النصر 1-0' in pages[0].headline


@pytest.mark.parametrize('snap', [
    Snap('breaking', 'رونالدو يغيب عن مواجهة الهلال', 'إصابة عضلية', image_path=TALL),
    Snap('statement', '', speaker='مدرب النصر', quote='الفريق جاهز للديربي', image_path=PHOTO),
    Snap('stats', 'رونالدو يواصل كتابة التاريخ', number='100', number_caption='هدف', image_path=PHOTO),
    Snap('transfer', 'النصر يعلن التعاقد مع المدافع', transfer_status='official'),
])
def test_post_4x5_and_snap_pass_qa(designer, snap):
    img, lay = designer.render(snap)
    assert check_render(img, lay, snap) == []
    post, play = designer.render_post(snap)
    assert post.size == (1080, POST_H)
    assert check_render(post, play, snap) == []
    # The snap geometry is restored after the 4:5 render.
    assert designer.render(snap)[0].size == (1080, 1920)


def test_official_transfer_gets_green_official_tag(designer):
    label, bg, _ = designer._tag(Snap('transfer', 'x', transfer_status='official'))
    assert label == 'رسمي' and bg[1] > bg[0]
    assert designer._tag(Snap('comment', 'x'))[0] == ''
    assert designer._tag(Snap('transfer', 'x', transfer_status='rumor'))[0] == 'سوق الانتقالات'


def test_photo_is_never_cropped(designer):
    from PIL import Image
    snap = Snap('general', 'عنوان تجريبي', image_path=TALL)
    _, lay = designer.render(snap)
    x0, y0, x1, y1 = next(b for n, b in lay.boxes if n == 'photo')
    w, h = Image.open(TALL).size
    assert abs((x1 - x0) / (y1 - y0) - w / h) < 0.01

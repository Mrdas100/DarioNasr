from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from daryo.config import Config
from daryo.design import Designer, create_renderer
from daryo.editor import Editor, rule_based, to_snap, validate
from daryo.filters import reject_reason
from daryo.models import Snap, SourcePost
from daryo.qa import check_render
from daryo.render import Layout, RenderError
from daryo.structured import extract

PRICES = ('أسعار تذاكر لقاء ( الأهلي، النصر )، ( الواجهة ): 60 ريال، '
          '( خلف المرمى ): 40 ريال، ( زوايا ): 50 ريال، ( دور ثالث ): من 25-35 ريال')
RELEASE = ('طرح تذاكر الأهلي والنصر لأصحاب التذاكر الموسمية ⬇️\n'
           'اللقاء سيُقام 20 نوفمبر (الجمعة)، الساعة 8:30م على ملعب الإنماء في جدة 🏟️\n'
           'رابط حجز التذاكر\nhttps://webook.com/ar/events/test')
ABSENCES = ('إصابات الأهلي قبل لقاء النصر القادم\n'
            'مريح ديميرال (❌) زكريا هوساوي (❌) صالح أبو الشامات (❌) '
            'نايف مسعود (❌) إدوارد سيبيرتسيان (❌) فالنتين أتانغانا (❌)\n'
            'تبقى على لقاء النصر 11 يوم')


@pytest.fixture
def designer():
    c = Config()
    return Designer(c.font_path, c.logo_path, c.snap_handle, c.account_name)


def test_prices_keep_category_value_and_range_order():
    r = rule_based(PRICES)
    assert r.template == 'tickets'
    assert r.rows == [('الواجهة', '60 ريال'), ('خلف المرمى', '40 ريال'),
                      ('زوايا', '50 ريال'), ('دور ثالث', 'من 25–35 ريال')]
    assert validate(r, PRICES) == []
    assert not r.speaker


def test_release_preserves_membership_date_time_and_booking_link():
    r, method = Editor(Config(anthropic_api_key='')).edit(RELEASE, [])
    assert method == 'rules' and r.template == 'tickets'
    assert 'الموسمية' in r.headline
    assert '8:30' in r.body and '20 نوفمبر' in r.body
    assert 'https://webook.com/ar/events/test' in r.telegram_caption
    assert validate(r, RELEASE) == []


def test_marked_absences_never_classified_as_statement():
    r = rule_based(ABSENCES)
    assert r.template == 'availability'
    assert len(r.rows) == 6
    assert r.rows[-1] == ('فالنتين أتانغانا', 'مصاب')
    assert '11 يوم' in r.body
    assert extract(ABSENCES + ' ✅ جاهز') is None


@pytest.mark.parametrize('raw', [PRICES, RELEASE, ABSENCES])
def test_source_examples_render_every_page_with_qa(raw, designer):
    r = rule_based(raw)
    snap = to_snap(r, None, 'https://t.me/n9rfc/1', False, lambda x: x)
    pages = designer.paginate(snap)
    assert [row for page in pages for row in page.rows] == snap.rows
    for page in pages:
        img, lay = designer.render(page)
        assert check_render(img, lay, page) == []
        for label, value in page.rows:
            drawn = ' '.join(lay.texts)
            assert label in drawn and value in drawn


def test_long_quote_keeps_every_word_across_pages(designer):
    quote = ' '.join(f'كلمة{i}' for i in range(150))
    snap = Snap('statement', quote, speaker='المدرب', quote=quote)
    pages = designer.paginate(snap)
    assert ' '.join(p.quote for p in pages) == quote
    assert [p.page for p in pages] == list(range(1, len(pages) + 1))
    for page in pages:
        img, lay = designer.render(page)
        assert check_render(img, lay, page) == []


def test_overflow_raises_instead_of_truncating(designer):
    with pytest.raises(RenderError):
        designer.render(Snap('general', 'كلمة ' * 500))


def test_newline_and_unbreakable_token_measurement(designer):
    assert designer.wrap('الجمعة 20 نوفمبر\nالساعة 8:30م', 45, 900) == ['الجمعة 20 نوفمبر', 'الساعة 8:30م']
    assert designer.fit('W' * 200, 500, 60, 40, 3)[0] is None


def test_same_renderer_for_samples_and_service():
    assert isinstance(create_renderer(Config(design_style='nassr')), Designer)


def test_qa_catches_missing_body_and_rows(designer):
    snap = Snap('tickets', 'تذاكر النصر', body='لأصحاب التذاكر الموسمية', rows=[('الواجهة', '60 ريال')])
    img, lay = designer.render(snap)
    lay.texts = [s for s in lay.texts if 'الموسمية' not in s]
    assert any('كامل' in p for p in check_render(img, lay, snap))


def test_video_overlay_and_still_share_geometry(designer):
    c = Config()
    snap = Snap('breaking', 'عنوان تجريبي للصورة', image_path=str(c.logo_path.parent / 'sample_photo_tall.jpg'))
    img, lay = designer.render(snap)
    combined = lay.base.convert('RGBA')
    combined.alpha_composite(lay.overlay)
    assert combined.convert('RGB').tobytes() == img.tobytes()
    assert check_render(img, lay, snap) == []


def test_service_prepares_all_pages_and_preserves_booking_link(tmp_path, monkeypatch):
    import asyncio
    from datetime import datetime, timezone
    from daryo.service import Service
    monkeypatch.setenv('DRY_RUN', '1')
    s = Service(Config(data_dir=tmp_path, anthropic_api_key='', bot_token='', source_mode='web'))
    sent = []
    class Bot:
        def send_png(self, path, caption=''):
            sent.append((path, caption))
        def alert(self, text):
            pass
    s.bot = Bot()
    raw = ABSENCES.replace('تبقى على', 'لاعب إضافي (❌)\nتبقى على') + '\nhttps://webook.com/ar/events/test'
    post = SourcePost(800, datetime.now(timezone.utc), raw, url='https://t.me/n9rfc/800')
    asyncio.run(s.process(post))
    assert len(sent) == 2
    assert all('https://t.me/n9rfc/800' in c and 'https://webook.com/ar/events/test' in c for _, c in sent)
    assert all(p.exists() for p, _ in sent)


def test_service_sends_no_partial_list_when_later_page_fails(tmp_path, monkeypatch):
    import asyncio
    from datetime import datetime, timezone
    from daryo.service import Service
    from daryo.qa import QAError
    monkeypatch.setenv('DRY_RUN', '1')
    s = Service(Config(data_dir=tmp_path, anthropic_api_key='', bot_token='', source_mode='web'))
    sent = []
    class Bot:
        def send_png(self, *args):
            sent.append(args)
        def alert(self, text):
            pass
    s.bot = Bot()
    original = s._design
    def fail_second(snap, msg_id, idx):
        if snap.page == 2:
            raise QAError('فشل اختباري')
        return original(snap, msg_id, idx)
    s._design = fail_second
    raw = ABSENCES.replace('تبقى على', 'لاعب إضافي (❌)\nتبقى على')
    asyncio.run(s.process(SourcePost(801, datetime.now(timezone.utc), raw)))
    assert sent == []


@pytest.mark.parametrize('style', ['clean', 'cinema', 'brand'])
def test_structured_news_supported_with_legacy_setting(style):
    renderer = create_renderer(Config(design_style=style))
    snap = to_snap(rule_based(PRICES), None, '', False, lambda x: x)
    img, lay = renderer.render(snap)
    assert check_render(img, lay, snap) == []


def test_long_caption_keeps_url_whole_across_telegram_messages():
    from daryo.textutil import message_chunks
    url = 'https://webook.com/ar/events/test'
    text = ('خبر رياضي ' * 1000) + url
    parts = message_chunks(text)
    assert len(parts) > 1
    assert ' '.join(parts).split() == text.split()
    assert any(url in part for part in parts)
    assert all(len(part.encode('utf-16-le')) // 2 <= 3500 for part in parts)

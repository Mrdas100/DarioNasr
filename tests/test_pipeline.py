"""اختبار المسار كاملًا بمصدر وهمي دون إنترنت: python -m pytest -q"""
import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from daryo.config import ROOT, Config
from daryo.models import SourcePost
from daryo.schedule import in_hours
from daryo.sources import parse_preview_html

PHOTO = str(ROOT / "assets" / "sample_photo_wide.jpg")


class FakeSource:
    name = "fake"

    def __init__(self):
        self.posts = []

    async def start(self):
        pass

    async def fetch_latest(self, limit=40):
        return list(self.posts)

    async def download(self, post, dest):
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for i, _ in enumerate(post.media_refs):
            p = dest / f"{post.msg_id}_{i}.jpg"
            shutil.copy(PHOTO, p)
            out.append(str(p))
        return out


def post(i, text, photo=True):
    p = SourcePost(msg_id=i, date=datetime.now(timezone.utc), text=text, url=f"https://t.me/n9rfc/{i}")
    if photo:
        p.media_refs = [("photo", "x")]
    return p


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    from daryo.service import Service
    s = Service(Config())
    s.source = FakeSource()
    return s


def run(coro):
    return asyncio.run(coro)


def test_full_flow(svc):
    src = svc.source
    src.posts = [post(1, "خبر قديم قبل التشغيل")]
    run(svc.baseline())
    assert svc.db.known(1)["status"] == "baseline"

    src.posts += [
        post(2, "🚨 عاجل: رونالدو يغيب عن مواجهة الهلال بسبب الإصابة في العضلة الخلفية"),
        post(3, "للإعلان والتواصل واتساب 0500000000", photo=False),
        post(4, "رأيكم؟؟", photo=False),
        post(5, "عاجل | غياب رونالدو عن مواجهة الهلال بسبب إصابة في العضلة الخلفية 🚨"),
        post(6, "مصادر: النصر يقترب من التعاقد مع مدافع جديد والمفاوضات في مراحلها الأخيرة"),
        post(7, "رسميًا: رونالدو يغيب عن مواجهة الهلال لمدة 3 أسابيع بسبب الإصابة في العضلة الخلفية"),
    ]
    run(svc.tick())
    st = {i: svc.db.known(i)["status"] for i in range(2, 8)}
    assert st[2] == "sent"
    assert st[3] == "skipped"
    assert st[4] == "skipped"
    assert st[5] == "duplicate", svc.db.known(5)["reason"]
    assert st[6] == "sent"
    assert st[7] == "sent"
    assert svc.db.known(7)["update_of"] is not None  # خبر محدّث مرتبط بالسابق
    png = Path(svc.db.known(2)["png_path"])
    from PIL import Image
    assert Image.open(png).size == (1080, 1920)

    # تعديل المصدر لمنشور مرسل بمعنى جديد = تحديث
    src.posts[-2] = post(6, "رسميًا النصر يعلن التعاقد مع المدافع الجديد حتى 2029")
    run(svc.tick())
    assert svc.db.known(6)["update_of"] is not None


def test_rumor_not_official():
    from daryo.editor import rule_based, validate
    r = rule_based("مصادر: النصر يقترب من ضم المهاجم")
    assert r.is_rumor and r.kicker == ""
    assert validate(r, "مصادر: النصر يقترب من ضم المهاجم") == []


def test_numbers_guard():
    from daryo.editor import EditResult, validate
    bad = EditResult(publishable=True, template="stats", headline="رونالدو يسجل 101 هدف", is_rumor=False)
    assert validate(bad, "رونالدو يسجل 100 هدف")


def test_hours():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Riyadh")
    assert in_hours("08:00-02:00", "Asia/Riyadh", datetime(2026, 1, 1, 1, 0, tzinfo=tz))
    assert not in_hours("08:00-02:00", "Asia/Riyadh", datetime(2026, 1, 1, 5, 0, tzinfo=tz))
    assert in_hours("", "Asia/Riyadh")


def test_preview_parser():
    html = """<div class="tgme_channel_info"></div>
    <div class="tgme_widget_message" data-post="n9rfc/33011">
      <div class="tgme_widget_message_grouped_wrap">
        <a class="tgme_widget_message_photo_wrap" style="width:100px;background-image:url('https://cdn.example/a.jpg')"></a>
        <a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn.example/b.jpg')"></a>
      </div>
      <div class="tgme_widget_message_text">سطر أول<br/>سطر ثاني</div>
      <span class="tgme_widget_message_meta"><time datetime="2026-10-24T03:00:00+00:00"></time></span>
    </div>"""
    posts = parse_preview_html(html, "n9rfc")
    assert posts[0].msg_id == 33011
    assert posts[0].text == "سطر أول\nسطر ثاني"
    assert [r[1] for r in posts[0].media_refs] == ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"]


def test_bot_source_album():
    import time as _t
    from daryo.sources import BotSource
    cfg = Config()
    cfg.source_channel = "n9rfc"
    src = BotSource(cfg)
    src.SETTLE_SEC = 0
    chat = {"id": -100123, "username": "n9rfc", "type": "channel"}
    base = {"chat": chat, "date": int(_t.time()), "media_group_id": "g1"}
    src.on_channel_post({**base, "message_id": 11, "caption": "عاجل النصر يفوز", "photo": [{"file_id": "s"}, {"file_id": "big1"}]}, False)
    src.on_channel_post({**base, "message_id": 12, "photo": [{"file_id": "big2"}]}, False)
    src.on_channel_post({"chat": {"id": 5, "username": "other"}, "date": 0, "message_id": 99, "text": "x"}, False)
    posts = asyncio.run(src.fetch_latest())
    assert len(posts) == 1
    p = posts[0]
    assert p.msg_id == 11 and p.text == "عاجل النصر يفوز"
    assert [r[1] for r in p.media_refs] == ["big1", "big2"]
    src.on_channel_post({**base, "message_id": 11, "caption": "عاجل النصر يفوز 2-0"}, True)
    p = asyncio.run(src.fetch_latest())[0]
    assert p.text.endswith("2-0") and len(p.media_refs) == 2

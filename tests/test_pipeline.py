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


def test_elongated_breaking_label():
    from daryo.editor import rule_based, validate
    t = "🚨🚨🚨 عاااااااااجل :  تعيين عصام الشوالي معلقا لمباراة النصر والهلال في الجولة القادمة من دوري روشن"
    r = rule_based(t)
    assert r.template == "breaking" and r.speaker == ""
    assert r.headline.startswith("تعيين عصام الشوالي")
    assert validate(r, t) == []


def test_preview_parser_video():
    html = """<div class="tgme_widget_message" data-post="n9rfc/500">
      <div class="tgme_widget_message_video_player">
        <i class="tgme_widget_message_video_thumb" style="background-image:url('https://cdn.example/t.jpg')"></i>
        <video src="https://cdn.example/v.mp4"></video>
      </div>
      <div class="tgme_widget_message_text">نيو لوك</div>
    </div>"""
    p = parse_preview_html(html, "n9rfc")[0]
    assert p.has_video and p.media_refs == [("video", "https://cdn.example/v.mp4", "https://cdn.example/t.jpg")]
    assert p.msg_ids == [500]


def test_video_snap(svc, tmp_path):
    import subprocess
    vid = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-pix_fmt", "yuv420p", str(vid)], check=True)
    from daryo.sources import extract_frame

    class VidSource(FakeSource):
        async def download(self, post, dest):
            dest.mkdir(parents=True, exist_ok=True)
            mp4 = dest / f"{post.msg_id}_0.mp4"
            shutil.copy(vid, mp4)
            jpg = dest / f"{post.msg_id}_0.jpg"
            assert extract_frame(mp4, jpg)
            return [str(jpg)]

    svc.source = VidSource()
    p = post(20, "نيو لوك قلب الاسد انييغو مارتينيز")
    p.has_video = True
    run(svc.process(p))
    row = svc.db.known(20)
    assert row["status"] == "sent" and row["png_path"].endswith(".mp4")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                          "-of", "csv=p=0", row["png_path"]], capture_output=True, text=True).stdout
    assert "video,1080,1920" in out and "audio" in out
    from daryo.video import duration
    assert abs(duration(Path(row["png_path"])) - 3) < 0.3


def test_long_text_keeps_photo(svc):
    text = ("عاجل — رسمياً: موقع FIFA يحتسب الهدف الثاني للنصر هدفًا عكسيًا وليس لكريستيانو رونالدو! "
            "وبذلك يتوقف رصيد رونالدو عند هدف واحد في المباراة بعد مراجعة اللقطة من الاتحاد الدولي")
    run(svc.process(post(21, text)))
    row = svc.db.known(21)
    assert row["status"] == "sent"
    assert "عاجل" not in row["headline"]


def test_short_rumor_words_match_whole_words():
    from daryo.editor import is_rumor_text
    assert not is_rumor_text("🚨 عاجل كل ما قدمه رونالدو امام الفيصلي")
    assert is_rumor_text("قد يغيب رونالدو عن المباراة")


def test_full_text_kept():
    from daryo.editor import rule_based
    r = rule_based("يعقـد السيـد آنج بوستيكوجلو عند الثالثة والنصف عصر غدٍ الثلاثاء، مؤتمرًا صحفيًا للحديث عن مباراة #النصر_الخلود\nوذلك في قاعة المؤتمرات بمقر دار #النصر 🎙️")
    assert r.headline.endswith("الثلاثاء")
    assert "النصر الخلود" in r.body and r.body.rstrip(" 🎙️").endswith("دار النصر")


def test_album_collage(svc):
    p = post(30, "عاجل النصر يكشف عن قميصه الجديد للموسم المقبل")
    p.media_refs = [("photo", "a"), ("photo", "b"), ("photo", "c"), ("photo", "d")]
    run(svc.process(p))
    row = svc.db.known(30)
    assert row["status"] == "sent"
    assert (svc.cfg.media_dir / "30_album.jpg").exists()


def test_short_caption_album_accepted(svc):
    p = post(31, "تدريـبٌ جديـد 💛")
    p.media_refs = [("photo", "a"), ("photo", "b"), ("photo", "c"), ("photo", "d")]
    run(svc.process(p))
    assert svc.db.known(31)["status"] == "sent"


def test_inline_emoji_rendered(tmp_path):
    from PIL import Image
    from daryo.config import Config
    from daryo.editor import rule_based, to_snap
    from daryo.emoji import EmojiStore
    from daryo.qa import check_render, check_snap_text
    from daryo.render import Renderer
    for code, color in (("1f49b", (255, 200, 0, 255)), ("1f981", (200, 120, 0, 255))):
        Image.new("RGBA", (64, 64), color).save(tmp_path / f"{code}.png")
    c = Config()
    rd = Renderer(c.font_path, c.logo_path, c.snap_handle, c.account_name,
                  emoji=EmojiStore(tmp_path, download=False))
    r = rule_based("🚨🚨🚨 نيو لوك قلب الاسد انييغو مارتينيز 💛🦁")
    assert r.headline.endswith("💛🦁") and "🚨" not in r.headline
    snap = to_snap(r, PHOTO, "u", False, lambda s: s)
    check_snap_text(snap, c.font_path)
    img, lay = rd.render(snap)
    assert check_render(img, lay, snap) == []


def test_keycap_emoji_split():
    from daryo.emoji import names, runs
    assert runs("حضوره، 9️⃣💛7️⃣")[1:] == [(True, "9️⃣"), (True, "💛"), (True, "7️⃣")]
    assert names("9️⃣")[0] == "0039-fe0f-20e3"

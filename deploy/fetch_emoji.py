"""ينزّل صور إيموجي أبل المستخدمة في التصميم وقت بناء الصورة على السيرفر (مكتبة emoji-datasource-apple)"""
import sys
import urllib.request
from pathlib import Path

CODES = ["1f6a8"]  # 🚨
SOURCES = ["https://cdn.jsdelivr.net/npm/emoji-datasource-apple@15.1.2/img/apple/64/{}.png",
           "https://unpkg.com/emoji-datasource-apple@15.1.2/img/apple/64/{}.png"]

out = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/emoji")
out.mkdir(parents=True, exist_ok=True)
for code in CODES:
    for src in SOURCES:
        try:
            data = urllib.request.urlopen(src.format(code), timeout=30).read()
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                (out / f"{code}.png").write_bytes(data)
                print("emoji", code, "ok")
                break
        except Exception as e:  # التصميم يرجع للأيقونة المرسومة إن لم يتوفر
            print("emoji", code, "failed from", src, e)

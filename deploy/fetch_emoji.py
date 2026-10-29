"""ينزّل صور إيموجي أبل المستخدمة في التصميم وقت بناء الصورة على السيرفر (مكتبة emoji-datasource-apple)"""
import sys
import urllib.request
from pathlib import Path

# 🚨 وأكثر الإيموجي استخدامًا في القناة
CODES = ["1f6a8", "26a0-fe0f", "1f525", "1f49b", "1f981", "26bd", "1f3c6", "1f44f", "1f399-fe0f", "1f4cd",
         "2705", "274c", "1f929", "1f631", "1f3a5", "1f4aa", "1f451", "1f31f", "2b50", "1f3af", "1f60d",
         "1f499", "2764-fe0f", "1f64c", "1f389", "1f4f8", "1f4fa", "1f4e2", "1f6a9", "1f1f8-1f1e6",
         "1f602", "1f62e", "1f914", "1f44d", "1f64f", "1f90d", "1f5e3-fe0f", "1f4f9", "23f0", "1f4c5",
         "0030-fe0f-20e3", "0031-fe0f-20e3", "0032-fe0f-20e3", "0033-fe0f-20e3", "0034-fe0f-20e3",
         "0035-fe0f-20e3", "0036-fe0f-20e3", "0037-fe0f-20e3", "0038-fe0f-20e3", "0039-fe0f-20e3", "1f51f",
         "1f410", "1f947", "1f3c5", "1f4af"]
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

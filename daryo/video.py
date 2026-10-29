"""سنابة فيديو: نفس التصميم مع تشغيل فيديو الخبر الأصلي مكان الصورة (ffmpeg)"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

log = logging.getLogger("daryo.video")

MAX_SEC = 60           # أطول مدة للسنابة الواحدة


class VideoError(Exception):
    pass


def video_of(photo_path: str | None) -> Path | None:
    """لقطة الفيديو محفوظة بجانب ملف الفيديو بنفس الاسم"""
    if not photo_path:
        return None
    v = Path(photo_path).with_suffix(".mp4")
    return v if v.exists() and v.stat().st_size > 1000 else None


def duration(video: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise VideoError("تعذر قراءة مدة الفيديو الأصلي")


def compose(png: Path, video: Path, box: tuple[int, int, int, int], out: Path, radius: int = 26,
            overlay: Path | None = None) -> Path:
    """يركّب الفيديو داخل مربع الصورة في التصميم مع الصوت الأصلي.
    overlay: طبقة شفافة (الشعار والتدرج والنص) تُوضع فوق الفيديو"""
    x0, y0, x1, y1 = box
    # مدة السنابة = مدة الفيديو الأصلي بالضبط (الصورة الخلفية والقناع يتكرران بلا نهاية)
    secs = min(duration(video), MAX_SEC)
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    mask = out.with_suffix(".mask.png")
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    m.save(mask)
    flt = (f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,format=rgba[v];"
           f"[2:v]format=gray,scale={w}:{h}[m];[v][m]alphamerge[vm];"
           f"[0:v][vm]overlay={x0}:{y0}:shortest=1")
    inputs = ["-loop", "1", "-i", str(png), "-i", str(video), "-loop", "1", "-i", str(mask)]
    if overlay is not None:
        flt += "[bv];[3:v]format=rgba[ov];[bv][ov]overlay=0:0,format=yuv420p[out]"
        inputs += ["-loop", "1", "-i", str(overlay)]
    else:
        flt += ",format=yuv420p[out]"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs,
           "-filter_complex", flt, "-map", "[out]", "-map", "1:a?",
           "-t", f"{secs:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise VideoError((e.stderr or b"").decode(errors="ignore")[-300:] or str(e))
    except Exception as e:
        raise VideoError(str(e))
    finally:
        mask.unlink(missing_ok=True)
    if not out.exists() or out.stat().st_size < 10000:
        raise VideoError("ملف الفيديو الناتج فارغ")
    return out

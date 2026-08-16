import os
import re
import subprocess

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()

FILES = [
    r"G:\夏校\2026_08_15_8.2课程回放\20260802134525-会议-视频-1-共享屏幕.mp4",
    r"G:\夏校\2026_08_15_8.2课程回放\7.29课程回放.mp4",
    r"G:\夏校\2026_08_15_8.2课程回放\7.31课程回放.mp4",
]


def measure(path):
    # 只分析前 60 秒，快速估算音量水平
    proc = subprocess.run(
        [FF, "-t", "60", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace",
    )
    err = proc.stderr
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err)
    maxv = re.search(r"max_volume:\s*(-?[\d.]+) dB", err)
    dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", err)
    d = ""
    if dur:
        h, m, s, ms = dur.groups()
        d = f"{int(h)}:{int(m):02d}:{int(s):02d}"
    return {
        "mean": float(mean.group(1)) if mean else None,
        "max": float(maxv.group(1)) if maxv else None,
        "dur": d,
        "size_mb": round(os.path.getsize(path) / 1048576, 1),
    }


for p in FILES:
    m = measure(p)
    # recommended boost to bring mean to ~-16dB (typical dialogue level)
    rec = ""
    if m["mean"] is not None:
        rec = f"建议放大 ~{max(2, round(-16 - m['mean']))}x"
    print(f"{os.path.basename(p)}")
    print(f"  时长: {m['dur']} | 大小: {m['size_mb']} MB")
    print(f"  音量: mean {m['mean']} dB, max {m['max']} dB | {rec}")

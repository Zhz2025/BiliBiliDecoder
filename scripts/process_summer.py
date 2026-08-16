"""批处理转写夏校课程回放：放大视频(可选) + FunASR 转写 + srt/md。
带断点续跑（已存在则跳过）与进度日志（scripts/transcribe_progress.log）。

用法：.venv\\Scripts\\python.exe scripts\\process_summer.py
"""

import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bilibili_decoder.api.models import VideoInfo  # noqa: E402
from bilibili_decoder.fetch import media  # noqa: E402
from bilibili_decoder.output import markdown as md_out  # noqa: E402
from bilibili_decoder.output import srt as srt_out  # noqa: E402
from bilibili_decoder.stt import engine  # noqa: E402

LOGFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe_progress.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOGFILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("summer")

D = r"G:\夏校\2026_08_15_8.2课程回放"

# (文件名, 是否需要 loudnorm 放大)
JOBS = [
    ("7.29课程回放.mp4", True),
    ("7.31课程回放.mp4", True),
    ("20260802134525-会议-视频-1-共享屏幕.mp4", False),
]


def process(fname: str, loudnorm: bool) -> None:
    path = os.path.join(D, fname)
    base = os.path.splitext(path)[0]
    title = os.path.splitext(fname)[0]
    log.info("===== 开始 %s (loudnorm=%s) =====", fname, loudnorm)

    # 1) 放大版视频（仅需要放大的）
    amp = base + "_放大.mp4"
    if loudnorm and not os.path.exists(amp):
        log.info("导出放大版视频 ...")
        media.amplify_video(path, amp, loudnorm=True)
        log.info("放大版完成: %s", amp)
    elif os.path.exists(amp):
        log.info("放大版已存在，跳过")

    # 2) 转写
    if os.path.exists(base + ".srt") and os.path.exists(base + ".md"):
        log.info("转写已存在，跳过")
        return
    with tempfile.TemporaryDirectory(prefix="bilisub_") as tmp:
        wav = os.path.join(tmp, "audio_16k.wav")
        log.info("提取音频(16k%s) ...", " + loudnorm" if loudnorm else "")
        media.to_16k_wav(path, wav, loudnorm=loudnorm)
        log.info("转写中 ...")
        segs = engine.transcribe(wav)
    log.info("分段数: %d", len(segs))
    if not segs:
        log.warning("未生成转写内容: %s", fname)
        return
    video = VideoInfo(
        bvid="LOCAL", aid=0, cid=0, title=title, duration=0,
        owner_mid=0, owner_name="本地视频",
    )
    srt_out.write_srt(base + ".srt", segs)
    md_out.write_markdown(
        base + ".md", segs, title=title, url=os.path.abspath(path),
        source="STT（FunASR Paraformer）本地文件",
    )
    log.info("转写完成: %s.srt / .md", base)


def main() -> None:
    for fname, loudnorm in JOBS:
        try:
            process(fname, loudnorm)
        except Exception as exc:  # noqa: BLE001
            log.error("%s 失败: %s", fname, exc)
    log.info("全部完成")


if __name__ == "__main__":
    main()

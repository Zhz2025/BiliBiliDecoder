"""Command-line interface for the Bilibili subtitle decoder.

Subcommands:
  video   <url|bvid> ...   Download subtitles for specific videos
  batch   -f list.txt      Process a list of URLs/BVIDs from a file
  up      <mid|space-url>  Crawl a UP主's videos (all / recent N / by tag)
  search  <keyword>        Search videos by keyword
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from typing import Optional

from .api.client import BilibiliClient, parse_bvid, parse_mid
from .api.models import VideoInfo, VideoPart, sanitize_name
from .fetch import media, subtitles
from .output import markdown as md_out
from .output import srt as srt_out
from .stt import engine as stt_engine

log = logging.getLogger("bilibili-decoder")

DEFAULT_FORMATS = ["srt", "md"]


def _out_formats(choice: Optional[str]) -> list[str]:
    if not choice:
        return list(DEFAULT_FORMATS)
    return [f.strip().lower().lstrip(".") for f in choice.split(",") if f.strip()]


def _fmt_dur(secs: int) -> str:
    secs = int(secs)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ----------------------------------------------------------------------
# Core processing
# ----------------------------------------------------------------------
def _output_base(video: VideoInfo, label: str, out_dir: str) -> str:
    base_name = f"{video.safe_title} [{video.bvid}]"
    if label:
        base_name += f" {label}"
    return os.path.join(out_dir, base_name)


def _write_outputs(
    segments: list,
    video: VideoInfo,
    part: VideoPart | None,
    label: str,
    out_dir: str,
    source: str,
    formats: list[str],
) -> list[str]:
    base = _output_base(video, label, out_dir)

    url = f"https://www.bilibili.com/video/{video.bvid}"
    if part and part.page > 1:
        url += f"?p={part.page}"
    md_title = video.title + (f"（{label}）" if label else "")

    written: list[str] = []
    for fmt in formats:
        if fmt == "srt":
            path = base + ".srt"
            srt_out.write_srt(path, segments)
        elif fmt == "md":
            path = base + ".md"
            md_out.write_markdown(
                path, segments, title=md_title, url=url, source=source, desc=video.desc
            )
        else:
            log.warning("Unsupported format: %s", fmt)
            continue
        written.append(path)
        log.info("  -> %s (%s)", path, source)
    return written


def _resolve_group_name(args: argparse.Namespace) -> Optional[str]:
    """解析 --group 的文件夹名，统一加 `group_` 前缀便于检索。

    --group NAME  -> group_NAME
    --group       -> 自动：search 用关键词、up 用 mid、其余用 group
    """
    g = getattr(args, "group", None)
    if g is None:
        return None
    if g == "__auto__":
        if getattr(args, "keyword", ""):
            g = args.keyword
        elif getattr(args, "target", ""):
            g = str(parse_mid(args.target) or args.target)
        else:
            g = "group"
    return "group_" + sanitize_name(str(g), fallback="group")


def _up_dir(args: argparse.Namespace, video: VideoInfo) -> str:
    """输出目录：指定 --group 时统一放 <out>/group_xxx/，否则按 <out>/UP主名/。"""
    group = getattr(args, "group_dir", None)
    up_dir = os.path.join(args.out, group if group else video.safe_owner)
    os.makedirs(up_dir, exist_ok=True)
    return up_dir


def _transcribe_video(client: BilibiliClient, video: VideoInfo, cid: int,
                      out_dir: str, keep_audio: bool, hotword: str,
                      label: str = "") -> list:
    # 中间文件（音频、16k wav）一律放临时目录，用完自动清理；
    # 仅 --keep-audio 时把原始 .m4a 保留到 UP 主目录。
    tmp = tempfile.TemporaryDirectory(prefix="bilisub_")
    try:
        if keep_audio:
            os.makedirs(out_dir, exist_ok=True)
            fname = f"{video.safe_title} [{video.bvid}]"
            if label:
                fname += f" {label}"
            m4a = os.path.join(out_dir, fname + ".m4a")
        else:
            m4a = os.path.join(tmp.name, "audio.m4a")
        log.info("  Downloading audio stream...")
        media.download_audio(client.get_audio_url(video.bvid, cid), m4a)
        wav = os.path.join(tmp.name, "audio_16k.wav")
        log.info("  Converting audio to 16 kHz WAV...")
        media.to_16k_wav(m4a, wav)
        return stt_engine.transcribe(wav, hotword=hotword)
    finally:
        tmp.cleanup()


def _part_label(part: VideoPart) -> str:
    part_title = sanitize_name(part.part, fallback="")
    return f"P{part.page}" + (f"-{part_title}" if part_title else "")


def _process_one(client: BilibiliClient, bvid: str, video: VideoInfo,
                 part: VideoPart, is_multi: bool, up_dir: str,
                 args: argparse.Namespace) -> None:
    """Process a single part (P) of a video."""
    label = _part_label(part) if is_multi else ""
    prefix = f"  [{label}] " if label else "  "

    # --skip-existing: 目标文件已存在则跳过，避免重复转写
    if args.skip_existing:
        base = _output_base(video, label, up_dir)
        existing = [
            f for f in _out_formats(args.formats) if os.path.exists(base + "." + f)
        ]
        if existing:
            log.info("%s已存在（%s），跳过", prefix, ",".join(existing))
            return

    segments: Optional[list] = None
    source = ""
    if not args.force_stt:
        try:
            segments = subtitles.fetch_segments(client, bvid, part.cid, prefer=args.lang)
        except subtitles.SubtitleQueryError as exc:
            # 查询失败 ≠ 没有字幕：跳过该视频，避免白白做几十分钟的本地转写
            log.warning("%s字幕接口查询失败（%s）——跳过以免无谓转写，可稍后重跑",
                        prefix, exc)
            _count_failure()
            return
        if segments:
            source = f"AI字幕（{args.lang}）"

    if segments is None:
        if args.no_stt:
            log.info("%s无AI字幕；已设置 --no-stt，跳过", prefix)
            return
        log.info("%s无AI字幕，启动本地语音转写（FunASR）...", prefix)
        segments = _transcribe_video(
            client, video, part.cid, up_dir, args.keep_audio, args.hotword, label
        )
        source = "STT（FunASR Paraformer）"

    if not segments:
        log.warning("%s未生成任何转写内容", prefix)
        return
    _write_outputs(segments, video, part if is_multi else None, label, up_dir,
                   source, _out_formats(args.formats))


def process_local_file(path: str, args: argparse.Namespace) -> None:
    """Transcribe a local video/audio file: extract audio -> FunASR -> srt/md."""
    if not os.path.isfile(path):
        log.error("文件不存在：%s", path)
        return
    video = VideoInfo(
        bvid="LOCAL",
        aid=0,
        cid=0,
        title=os.path.splitext(os.path.basename(path))[0],
        duration=0,
        owner_mid=0,
        owner_name="本地视频",
    )
    log.info("[本地] %s", path)
    with tempfile.TemporaryDirectory(prefix="bilisub_") as tmp:
        wav = os.path.join(tmp, "audio_16k.wav")
        if args.loudnorm:
            log.info("  提取音频并转换 16k WAV（响度归一化自动放大）...")
        elif args.volume and args.volume != 1.0:
            log.info("  提取音频并转换 16k WAV（音量放大 %.1fx）...", args.volume)
        else:
            log.info("  提取音频并转换 16k WAV（ffmpeg）...")
        media.to_16k_wav(path, wav, volume=args.volume, loudnorm=args.loudnorm)
        log.info("  本地转写（FunASR）...")
        segments = stt_engine.transcribe(wav, hotword=args.hotword)

    if not segments:
        log.warning("  未生成任何转写内容：%s", path)
        # 仍可导出放大版视频
        _maybe_export_amplified(path, args)
        return

    # 输出到视频文件同目录，同名 .srt/.md
    base = os.path.splitext(path)[0]
    source = "STT（FunASR Paraformer）本地文件"
    srt_out.write_srt(base + ".srt", segments)
    md_out.write_markdown(
        base + ".md", segments,
        title=video.title, url=os.path.abspath(path), source=source,
    )
    log.info("  -> %s.srt (%s)", base, source)
    log.info("  -> %s.md (%s)", base, source)
    _maybe_export_amplified(path, args)


def _maybe_export_amplified(path: str, args: argparse.Namespace) -> None:
    """--save-video 时，在视频同目录导出放大后的 mp4（音轨 loudnorm/volume）。"""
    if not args.save_video:
        return
    amp_path = os.path.splitext(path)[0] + "_放大.mp4"
    if os.path.exists(amp_path):
        log.info("  放大版视频已存在，跳过：%s", amp_path)
        return
    log.info("  导出放大版视频 -> %s ...", amp_path)
    media.amplify_video(path, amp_path, loudnorm=args.loudnorm, volume=args.volume)
    log.info("  -> %s", amp_path)


def process_video(client: BilibiliClient, bvid: str, args: argparse.Namespace) -> None:
    video = client.get_video_info(bvid)
    log.info(
        "[%s] %s（%s）by %s",
        bvid, video.title, _fmt_dur(video.duration), video.owner_name or "?",
    )
    up_dir = _up_dir(args, video)
    pages = video.pages or [VideoPart(cid=video.cid, page=1, part="", duration=video.duration)]
    is_multi = len(pages) > 1
    if is_multi:
        log.info("  共 %d P，将逐个下载", len(pages))
    for part in pages:
        try:
            _process_one(client, bvid, video, part, is_multi, up_dir, args)
        except Exception as exc:  # noqa: BLE001
            log.error("  处理失败：%s", exc)


# ----------------------------------------------------------------------
# UP主 crawling
# ----------------------------------------------------------------------
def _filter_tag(videos: list[VideoInfo], tag: str) -> list[VideoInfo]:
    if not tag:
        return videos
    t = tag.lower()
    return [v for v in videos if t in v.title.lower()]


def _parse_since(s: Optional[str]) -> float:
    """把 --since YYYY-MM-DD 解析为时间戳（当天 00:00）。"""
    if not s:
        return 0.0
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").timestamp()
    except ValueError:
        log.warning("--since 日期格式应为 YYYY-MM-DD，已忽略：%s", s)
        return 0.0


def _filter_videos(videos: list[VideoInfo], tag: str, since_ts: float) -> list[VideoInfo]:
    """按标题关键词 + 发布日期过滤。"""
    out = videos
    if tag:
        t = tag.lower()
        out = [v for v in out if t in v.title.lower()]
    if since_ts:
        out = [v for v in out if not v.pubdate or v.pubdate >= since_ts]
    return out


def _crawl_up_web(client: BilibiliClient, mid: int, args: argparse.Namespace) -> list[VideoInfo]:
    """Web 接口爬取（WBI 签名）。"""
    if args.all:
        page_size, limit = 30, 0  # 0 == unlimited
    else:
        page_size, limit = 50, args.recent or 30
    since = _parse_since(getattr(args, "since", ""))

    videos: list[VideoInfo] = []
    page = 1
    while True:
        batch = client.get_up_videos(mid, page=page, page_size=page_size)
        if not batch:
            break
        videos.extend(_filter_videos(batch, args.tag, since))
        if limit and len(videos) >= limit:
            return videos[:limit]
        # 视频按时间倒序，最后一页已早于 --since 则可提前结束
        if since and batch[-1].pubdate and batch[-1].pubdate < since:
            break
        if len(batch) < page_size:
            break
        page += 1
        time.sleep(1.0)  # 翻页间隔，降低触发风控概率
    return videos


def _crawl_up_app(client: BilibiliClient, mid: int, args: argparse.Namespace) -> list[VideoInfo]:
    """手机端接口爬取（appkey 签名，风控较弱）——Web 被 412 拦截时的备用通道。"""
    page_size = 20
    limit = 0 if args.all else (args.recent or 30)
    since = _parse_since(getattr(args, "since", ""))

    videos: list[VideoInfo] = []
    page = 1
    while True:
        batch, has_more = client.get_up_videos_app(mid, page=page, page_size=page_size)
        if not batch:
            break
        videos.extend(_filter_videos(batch, args.tag, since))
        if limit and len(videos) >= limit:
            return videos[:limit]
        if since and batch[-1].pubdate and batch[-1].pubdate < since:
            break
        if not has_more:
            break
        page += 1
        time.sleep(1.0)
    return videos


def crawl_up(client: BilibiliClient, mid: int, args: argparse.Namespace) -> list[VideoInfo]:
    """爬取 UP主视频列表：优先 Web 接口，被风控拦截时自动切换手机端接口重爬。"""
    try:
        return _crawl_up_web(client, mid, args)
    except Exception as exc:  # noqa: BLE001
        log.warning("Web 接口爬取 UP主失败（%s），改用手机端接口重新爬取...", exc)
        return _crawl_up_app(client, mid, args)


MAX_SEARCH_PAGES = 50  # B站搜索接口最多 50 页


def crawl_search(client: BilibiliClient, keyword: str, maximum: int) -> list[VideoInfo]:
    """按关键词搜索，按接口返回的总页数翻页（避免过早停止）。"""
    videos: list[VideoInfo] = []
    page = 1
    while len(videos) < maximum and page <= MAX_SEARCH_PAGES:
        batch, num_pages = client.search_videos_page(keyword, page=page)
        videos.extend(batch)
        if num_pages and page >= num_pages:
            break
        if not batch:
            break  # 本页没有有效视频，结束
        page += 1
        time.sleep(0.5)  # 翻页间隔
    return videos[:maximum]


# ----------------------------------------------------------------------
# Multi-format list dispatch (used by `batch`)
# ----------------------------------------------------------------------
# 本地媒体文件扩展名（list.txt 里出现这类行时按本地文件转写处理）
MEDIA_EXTS = (
    ".mp4", ".mkv", ".flv", ".mov", ".avi", ".webm", ".ts",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma",
)


def classify_target(line: str):
    """识别列表一行的类型：(kind, value)。kind ∈ local / video / up / search。"""
    s = line.strip()
    # 去掉首尾引号（路径可能带引号）
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    low = s.lower()
    if low.startswith("search:"):
        kw = s[len("search:"):].strip()
        return ("search", kw) if kw else None
    if low.startswith("up:"):
        mid = parse_mid(s[len("up:"):])
        return ("up", mid) if mid else None
    # 本地视频/音频文件：存在，或带媒体扩展名
    if os.path.isfile(s):
        return ("local", s)
    if low.endswith(MEDIA_EXTS):
        return ("local", s)
    bvid = parse_bvid(s)
    if bvid:
        return ("video", bvid)
    mid = parse_mid(s)
    if mid:
        return ("up", mid)
    return None


# 单次运行失败超过该数量即告警（通常是 Cookie/令牌失效）并中断剩余任务
FAIL_ALERT_THRESHOLD = 10
_failures = 0


def _log_threshold_alert() -> None:
    log.error("=" * 64)
    log.error("⚠ 已失败 %d 项（超过阈值 %d）—— Cookie/令牌可能已过期！",
              _failures, FAIL_ALERT_THRESHOLD)
    log.error("  请更新 cookie.txt 后重新运行（已下载的会自动跳过）")
    log.error("=" * 64)


def _count_failure() -> None:
    """记录一次失败；首次越过阈值时给出醒目告警。"""
    global _failures
    _failures += 1
    if _failures == FAIL_ALERT_THRESHOLD + 1:
        _log_threshold_alert()


def _safe_run(fn, label: str) -> bool:
    """执行单个处理项并捕获异常，单个失败不中断后续项。"""
    try:
        fn()
        return True
    except Exception as exc:  # noqa: BLE001
        _count_failure()
        log.error("处理失败 %s：%s", label, exc)
        return False


def _process_videos_guarded(client: BilibiliClient, videos: list[VideoInfo],
                            args: argparse.Namespace) -> None:
    """逐个下载；失败数超过阈值时中断剩余任务（避免令牌失效后无效刷请求）。"""
    for v in videos:
        if _failures > FAIL_ALERT_THRESHOLD:
            log.error("失败过多（%d 项），已中断本次剩余任务；请更新 cookie.txt 后重跑",
                      _failures)
            return
        _safe_run(lambda: process_video(client, v.bvid, args), v.bvid)


def _dispatch_target(client: BilibiliClient, target: str, args: argparse.Namespace) -> None:
    """按列表行类型分发：本地文件 / 视频 / UP主 / 搜索。"""
    classified = classify_target(target)
    if not classified:
        log.warning("跳过无法识别的行：%s", target)
        return
    kind, value = classified
    if kind == "local":
        _safe_run(lambda: process_local_file(value, args), value)
    elif kind == "video":
        _safe_run(lambda: process_video(client, value, args), value)
    elif kind == "up":
        videos = crawl_up(client, value, args)
        log.info("UP主 %s：共 %d 个视频", value, len(videos))
        _process_videos_guarded(client, videos, args)
    else:  # search
        videos = crawl_search(client, value, args.max)
        log.info("搜索“%s”：共 %d 个视频", value, len(videos))
        _process_videos_guarded(client, videos, args)


# ----------------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------------
def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def cmd_clean(args: argparse.Namespace) -> int:
    """One-click cleanup: pycache / leftover .part / stale temp dirs.
    With --models, also remove the STT model cache (~2 GB)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    freed = 0
    removed = 0

    def _skip(dirpath: str) -> bool:
        parts = dirpath.split(os.sep)
        return ".venv" in parts or "models_cache" in parts

    # 1. __pycache__ directories
    for dirpath, dirnames, _filenames in os.walk(root):
        if _skip(dirpath):
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) == "__pycache__":
            freed += _dir_size(dirpath)
            shutil.rmtree(dirpath, ignore_errors=True)
            removed += 1

    # 2. leftover partial downloads (*.part)
    for dirpath, _dirnames, filenames in os.walk(root):
        if _skip(dirpath):
            continue
        for fn in filenames:
            if fn.endswith(".part"):
                p = os.path.join(dirpath, fn)
                try:
                    freed += os.path.getsize(p)
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass

    # 3. stale transcription temp dirs in the system temp folder
    tmp_root = tempfile.gettempdir()
    try:
        for name in os.listdir(tmp_root):
            if name.startswith("bilisub_"):
                p = os.path.join(tmp_root, name)
                if os.path.isdir(p):
                    freed += _dir_size(p)
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
    except OSError:
        pass

    log.info("清理完成：删除 %d 项，释放 %.1f MB", removed, freed / 1048576)

    if args.models:
        mc = os.path.join(root, "models_cache")
        if os.path.isdir(mc):
            size = _dir_size(mc)
            shutil.rmtree(mc, ignore_errors=True)
            log.info("已删除模型缓存 models_cache（%.1f MB），下次 STT 将重新下载", size / 1048576)
        else:
            log.info("models_cache 不存在，无需删除")
    return 0


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bilibili-decoder",
        description="本地 B 站字幕下载工具：优先下载 AI 字幕，无字幕时用 FunASR 本地转写，"
        "输出带时间轴的 .srt 和 .md。",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="subtitles", help="输出目录（默认 subtitles）")
    common.add_argument("--formats", default=None, help="输出格式，逗号分隔：srt,md（默认 srt,md）")
    common.add_argument("--no-stt", action="store_true", help="仅下载已有AI字幕，不做本地转写")
    common.add_argument("--force-stt", action="store_true", help="强制本地转写，忽略已有AI字幕")
    common.add_argument(
        "--skip-existing", action="store_true",
        help="目标文件已存在则跳过（避免重复转写/下载）",
    )
    common.add_argument("--lang", default="zh", help="优先字幕语言（默认 zh）")
    common.add_argument("--hotword", default="", help="STT 热词，逗号分隔，如：电机,机器人")
    common.add_argument("--keep-audio", action="store_true", help="保留下载的音频文件")
    common.add_argument("--cookie", default="", help="B站 Cookie 字符串（如 SESSDATA=...）")
    common.add_argument(
        "--cookie-file", default="",
        help="从文件读取 Cookie 字符串（更安全，文件内只放 Cookie 内容）",
    )
    common.add_argument(
        "--group", nargs="?", const="__auto__", default=None, metavar="NAME",
        help="把本次全部文件统一放入 <输出目录>/group_<名称>/（不加值则自动用关键词/UP主 mid）",
    )

    # 本地文件转写相关选项（local 命令与 batch 列表中的本地文件条目共用）
    local_opts = argparse.ArgumentParser(add_help=False)
    local_opts.add_argument(
        "--volume", type=float, default=1.0,
        help="音频放大倍数（默认 1.0 不变；音频很轻时可用如 5.0/10.0）",
    )
    local_opts.add_argument(
        "--loudnorm", action="store_true",
        help="响度归一化自动放大（音频很轻时推荐，自动限幅防削波）",
    )
    local_opts.add_argument(
        "--save-video", action="store_true",
        help="同时导出放大版视频（同目录 原名_放大.mp4，音轨 loudnorm/volume）",
    )

    p_video = sub.add_parser("video", parents=[common], help="下载指定视频的字幕")
    p_video.add_argument("targets", nargs="+", help="视频链接或 BVID，可多个")

    p_batch = sub.add_parser(
        "batch", parents=[common, local_opts],
        help="从列表文件批量处理（支持本地文件/视频/UP主/搜索混合格式）",
    )
    p_batch.add_argument("-f", "--file", required=True, help="列表文件路径")
    p_batch.add_argument("--all", action="store_true", help="列表中的 UP 主条目：抓取全部视频")
    p_batch.add_argument("--recent", type=int, default=0, help="列表中的 UP 主条目：抓取最近 N 个（默认 30）")
    p_batch.add_argument("--tag", default="", help="列表中的 UP 主条目：仅处理标题含该关键词的视频")
    p_batch.add_argument("--since", default="", help="列表中的 UP 主条目：仅处理该日期之后发布的视频（YYYY-MM-DD）")
    p_batch.add_argument("--max", type=int, default=20, help="列表中的 search 条目：最多处理结果数")

    p_up = sub.add_parser("up", parents=[common], help="爬取某 UP 主的视频字幕")
    p_up.add_argument("target", help="UP主 mid 或空间页链接")
    mode = p_up.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="爬取该 UP 主全部视频")
    mode.add_argument("--recent", type=int, default=0, help="爬取最近 N 个视频（默认 30）")
    p_up.add_argument("--tag", default="", help="仅处理标题包含该关键词的视频")
    p_up.add_argument("--since", default="", help="仅处理该日期之后发布的视频（YYYY-MM-DD）")

    p_search = sub.add_parser("search", parents=[common], help="按关键词搜索视频并下载字幕")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--max", type=int, default=20, help="最多处理结果数（默认 20）")

    p_clean = sub.add_parser("clean", help="一键清理临时文件/缓存")
    p_clean.add_argument(
        "--models", action="store_true",
        help="同时删除 STT 模型缓存 models_cache（约 2GB，下次转写需重新下载）",
    )

    p_local = sub.add_parser(
        "local", parents=[common, local_opts],
        help="转写本地视频/音频文件（提取音频 + FunASR，输出同名 srt/md）",
    )
    p_local.add_argument("targets", nargs="+", help="本地文件路径，可多个")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    global _failures
    _failures = 0
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.command == "clean":
        return cmd_clean(args)

    # --group：统一输出文件夹（带 group_ 前缀）
    args.group_dir = _resolve_group_name(args)
    if args.group_dir:
        log.info("本次全部文件统一输出到：%s", os.path.join(args.out, args.group_dir))

    cookie = args.cookie
    if args.cookie_file:
        try:
            with open(args.cookie_file, encoding="utf-8") as fh:
                cookie = "\n".join(
                    ln.strip()
                    for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")
                )
        except OSError as exc:
            log.warning(
                "Cookie 文件无法读取（%s），将以匿名模式继续，可能拿不到现成字幕", exc
            )
    client = BilibiliClient(cookie=cookie)
    os.makedirs(args.out, exist_ok=True)

    if args.command == "video":
        targets = args.targets
    elif args.command == "batch":
        try:
            with open(args.file, encoding="utf-8") as fh:
                targets = [
                    ln.strip()
                    for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")
                ]
        except OSError as exc:
            log.error("无法读取列表文件：%s", exc)
            return 1
        for target in targets:
            try:
                _dispatch_target(client, target, args)
            except Exception as exc:  # noqa: BLE001
                log.error("处理失败 %s：%s", target, exc)
        return 0
    elif args.command == "up":
        mid = parse_mid(args.target)
        if not mid:
            log.error("无法解析 UP 主目标：%s", args.target)
            return 1
        videos = crawl_up(client, mid, args)
        log.info("共找到 %d 个视频（UP主 mid=%s）", len(videos), mid)
        _process_videos_guarded(client, videos, args)
        return 0
    elif args.command == "search":
        videos = crawl_search(client, args.keyword, args.max)
        log.info("关键词“%s”共找到 %d 个视频", args.keyword, len(videos))
        _process_videos_guarded(client, videos, args)
        return 0
    elif args.command == "local":
        for target in args.targets:
            try:
                process_local_file(target, args)
            except Exception as exc:  # noqa: BLE001
                log.error("处理失败 %s：%s", target, exc)
        return 0
    else:
        log.error("未知命令：%s", args.command)
        return 1

    for target in targets:
        bvid = parse_bvid(target)
        if not bvid:
            log.warning("跳过无效目标：%s", target)
            continue
        try:
            process_video(client, bvid, args)
        except Exception as exc:  # noqa: BLE001
            log.error("处理失败 %s：%s", target, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Scan videos and report which have server-side subtitles (AI or uploader CC).

Tests the "ready-made subtitle" path before bulk download. Optionally accepts
a cookie string via --cookie to compare logged-in vs anonymous results.

Usage:
    .venv\\Scripts\\python.exe scripts\\scan_subtitles.py
    .venv\\Scripts\\python.exe scripts\\scan_subtitles.py --cookie "SESSDATA=..."
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bilibili_decoder.api.client import BilibiliClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookie", default="", help="Bilibili cookie string")
    parser.add_argument(
        "--cookie-file", default="", help="read cookie string from a file"
    )
    parser.add_argument("--max", type=int, default=20, help="max videos to scan")
    args = parser.parse_args()

    cookie = args.cookie
    if args.cookie_file:
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookie = "\n".join(
                ln.strip()
                for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")
            )

    client = BilibiliClient(cookie=cookie)
    keywords = ["电机", "机器人", "科学史", "科普", "深度学习", "自动驾驶", "芯片", "物理学"]

    seen: set[str] = set()
    videos = []
    for kw in keywords:
        if len(videos) >= args.max:
            break
        try:
            for v in client.search_videos(kw, page=1):
                if v.bvid not in seen:
                    seen.add(v.bvid)
                    videos.append(v)
                if len(videos) >= args.max:
                    break
        except Exception as exc:  # noqa: BLE001
            print(f"[search {kw}] failed: {exc}")

    print(f"Scanning {len(videos)} videos ...")
    with_sub = 0
    for v in videos:
        try:
            info = client.get_video_info(v.bvid)  # resolves cid
            subs = client.get_subtitle_list(v.bvid, info.cid)
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] {v.bvid} {v.title[:24]}: {exc}")
            continue
        if subs:
            with_sub += 1
            detail = ", ".join(
                f"{s.lan}({'UP上传' if s.ai_type == 0 else 'AI'})" for s in subs
            )
            print(f"  [有字幕] {v.bvid} {v.title[:28]} -> {detail}")
        else:
            print(f"  [无字幕] {v.bvid} {v.title[:28]}")
    print(f"\n结果：{with_sub}/{len(videos)} 个视频存在服务器端字幕（登录={bool(args.cookie)}）")


if __name__ == "__main__":
    main()

"""Verify login cookie and check a UP主's video subtitle availability.

Usage: .venv\\Scripts\\python.exe scripts\\check_up.py <mid-or-bvid>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bilibili_decoder.api.client import BilibiliClient, parse_bvid, parse_mid  # noqa: E402


def _load_cookie(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return "\n".join(
            ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")
        )


def main() -> None:
    cookie = _load_cookie(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookie.txt"))
    client = BilibiliClient(cookie=cookie)

    # login check
    nav = client._get_json("https://api.bilibili.com/x/web-interface/nav").get("data", {})
    print("登录状态 isLogin:", nav.get("isLogin"), "| 用户名:", nav.get("uname", ""))
    if not nav.get("isLogin"):
        print("!! Cookie 无效或已过期，字幕接口可能仍拿不到")
        return

    target = sys.argv[1] if len(sys.argv) > 1 else "BV1AiuJ6QE9q"
    mid = parse_mid(target)
    if not mid:
        info = client.get_video_info(parse_bvid(target))
        mid = info.owner_mid
        print(f"视频 {info.bvid} 的 UP 主：{info.owner_name} (mid={mid})")
    else:
        print(f"目标 UP 主 mid={mid}")

    videos = []
    page = 1
    while True:
        batch = client.get_up_videos(mid, page=page, page_size=30)
        if not batch:
            break
        videos.extend(batch)
        if len(batch) < 30:
            break
        page += 1
    print(f"该 UP 主共 {len(videos)} 个视频\n")

    with_sub = 0
    for v in videos:
        try:
            info = client.get_video_info(v.bvid)  # ensure fresh cid
            subs = client.get_subtitle_list(v.bvid, info.cid)
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] {v.bvid}: {exc}")
            continue
        if subs:
            with_sub += 1
            detail = ", ".join(
                f"{s.lan}({'UP上传' if s.ai_type == 0 else 'AI'})" for s in subs
            )
            print(f"  [有字幕] {v.bvid} {v.title[:40]} -> {detail}")
        else:
            print(f"  [无字幕] {v.bvid} {v.title[:40]}")
    print(f"\n结果：{with_sub}/{len(videos)} 个视频有服务器端字幕（已登录）")


if __name__ == "__main__":
    main()

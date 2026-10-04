"""Fetch and parse Bilibili AI subtitles."""

from __future__ import annotations

import logging
from typing import Optional

from ..api.client import BilibiliClient
from ..api.models import SubtitleSegment

log = logging.getLogger(__name__)


class SubtitleQueryError(RuntimeError):
    """字幕接口查询失败（网络/风控）。

    注意：这只代表"没查到"，**不代表该视频没有字幕** —— 调用方不应据此
    回退到本地转写（可能白白转写一个本来有字幕的视频）。
    """


def fetch_segments(
    client: BilibiliClient, bvid: str, cid: int, prefer: str = "zh"
) -> Optional[list[SubtitleSegment]]:
    """返回字幕分段；接口正常但没有字幕时返回 None，查询失败则抛异常。"""
    try:
        subs = client.get_subtitle_list(bvid, cid)
    except Exception as exc:
        raise SubtitleQueryError(f"{bvid}: {exc}") from exc
    if not subs:
        return None  # 接口正常返回空 —— 确实没有字幕

    chosen = next((s for s in subs if s.lan == prefer), subs[0])
    log.debug("Using subtitle %s (%s) for %s", chosen.lan, chosen.lan_doc, bvid)
    try:
        body = client.fetch_subtitle_json(chosen.url)
    except Exception as exc:
        log.warning("Failed to fetch subtitle JSON for %s: %s", bvid, exc)
        return None

    segments: list[SubtitleSegment] = []
    for item in body:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        try:
            start = float(item["from"])
            end = float(item["to"])
        except (KeyError, TypeError, ValueError):
            continue
        segments.append(SubtitleSegment(start=start, end=end, text=content))
    return segments or None

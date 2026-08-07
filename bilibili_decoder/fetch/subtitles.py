"""Fetch and parse Bilibili AI subtitles."""

from __future__ import annotations

import logging
from typing import Optional

from ..api.client import BilibiliClient
from ..api.models import SubtitleSegment

log = logging.getLogger(__name__)


def fetch_segments(
    client: BilibiliClient, bvid: str, cid: int, prefer: str = "zh"
) -> Optional[list[SubtitleSegment]]:
    """Return subtitle segments for a video, or None if none is usable."""
    try:
        subs = client.get_subtitle_list(bvid, cid)
    except Exception as exc:
        log.warning("Failed to query subtitle list for %s: %s", bvid, exc)
        return None
    if not subs:
        return None

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

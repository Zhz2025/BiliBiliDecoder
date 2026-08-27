"""Markdown transcript writer — timestamped lines, readable like the sample doc."""

from __future__ import annotations

from ..api.models import SubtitleSegment


def format_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def to_markdown(
    segments: list[SubtitleSegment],
    title: str = "",
    url: str = "",
    source: str = "",
    desc: str = "",
) -> str:
    lines: list[str] = []
    if title:
        lines.append(f"# {title}")
    if url:
        lines.append("")
        lines.append(f"> {url}")
    if source:
        lines.append("")
        lines.append(f"> 字幕来源：{source}")
    if desc and desc.strip():
        lines.append("")
        lines.append("## 简介")
        lines.append("")
        for dl in str(desc).strip().splitlines():
            lines.append(dl)
    lines.append("")
    lines.append("## 完整口播")
    lines.append("")
    for seg in segments:
        lines.append(f"{format_mmss(seg.start)} {seg.text}")
    lines.append("")
    return "\n".join(lines)


def write_markdown(
    path: str,
    segments: list[SubtitleSegment],
    title: str = "",
    url: str = "",
    source: str = "",
    desc: str = "",
) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_markdown(segments, title=title, url=url, source=source, desc=desc))

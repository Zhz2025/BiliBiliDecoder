"""SRT subtitle writer with light segment merging."""

from __future__ import annotations

from ..api.models import SubtitleSegment


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _join_text(a: str, b: str) -> str:
    """Concatenate two fragments, inserting a space between Latin words."""
    if a and b and a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum():
        return a + " " + b
    return a + b


def merge_segments(
    segments: list[SubtitleSegment],
    max_gap: float = 0.4,
    max_duration: float = 9.0,
) -> list[SubtitleSegment]:
    """Merge adjacent segments with tiny gaps so SRT lines don't flicker."""
    if not segments:
        return []
    merged: list[SubtitleSegment] = []
    for seg in segments:
        if not merged:
            merged.append(SubtitleSegment(seg.start, seg.end, seg.text))
            continue
        last = merged[-1]
        gap = seg.start - last.end
        new_end = max(last.end, seg.end)
        if 0 <= gap <= max_gap and (new_end - last.start) <= max_duration:
            last.end = new_end
            last.text = _join_text(last.text, seg.text)
        else:
            merged.append(SubtitleSegment(seg.start, seg.end, seg.text))
    return merged


def to_srt(segments: list[SubtitleSegment], merge: bool = True) -> str:
    segs = merge_segments(segments) if merge else segments
    lines: list[str] = []
    for i, seg in enumerate(segs, start=1):
        lines.append(str(i))
        lines.append(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def write_srt(path: str, segments: list[SubtitleSegment], merge: bool = True) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_srt(segments, merge=merge))

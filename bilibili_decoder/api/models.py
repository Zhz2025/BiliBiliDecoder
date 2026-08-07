"""Data models shared across the tool."""

from __future__ import annotations

from dataclasses import dataclass, field

# Characters not allowed in Windows file/folder names.
_INVALID_NAME_CHARS = '<>:"/\\|?*'


def sanitize_name(text: str, fallback: str = "unknown") -> str:
    """Sanitize arbitrary text into a safe file/folder name."""
    cleaned = "".join("_" if c in _INVALID_NAME_CHARS else c for c in str(text))
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.rstrip(". ")
    return cleaned.strip() or fallback


@dataclass
class VideoInfo:
    bvid: str
    aid: int
    cid: int
    title: str
    duration: int  # seconds
    owner_mid: int
    owner_name: str
    desc: str = ""
    pic: str = ""
    pubdate: int = 0

    @property
    def safe_title(self) -> str:
        """Title sanitized for use as a filename."""
        return sanitize_name(self.title, fallback=self.bvid)

    @property
    def safe_owner(self) -> str:
        """UP主 name sanitized for use as a folder name."""
        return sanitize_name(self.owner_name, fallback=f"UP_{self.owner_mid or 'unknown'}")


@dataclass
class SubtitleInfo:
    lan: str
    lan_doc: str
    url: str  # absolute URL to the subtitle JSON
    ai_type: int = 1  # 0 = 用户/UP主上传, 1 = AI自动生成


@dataclass
class SubtitleSegment:
    start: float  # seconds
    end: float    # seconds
    text: str

    def __post_init__(self) -> None:
        self.text = self.text.strip()

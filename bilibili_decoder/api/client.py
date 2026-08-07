"""Minimal Bilibili API client with WBI signing support."""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests

from .models import SubtitleInfo, VideoInfo
from .wbi import enc_wbi, extract_key_from_url

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
MID_RE = re.compile(r"(?:space\.bilibili\.com/|mid=)(\d+)")

REFERER = "https://www.bilibili.com/"


def parse_bvid(text: str) -> Optional[str]:
    m = BVID_RE.search(text)
    return m.group(1) if m else None


def parse_mid(text: str) -> Optional[int]:
    m = MID_RE.search(text)
    if m:
        return int(m.group(1))
    if text.strip().isdigit():
        return int(text.strip())
    return None


def _parse_length(length: str) -> int:
    """Parse a 'MM:SS' / 'H:MM:SS' duration string into seconds."""
    secs = 0
    for part in str(length).split(":"):
        secs = secs * 60 + int(part or 0)
    return secs


class BilibiliClient:
    """Thin wrapper around Bilibili's web API."""

    def __init__(self, cookie: str = "", timeout: float = 15.0, retries: int = 3) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Referer": REFERER})
        if cookie:
            self.session.headers["Cookie"] = cookie
        self.timeout = timeout
        self.retries = retries
        self._wbi_keys: Optional[dict] = None
        self._ensure_buvid3()

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------
    def _ensure_buvid3(self) -> None:
        """Obtain a buvid3 cookie if not present (required by many endpoints)."""
        if "buvid3" in self.session.cookies:
            return
        try:
            resp = self.session.get(
                "https://api.bilibili.com/x/frontend/finger/spi", timeout=self.timeout
            )
            data = (resp.json() or {}).get("data", {})
            buvid3 = data.get("b_3")
            if buvid3:
                self.session.cookies.set("buvid3", buvid3, domain=".bilibili.com")
                self.session.cookies.set("buvid4", data.get("b_4", ""), domain=".bilibili.com")
        except Exception:
            log.debug("Failed to obtain buvid3", exc_info=True)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                resp = self.session.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.debug("Request failed (%s): %s", url, exc)
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Request failed after {self.retries} tries: {url}") from last_exc

    def _get_json(self, url: str, params: Optional[dict] = None, signed: bool = False) -> dict:
        if signed:
            params = self._sign(params or {})
        resp = self._request("GET", url, params=params)
        return resp.json()

    def _sign(self, params: dict) -> dict:
        if self._wbi_keys is None:
            self._wbi_keys = self._fetch_wbi_keys()
        return enc_wbi(params, self._wbi_keys["img_key"], self._wbi_keys["sub_key"])

    def _fetch_wbi_keys(self) -> dict:
        data = self._get_json("https://api.bilibili.com/x/web-interface/nav").get("data", {})
        wbi = data.get("wbi_img", {})
        img_url = wbi.get("img_url", "")
        sub_url = wbi.get("sub_url", "")
        if not img_url or not sub_url:
            raise RuntimeError("Failed to obtain WBI keys (login may be required)")
        return {
            "img_key": extract_key_from_url(img_url),
            "sub_key": extract_key_from_url(sub_url),
        }

    # ------------------------------------------------------------------
    # Video info
    # ------------------------------------------------------------------
    def get_video_info(self, bvid: str) -> VideoInfo:
        data = self._get_json(
            "https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}
        ).get("data")
        if not data:
            raise RuntimeError(f"Video not found or unavailable: {bvid}")
        return VideoInfo(
            bvid=data["bvid"],
            aid=data["aid"],
            cid=data["cid"],
            title=data["title"],
            duration=int(data.get("duration", 0)),
            owner_mid=data.get("owner", {}).get("mid", 0),
            owner_name=data.get("owner", {}).get("name", ""),
            desc=data.get("desc", ""),
            pic=data.get("pic", ""),
            pubdate=int(data.get("pubdate", 0)),
        )

    # ------------------------------------------------------------------
    # Subtitles
    # ------------------------------------------------------------------
    def get_subtitle_list(self, bvid: str, cid: int) -> list[SubtitleInfo]:
        data = self._get_json(
            "https://api.bilibili.com/x/player/wbi/v2",
            params={"bvid": bvid, "cid": cid},
            signed=True,
        ).get("data") or {}
        subs: list[SubtitleInfo] = []
        for item in (data.get("subtitle", {}) or {}).get("subtitles", []) or []:
            url = item.get("subtitle_url", "")
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            subs.append(
                SubtitleInfo(
                    lan=item.get("lan", ""),
                    lan_doc=item.get("lan_doc", ""),
                    url=url,
                    ai_type=int(item.get("ai_type", 1) or 1),
                )
            )
        return subs

    def fetch_subtitle_json(self, url: str) -> list[dict]:
        resp = self._request("GET", url)
        return (resp.json() or {}).get("body", [])

    # ------------------------------------------------------------------
    # Audio stream (DASH)
    # ------------------------------------------------------------------
    def get_audio_url(self, bvid: str, cid: int) -> str:
        data = self._get_json(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bvid, "cid": cid, "fnval": 16, "fnver": 0, "fourk": 1},
            signed=True,
        ).get("data") or {}
        audios = ((data.get("dash") or {}).get("audio")) or []
        if not audios:
            raise RuntimeError(f"No DASH audio stream available for {bvid}")
        # Prefer the highest quality stream, then fall back to backup URLs.
        audios.sort(key=lambda a: int(a.get("id", 0) or 0), reverse=True)
        candidates = [audios[0].get("baseUrl", "")] + list(audios[0].get("backupUrl", []) or [])
        for cand in candidates:
            if cand:
                return cand
        raise RuntimeError(f"No audio URL available for {bvid}")

    # ------------------------------------------------------------------
    # UP主 videos
    # ------------------------------------------------------------------
    def get_up_videos(self, mid: int, page: int = 1, page_size: int = 30) -> list[VideoInfo]:
        data = self._get_json(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params={"mid": mid, "pn": page, "ps": page_size},
            signed=True,
        ).get("data") or {}
        vlist = (data.get("list", {}) or {}).get("vlist", []) or []
        videos: list[VideoInfo] = []
        for v in vlist:
            videos.append(
                VideoInfo(
                    bvid=v["bvid"],
                    aid=int(v.get("aid", 0)),
                    cid=int(v.get("cid", 0) or 0),
                    title=v.get("title", ""),
                    duration=_parse_length(v.get("length", "0:00")),
                    owner_mid=mid,
                    owner_name="",
                    pic=v.get("pic", ""),
                    pubdate=int(v.get("created", 0)),
                )
            )
        return videos

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search_videos(self, keyword: str, page: int = 1, page_size: int = 20) -> list[VideoInfo]:
        data = self._get_json(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={
                "search_type": "video",
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
            },
        ).get("data") or {}
        results = data.get("result", []) or []
        videos: list[VideoInfo] = []
        for r in results:
            if r.get("type") != "video":
                continue
            bvid = r.get("bvid", "")
            if not bvid:
                continue
            videos.append(
                VideoInfo(
                    bvid=bvid,
                    aid=int(r.get("aid", 0)),
                    cid=0,  # resolved later via get_video_info
                    title=re.sub(r"<[^>]+>", "", r.get("title", "")),
                    duration=_parse_length(str(r.get("duration", "0"))),
                    owner_mid=int(r.get("mid", 0) or 0),
                    owner_name=r.get("author", ""),
                    desc=r.get("description", ""),
                    pic=r.get("pic", ""),
                    pubdate=int(r.get("pubdate", 0) or 0),
                )
            )
        return videos

"""Minimal Bilibili API client with WBI signing support."""

from __future__ import annotations

import hashlib
import logging
import re
import time
import urllib.parse
from typing import Optional

import requests

from .models import SubtitleInfo, VideoInfo, VideoPart
from .wbi import enc_wbi, extract_key_from_url

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
MID_RE = re.compile(r"(?:space\.bilibili\.com/|mid=)(\d+)")

REFERER = "https://www.bilibili.com/"

# 手机端 API 签名用的公开 appkey/appsec（用于风控较弱的备用通道）
APPKEY = "1d8b6e7d45233436"
APPSEC = "560c52ccd288fed045859ed18bffd973"


def appsign(params: dict) -> dict:
    """手机端 API 签名：appkey + ts + sign=md5(sorted_query + appsec)。"""
    params = dict(params)
    params["appkey"] = APPKEY
    params["ts"] = int(time.time())
    query = urllib.parse.urlencode(dict(sorted(params.items())))
    params["sign"] = hashlib.md5((query + APPSEC).encode("utf-8")).hexdigest()
    return params


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

    def __init__(self, cookie: str = "", timeout: float = 15.0, retries: int = 8) -> None:
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

    def _request(self, method: str, url: str, params=None, sign: bool = False,
                 max_wait: float = 6.0, **kwargs) -> requests.Response:
        """HTTP 请求，带自动重试。

        重要：`sign=True` 时**每次重试都会重新生成 WBI 签名**（新的 wts/w_rid）。
        因为 B 站风控是随机拦截的——复用旧签名重试可能一直失败，换个新签名
        往往就能通过。
        """
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req_params = self._sign(dict(params or {})) if sign else params
                resp = self.session.request(method, url, params=req_params, **kwargs)
                # B站风控会随机返回 412（拦截图）
                if resp.status_code == 412:
                    raise RuntimeError("HTTP 412（B站风控拦截，稍后重试）")
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.debug("Request failed (%s): %s", url, exc)
                if attempt < self.retries - 1:
                    time.sleep(min(0.8 * (attempt + 1), max_wait))
        raise RuntimeError(
            f"Request failed after {self.retries} tries ({last_exc}): {url}"
        ) from last_exc

    def _get_json(self, url: str, params: Optional[dict] = None, signed: bool = False) -> dict:
        resp = self._request("GET", url, params=params, sign=signed)
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
        pages = [
            VideoPart(
                cid=int(p.get("cid", 0) or 0),
                page=int(p.get("page", 1) or 1),
                part=p.get("part", ""),
                duration=int(p.get("duration", 0) or 0),
            )
            for p in (data.get("pages") or [])
        ]
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
            pages=pages,
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

    def get_up_videos_app(
        self, mid: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[VideoInfo], bool]:
        """手机端 API 获取 UP主视频（appkey 签名，风控较弱）。

        返回 (视频列表, 是否还有下一页)。
        """
        params = appsign({
            "vmid": mid, "ps": page_size, "pn": page, "order": "pubdate",
            "platform": "android", "mobi_app": "android", "build": 7001400,
        })
        resp = self._request(
            "GET", "https://app.bilibili.com/x/v2/space/archive/cursor", params=params
        )
        data = (resp.json() or {}).get("data") or {}
        videos: list[VideoInfo] = []
        for it in data.get("item") or []:
            bvid = it.get("bvid", "")
            if not bvid:
                continue
            videos.append(
                VideoInfo(
                    bvid=bvid,
                    aid=int(it.get("param", 0) or 0),
                    cid=int(it.get("first_cid", 0) or 0),
                    title=it.get("title", ""),
                    duration=int(it.get("duration", 0) or 0),
                    owner_mid=mid,
                    owner_name=it.get("author", ""),
                    pic=it.get("cover", ""),
                    pubdate=int(it.get("ctime", 0) or 0),
                )
            )
        return videos, bool(data.get("has_next", 0))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search_videos_page(
        self, keyword: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[VideoInfo], int]:
        """搜索一页，返回 (视频列表, 总页数)。

        注意：每页原始结果会混有"课堂""直播"等非普通视频条目（会被过滤掉），
        所以**不能用过滤后的条数判断是否还有下一页**，必须用接口返回的
        `numPages` 来推进分页。
        """
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
        return videos, int(data.get("numPages", 0) or 0)

    def search_videos(self, keyword: str, page: int = 1, page_size: int = 20) -> list[VideoInfo]:
        """搜索一页，只返回视频列表（兼容旧调用）。"""
        return self.search_videos_page(keyword, page=page, page_size=page_size)[0]

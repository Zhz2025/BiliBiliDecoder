"""Download audio streams and convert them with ffmpeg."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_FFMPEG_BIN: Optional[str] = None


def find_ffmpeg() -> Optional[str]:
    """Locate an ffmpeg binary: system PATH first, then imageio-ffmpeg bundle."""
    global _FFMPEG_BIN
    if _FFMPEG_BIN:
        return _FFMPEG_BIN
    system = shutil.which("ffmpeg")
    if system:
        _FFMPEG_BIN = system
        return system
    try:
        import imageio_ffmpeg

        _FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG_BIN
    except Exception:
        return None


def download_file(url: str, dest: str, headers: Optional[dict] = None,
                  chunk_size: int = 1 << 20) -> str:
    """Stream a file to disk (atomic via .part), returning the destination path."""
    resp = requests.get(url, headers=headers, stream=True, timeout=30)
    resp.raise_for_status()
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                fh.write(chunk)
    os.replace(tmp, dest)
    return dest


def download_audio(url: str, dest_m4a: str) -> str:
    """Download an audio stream with Bilibili-required anti-leech headers."""
    return download_file(
        url,
        dest_m4a,
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
    )


def to_16k_wav(src: str, dest_wav: str) -> str:
    """Convert any audio file to 16 kHz mono WAV (required by FunASR Paraformer)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found. Install it (e.g. `winget install ffmpeg`) or run "
            "`pip install imageio-ffmpeg` to use the bundled binary."
        )
    cmd = [ffmpeg, "-y", "-i", src, "-ar", "16000", "-ac", "1", "-vn", dest_wav]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr[-500:]}")
    return dest_wav

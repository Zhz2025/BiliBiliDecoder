"""Bilibili subtitle decoder — local subtitle downloader with STT fallback.

Downloads AI subtitles from Bilibili via the official API (WBI signed), and
falls back to local speech-to-text (FunASR Paraformer) for videos without
subtitles. Outputs timestamped .srt and .md transcripts.
"""

__version__ = "0.1.0"

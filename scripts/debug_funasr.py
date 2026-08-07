"""Diagnose raw FunASR output structure to decide how to improve segmentation.

Usage: .venv\\Scripts\\python.exe scripts\\debug_funasr.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bilibili_decoder.api.client import BilibiliClient  # noqa: E402
from bilibili_decoder.fetch import media  # noqa: E402
from bilibili_decoder.stt import engine  # noqa: E402


def main() -> None:
    client = BilibiliClient()
    video = client.get_video_info("BV1AiuJ6QE9q")
    with tempfile.TemporaryDirectory(prefix="bilisub_dbg_") as tmp:
        m4a = os.path.join(tmp, "audio.m4a")
        print("downloading audio ...")
        media.download_audio(client.get_audio_url(video.bvid, video.cid), m4a)
        wav = os.path.join(tmp, "audio.wav")
        print("converting ...")
        media.to_16k_wav(m4a, wav)

        mdl = engine.get_model()
        print("generating ...")
        res = mdl.generate(input=wav, batch_size_s=300, sentence_timestamp=True)
        r = res[0]

        print("\n== KEYS:", sorted(r.keys()))
        text = r.get("text", "")
        print("== TEXT len:", len(text), "| has punct:", any(c in text for c in "，。！？；："))
        print("== TEXT head:", text[:200])

        si = r.get("sentence_info", []) or []
        print("\n== sentence_info count:", len(si))
        for s in si[:8]:
            print("   [%8s -> %8s] %r" % (s.get("start"), s.get("end"), (s.get("text") or "")[:60]))

        tok = r.get("token", []) or []
        ts = r.get("timestamp", []) or []
        print("\n== token count:", len(tok), "| timestamp count:", len(ts))
        print("== first tokens:", tok[:25])
        print("== first ts:", ts[:10])


if __name__ == "__main__":
    main()

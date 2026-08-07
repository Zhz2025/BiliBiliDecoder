"""Local speech-to-text via FunASR (Paraformer-large, optimized for Chinese).

Models are downloaded from ModelScope on first use. Audio must be 16 kHz
mono WAV (see fetch.media.to_16k_wav).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from ..api.models import SubtitleSegment

log = logging.getLogger(__name__)

# Keep large STT model downloads on the same drive as the project (default E 盘)
# instead of the default C:\\Users\\<user>\\.cache\\modelscope. Override via the
# MODELSCOPE_CACHE environment variable if desired.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MODELSCOPE_CACHE = os.environ.get(
    "MODELSCOPE_CACHE",
    os.path.join(_PROJECT_ROOT, "models_cache"),
)
os.environ["MODELSCOPE_CACHE"] = _MODELSCOPE_CACHE
log.info("STT 模型缓存目录：%s", _MODELSCOPE_CACHE)

DEFAULT_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
DEFAULT_VAD = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
DEFAULT_PUNC = "iic/punc_ct-transformer_cn-en-common-vocab471067-large"

_MODEL: Optional[object] = None
_MODEL_LOCK = threading.Lock()


def _load_model(model: str, vad_model: str, punc_model: str):
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise RuntimeError(
            "FunASR is not installed. Run: pip install -r requirements.txt"
        ) from exc
    log.info("Loading FunASR models (first run downloads them, this can take a while)...")
    return AutoModel(
        model=model,
        vad_model=vad_model,
        punc_model=punc_model,
        disable_update=True,
    )


def get_model(
    model: str = DEFAULT_MODEL,
    vad_model: str = DEFAULT_VAD,
    punc_model: str = DEFAULT_PUNC,
):
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            _MODEL = _load_model(model, vad_model, punc_model)
            log.info("FunASR model loaded.")
    return _MODEL


def transcribe(
    audio_path: str,
    model: str = DEFAULT_MODEL,
    vad_model: str = DEFAULT_VAD,
    punc_model: str = DEFAULT_PUNC,
    hotword: str = "",
    batch_size_s: int = 300,
) -> list[SubtitleSegment]:
    """Transcribe a 16 kHz WAV file into timestamped segments (seconds)."""
    mdl = get_model(model, vad_model, punc_model)
    kwargs: dict = {"batch_size_s": batch_size_s, "sentence_timestamp": True}
    if hotword:
        kwargs["hotword"] = hotword

    log.info("Transcribing %s ...", audio_path)
    result = mdl.generate(input=audio_path, **kwargs)

    segments: list[SubtitleSegment] = []
    if not result:
        return segments
    first = result[0]
    for sent in first.get("sentence_info", []) or []:
        text = (sent.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            SubtitleSegment(
                start=float(sent.get("start", 0)) / 1000.0,
                end=float(sent.get("end", 0)) / 1000.0,
                text=text,
            )
        )
    # Fallback: sentence timestamps unavailable -> single segment for whole text.
    if not segments and (first.get("text") or "").strip():
        segments.append(
            SubtitleSegment(
                start=0.0,
                end=0.0,
                text=(first.get("text") or "").strip(),
            )
        )
    return segments

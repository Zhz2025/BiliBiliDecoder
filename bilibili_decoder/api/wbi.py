"""Bilibili WBI (Web Interface) signature algorithm.

Bilibili requires a signed `w_rid` parameter for several API endpoints.
The signature is an MD5 of (sorted query string + mixin key) where the
mixin key is derived from two rotating keys exposed by the `/nav` endpoint.
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse

# 64-element permutation table used to shuffle img_key + sub_key.
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# Salt appended to the query string before MD5.
MIXIN_KEY = "ea1db124af3c7062474693fa704f4ff8"

# Characters filtered out of parameter values before signing.
_FILTER_CHARS = set("!'()*")


def get_mixin_key(orig: str) -> str:
    """Apply the permutation table to `orig` and keep the first 32 chars."""
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """Return a copy of `params` augmented with `wts` and `w_rid`."""
    params = dict(params)
    params["wts"] = int(time.time())

    sorted_params = dict(sorted(params.items()))
    filtered = {
        k: "".join(ch for ch in str(v) if ch not in _FILTER_CHARS)
        for k, v in sorted_params.items()
    }
    query = urllib.parse.urlencode(filtered)
    mixin_key = get_mixin_key(img_key + sub_key)
    wbi_sign = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    filtered["w_rid"] = wbi_sign
    return filtered


def extract_key_from_url(url: str) -> str:
    """Extract the key (filename without extension) from a wbi_img URL."""
    return url.rsplit("/", 1)[-1].split(".")[0]

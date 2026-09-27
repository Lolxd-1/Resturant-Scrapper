"""Photo downloading and validation: thumbnails for screening, full size for the final pick."""
from __future__ import annotations

import hashlib
import io
import logging

import numpy as np
from PIL import Image

from studio.zomato import Http

log = logging.getLogger("studio.imaging")

THUMB_SUFFIX = "?fit=around%7C300%3A300&crop=300%3A300%3B%2A%2C%2A"

_MIN_VALID_SIDE = 200
_MAX_ASPECT = 2.2
_MIN_ASPECT = 0.45
_BLANK_STDDEV = 8.0


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_get(url: str, http: Http):
    try:
        return http.get(url)
    except Exception as exc:
        log.debug("imaging: request failed for %s: %s", url, exc)
        return None


def fetch_thumb(url: str, http: Http) -> bytes | None:
    resp = _safe_get(url.split("?", 1)[0] + THUMB_SUFFIX, http)
    if resp is None or resp.status_code != 200:
        return None
    content = resp.content
    if content is None or len(content) < 1500:
        return None
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return None
    return content


def validate_photo(img: Image.Image) -> str | None:
    w, h = img.size
    if min(w, h) < _MIN_VALID_SIDE:
        return "too small"
    aspect = w / h
    if aspect > _MAX_ASPECT or aspect < _MIN_ASPECT:
        return "odd shape"
    thumb = img.convert("L").resize((64, 64), Image.LANCZOS)
    if float(np.asarray(thumb, dtype=np.float64).std()) < _BLANK_STDDEV:
        return "blank"
    return None


def fetch_full(
    url: str, http: Http, min_side: int = 400, max_side: int = 1600
) -> tuple[bytes, tuple[int, int]] | None:
    resp = _safe_get(url.split("?", 1)[0], http)
    if resp is None or resp.status_code != 200:
        return None
    content = resp.content
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return None

    if validate_photo(img) is not None:
        return None

    if img.mode in ("P", "RGBA", "LA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")

    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

    if min(img.size) < min_side:
        return None

    buf = io.BytesIO()
    try:
        img.save(buf, format="JPEG", quality=88, optimize=True)
    except Exception:
        return None
    return buf.getvalue(), img.size

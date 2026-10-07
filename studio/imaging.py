"""Photo downloading and validation: thumbnails for screening, full size for the final pick."""
from __future__ import annotations

import hashlib
import io
import logging

import numpy as np
from PIL import Image

from studio.swiggy import IMG_BASE
from studio.zomato import Http

log = logging.getLogger("studio.imaging")

THUMB_SUFFIX = "?fit=around%7C300%3A300&crop=300%3A300%3B%2A%2C%2A"
_SWIGGY_THUMB = "fl_lossy,f_auto,q_auto,w_300,h_300,c_fill/"

_MIN_VALID_SIDE = 200
_MAX_ASPECT = 2.2
_MIN_ASPECT = 0.45
_BLANK_STDDEV = 8.0


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_get_ex(url: str, http: Http) -> tuple[object | None, str]:
    try:
        return http.get_ex(url)
    except Exception as exc:
        log.debug("imaging: request failed for %s: %s", url, exc)
        return None, "network"


def full_url(url: str) -> str:
    return url.split("?", 1)[0]


def thumb_url(url: str) -> str:
    base = full_url(url)
    if base.startswith(IMG_BASE):
        return IMG_BASE + _SWIGGY_THUMB + base[len(IMG_BASE):]
    return base + THUMB_SUFFIX


def fetch_thumb_ex(url: str, http: Http) -> tuple[bytes | None, str]:
    resp, reason = _safe_get_ex(thumb_url(url), http)
    if resp is None:
        return None, reason
    content = resp.content
    if content is None or len(content) < 1500:
        return None, "invalid"
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return None, "invalid"
    return content, ""


def fetch_thumb(url: str, http: Http) -> bytes | None:
    content, _ = fetch_thumb_ex(url, http)
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


def fetch_full_ex(
    url: str, http: Http, min_side: int = 400, max_side: int = 1600
) -> tuple[tuple[bytes, tuple[int, int]] | None, str]:
    resp, reason = _safe_get_ex(full_url(url), http)
    if resp is None:
        return None, reason
    content = resp.content
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        return None, "invalid"

    if validate_photo(img) is not None:
        return None, "invalid"

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
        return None, "invalid"

    buf = io.BytesIO()
    try:
        img.save(buf, format="JPEG", quality=88, optimize=True)
    except Exception:
        return None, "invalid"
    return (buf.getvalue(), img.size), ""


def fetch_full(
    url: str, http: Http, min_side: int = 400, max_side: int = 1600
) -> tuple[bytes, tuple[int, int]] | None:
    result, _ = fetch_full_ex(url, http, min_side, max_side)
    return result

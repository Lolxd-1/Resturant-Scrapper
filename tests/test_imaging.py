"""Tests for studio.imaging (offline; no real network access)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

import requests

from studio.imaging import (
    THUMB_SUFFIX, fetch_full, fetch_full_ex, fetch_thumb, fetch_thumb_ex, full_url, sha256, thumb_url,
)
from studio.swiggy import IMG_BASE
from studio.zomato import Http
from tests.conftest import FakeResponse


def make_http(fake_session, **kwargs):
    kwargs.setdefault("min_interval", 0.0)
    kwargs.setdefault("sleep", lambda s: None)
    kwargs.setdefault("clock", lambda: 0.0)
    return Http(session=fake_session, **kwargs)


def image_bytes(size, mode="RGB", color=(200, 30, 30), fmt="JPEG"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return buf.getvalue()


def rgba_pattern_bytes(size):
    """A non-blank RGBA image: opaque black left half, translucent white right half."""
    w, h = size
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, : w // 2] = (0, 0, 0, 255)
    arr[:, w // 2 :] = (255, 255, 255, 128)
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


# ---- TC1: fetch_thumb strips query + appends suffix; 404 -> None; garbage -> None ----

def test_tc1_fetch_thumb_strips_query_and_appends_suffix(fake_session):
    data = image_bytes((300, 300))
    http = make_http(fake_session)
    fake_session.add("https://b.zmtcdn.com/img.jpg" + THUMB_SUFFIX, FakeResponse(200, content=data))

    result = fetch_thumb("https://b.zmtcdn.com/img.jpg?fit=around|100:100", http)

    assert result == data
    called_url = fake_session.calls[0][0]
    assert called_url == "https://b.zmtcdn.com/img.jpg" + THUMB_SUFFIX


def test_tc1_fetch_thumb_404_returns_none(fake_session):
    http = make_http(fake_session)
    assert fetch_thumb("https://b.zmtcdn.com/missing.jpg", http) is None


def test_tc1_fetch_thumb_garbage_bytes_returns_none(fake_session):
    http = make_http(fake_session)
    fake_session.add("https://b.zmtcdn.com/bad.jpg" + THUMB_SUFFIX, FakeResponse(200, content=b"not an image" * 200))
    assert fetch_thumb("https://b.zmtcdn.com/bad.jpg", http) is None


def test_tc1_fetch_thumb_too_small_returns_none(fake_session):
    http = make_http(fake_session)
    fake_session.add("https://b.zmtcdn.com/tiny.jpg" + THUMB_SUFFIX, FakeResponse(200, content=b"x" * 100))
    assert fetch_thumb("https://b.zmtcdn.com/tiny.jpg", http) is None


# ---- TC2: fetch_full downscale/convert, min_side reject, aspect reject, blank reject ----

def test_tc2_fetch_full_downscales_rgba_png(fake_session):
    data = rgba_pattern_bytes((2000, 1500))
    http = make_http(fake_session)
    fake_session.add("https://b.zmtcdn.com/big.png", FakeResponse(200, content=data))

    result = fetch_full("https://b.zmtcdn.com/big.png", http)

    assert result is not None
    out_bytes, size = result
    assert size == (1600, 1200)
    out_img = Image.open(io.BytesIO(out_bytes))
    assert out_img.format == "JPEG"
    assert out_img.mode == "RGB"
    assert out_img.size == (1600, 1200)


def test_tc2_fetch_full_below_min_side_returns_none(fake_session):
    http = make_http(fake_session)
    fake_session.add("https://b.zmtcdn.com/small.jpg", FakeResponse(200, content=image_bytes((300, 300))))
    assert fetch_full("https://b.zmtcdn.com/small.jpg", http) is None


def test_tc2_fetch_full_odd_shape_returns_none(fake_session):
    http = make_http(fake_session)
    fake_session.add("https://b.zmtcdn.com/banner.jpg", FakeResponse(200, content=image_bytes((1000, 200))))
    assert fetch_full("https://b.zmtcdn.com/banner.jpg", http) is None


def test_tc2_fetch_full_blank_returns_none(fake_session):
    http = make_http(fake_session)
    data = image_bytes((800, 800), color=(128, 128, 128))
    fake_session.add("https://b.zmtcdn.com/blank.jpg", FakeResponse(200, content=data))
    assert fetch_full("https://b.zmtcdn.com/blank.jpg", http) is None


def test_tc2_fetch_full_strips_query_and_never_raises_on_404(fake_session):
    http = make_http(fake_session)
    assert fetch_full("https://b.zmtcdn.com/missing.jpg?x=1", http) is None
    assert fetch_full("https://b.zmtcdn.com/missing.jpg", http) is None


# ---- FIX2 TC3: fetch_full_ex distinguishes network failure from a definitive 404 ----

def test_fix2_tc3_fetch_full_ex_network_failure(fake_session):
    http = make_http(fake_session, max_retries=1)
    fake_session.add("https://b.zmtcdn.com/flaky.jpg", requests.ConnectionError("boom"))
    result, reason = fetch_full_ex("https://b.zmtcdn.com/flaky.jpg", http)
    assert result is None
    assert reason == "network"


def test_fix2_tc3_fetch_full_ex_404_is_http(fake_session):
    http = make_http(fake_session)
    result, reason = fetch_full_ex("https://b.zmtcdn.com/missing.jpg", http)
    assert result is None
    assert reason == "http"


# ---- TC7: sha256 of b"abc" equals the known hex digest ----

def test_tc7_sha256_known_digest():
    assert sha256(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ---- host-aware URLs (Zomato + Swiggy) ----

def test_thumb_and_full_url_for_both_hosts():
    z = "https://b.zmtcdn.com/data/dish/x.jpg?fit=1"
    assert full_url(z) == "https://b.zmtcdn.com/data/dish/x.jpg"
    assert thumb_url(z) == "https://b.zmtcdn.com/data/dish/x.jpg" + THUMB_SUFFIX
    s = IMG_BASE + "abc/def.jpg"
    assert full_url(s) == s
    assert thumb_url(s) == IMG_BASE + "fl_lossy,f_auto,q_auto,w_300,h_300,c_fill/abc/def.jpg"


def test_fetch_thumb_ex_requests_swiggy_thumb_url(fake_session):
    fake_session.add(IMG_BASE, FakeResponse(200, content=image_bytes((300, 300))))
    fetch_thumb_ex(IMG_BASE + "abc", make_http(fake_session))
    assert fake_session.calls[0][0] == IMG_BASE + "fl_lossy,f_auto,q_auto,w_300,h_300,c_fill/abc"

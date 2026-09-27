"""Tests for studio.hosting (offline; no real network access)."""
from __future__ import annotations

import hashlib
import json

import pytest
import requests

import studio.hosting as hosting
from studio.hosting import IMGBB_URL, Uploader, UploadError
from studio.models import ImgbbKey
from studio.store import PoolStore
from tests.conftest import FakeResponse


class ScriptedPost:
    """A fake http_post: returns/raises the next scripted item on each call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, url, data=None, files=None, timeout=None):
        assert url == IMGBB_URL
        self.calls.append(dict(data))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def success_resp(url: str, display_url: str | None = None) -> FakeResponse:
    display_url = url if display_url is None else display_url
    body = {"data": {"url": url, "display_url": display_url}, "success": True, "status": 200}
    return FakeResponse(200, json.dumps(body))


def invalid_key_resp() -> FakeResponse:
    body = {"status_code": 400, "error": {"message": "Invalid API v1 key.", "code": 100}, "status_txt": "Bad Request"}
    return FakeResponse(400, json.dumps(body))


def rate_limit_resp() -> FakeResponse:
    body = {"status_code": 429, "error": {"message": "Too many requests", "code": 999}, "status_txt": "Too Many Requests"}
    return FakeResponse(429, json.dumps(body))


def reject_resp(message: str) -> FakeResponse:
    body = {"status_code": 400, "error": {"message": message, "code": 999}, "status_txt": "Bad Request"}
    return FakeResponse(400, json.dumps(body))


# ---- TC1: happy path returns https display_url, caches by sha256, dedupes ----

def test_tc1_happy_success_and_dedupe(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    post = ScriptedPost([success_resp("https://i.ibb.co/x/a.jpg")])
    up = Uploader([ImgbbKey(label="k1", key="AAAAAAAA1111")], http_post=post, store=store)

    url = up.upload(b"hello", "Dish Name")

    assert url == "https://i.ibb.co/x/a.jpg"
    assert post.calls[0]["name"] == "dish-name"
    assert store.get_upload(hashlib.sha256(b"hello").hexdigest()) == url

    url2 = up.upload(b"hello", "Dish Name")
    assert url2 == url
    assert len(post.calls) == 1  # second upload made no HTTP call


# ---- TC2: 3 keys, 3 uploads -> keys used in round-robin order k1, k2, k3 ----

def test_tc2_rotation_across_uploads(tmp_path):
    post = ScriptedPost([
        success_resp("https://i.ibb.co/1/a.jpg"),
        success_resp("https://i.ibb.co/2/b.jpg"),
        success_resp("https://i.ibb.co/3/c.jpg"),
    ])
    ks = [
        ImgbbKey(label="k1", key="AAAA1111"),
        ImgbbKey(label="k2", key="BBBB2222"),
        ImgbbKey(label="k3", key="CCCC3333"),
    ]
    up = Uploader(ks, http_post=post)

    up.upload(b"one", "d1")
    up.upload(b"two", "d2")
    up.upload(b"three", "d3")

    assert [c["key"] for c in post.calls] == ["AAAA1111", "BBBB2222", "CCCC3333"]


# ---- TC3: invalid key disables it permanently and is skipped afterwards ----

def test_tc3_invalid_key_disables_and_skips(tmp_path):
    post = ScriptedPost([
        invalid_key_resp(),
        success_resp("https://i.ibb.co/2/b.jpg"),
        success_resp("https://i.ibb.co/2/c.jpg"),
    ])
    ks = [ImgbbKey(label="k1", key="AAAA1111"), ImgbbKey(label="k2", key="BBBB2222")]
    up = Uploader(ks, http_post=post)

    url = up.upload(b"one", "d1")
    assert url == "https://i.ibb.co/2/b.jpg"

    states = {s["label"]: s for s in up.key_states()}
    assert states["k1"]["state"] == "disabled"
    assert states["k1"]["last_error"] == "Invalid key"
    assert states["k1"]["tail"] == "1111"

    up.upload(b"two", "d2")
    used_keys = [c["key"] for c in post.calls]
    assert "AAAA1111" not in used_keys[1:]


# ---- TC4: rate limit cools the key down; it recovers once the cooldown elapses ----

def test_tc4_rate_limit_cooldown_then_recovers():
    clk = FakeClock()
    post = ScriptedPost([
        rate_limit_resp(),
        success_resp("https://i.ibb.co/2/b.jpg"),
        success_resp("https://i.ibb.co/1/again.jpg"),
    ])
    ks = [ImgbbKey(label="k1", key="AAAA1111"), ImgbbKey(label="k2", key="BBBB2222")]
    up = Uploader(ks, http_post=post, sleep=clk.sleep, clock=clk.clock)

    url = up.upload(b"one", "d1")
    assert url == "https://i.ibb.co/2/b.jpg"
    states = {s["label"]: s for s in up.key_states()}
    assert states["k1"]["state"] == "cooldown"
    assert states["k1"]["last_error"] == "Rate limited"

    clk.now += 61
    url2 = up.upload(b"two", "d2")
    assert url2 == "https://i.ibb.co/1/again.jpg"
    assert [c["key"] for c in post.calls][-1] == "AAAA1111"


# ---- TC5: every key invalid -> error message lists every label, no full key ----

def test_tc5_all_keys_invalid_error_lists_labels_no_keys():
    post = ScriptedPost([invalid_key_resp(), invalid_key_resp()])
    ks = [ImgbbKey(label="k1", key="AAAA1111"), ImgbbKey(label="k2", key="BBBB2222")]
    up = Uploader(ks, http_post=post)

    with pytest.raises(UploadError) as exc:
        up.upload(b"one", "d1")
    msg = str(exc.value)
    assert "k1" in msg and "k2" in msg
    assert "AAAA1111" not in msg and "BBBB2222" not in msg


# ---- TC6: network errors on every key, then recovery after the fake sleep advances the clock ----

def test_tc6_network_errors_then_recover_via_wait():
    clk = FakeClock()
    post = ScriptedPost([
        requests.exceptions.ConnectionError("boom"),
        requests.exceptions.ConnectionError("boom"),
        success_resp("https://i.ibb.co/1/ok.jpg"),
    ])
    ks = [ImgbbKey(label="k1", key="AAAA1111"), ImgbbKey(label="k2", key="BBBB2222")]
    up = Uploader(ks, http_post=post, sleep=clk.sleep, clock=clk.clock)

    url = up.upload(b"one", "d1")
    assert url == "https://i.ibb.co/1/ok.jpg"
    assert len(post.calls) == 3


# ---- TC7: image rejected -> immediate error, key is not blamed ----

def test_tc7_reject_does_not_blame_key():
    post = ScriptedPost([reject_resp("Invalid image source")])
    ks = [ImgbbKey(label="k1", key="AAAA1111")]
    up = Uploader(ks, http_post=post)

    with pytest.raises(UploadError, match=r"ImgBB rejected the image: Invalid image source"):
        up.upload(b"one", "d1")

    state = up.key_states()[0]
    assert state["state"] == "ok"
    assert state["last_error"] == ""


# ---- TC8: no enabled keys -> Settings message ----

def test_tc8_no_usable_keys():
    ks = [ImgbbKey(label="k1", key="", enabled=True), ImgbbKey(label="k2", key="X", enabled=False)]
    up = Uploader(ks, http_post=ScriptedPost([]))

    with pytest.raises(UploadError, match=r"No ImgBB API key saved\. Add one in Settings\."):
        up.upload(b"one", "d1")


# ---- TC9: test_key maps each outcome to its exact tuple ----

def test_tc9_test_key_mappings():
    assert hosting.test_key(
        "AAAA1111", http_post=ScriptedPost([success_resp("https://i.ibb.co/1/a.jpg")])
    ) == (True, "Key works")
    assert hosting.test_key(
        "AAAA1111", http_post=ScriptedPost([invalid_key_resp()])
    ) == (False, "Invalid key")
    assert hosting.test_key(
        "AAAA1111", http_post=ScriptedPost([rate_limit_resp()])
    ) == (False, "Rate limited — try again later")

    ok, msg = hosting.test_key(
        "AAAA1111", http_post=ScriptedPost([requests.exceptions.ConnectionError("boom")])
    )
    assert ok is False
    assert msg.startswith("Could not reach ImgBB:")
    assert "AAAA1111" not in msg


# ---- TC10: "http://" response url is upgraded to "https://" ----

def test_tc10_http_url_upgraded_to_https():
    post = ScriptedPost([success_resp("http://i.ibb.co/1/a.jpg")])
    ks = [ImgbbKey(label="k1", key="AAAA1111")]
    up = Uploader(ks, http_post=post)

    url = up.upload(b"one", "d1")
    assert url == "https://i.ibb.co/1/a.jpg"

"""ImgBB uploader: multi-key rotation, cooldown, disable-on-invalid, sha256 dedupe."""
from __future__ import annotations

import hashlib
import re
import time
from io import BytesIO

import requests
from PIL import Image

from studio.models import ImgbbKey
from studio.store import PoolStore

IMGBB_URL = "https://api.imgbb.com/1/upload"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class UploadError(Exception):
    pass


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:60]


def _classify(resp) -> tuple[str, object]:
    """Returns (kind, payload). kind in success/disabled/cooldown60/servererror/reject."""
    status = getattr(resp, "status_code", 200)
    try:
        j = resp.json()
    except Exception:
        return "servererror", f"Server error {status}"
    if not isinstance(j, dict):
        return "servererror", f"Server error {status}"
    if j.get("success") and isinstance(j.get("data"), dict) and j["data"].get("url"):
        return "success", j["data"]

    error = j.get("error")
    message = ""
    code = None
    if isinstance(error, dict):
        message = str(error.get("message") or "")
        code = error.get("code")
    if not message:
        message = str(j.get("status_txt") or "")

    if code == 100 or "invalid api" in message.lower():
        return "disabled", "Invalid key"
    if status == 429 or re.search(r"rate|too many|limit", message, re.I):
        return "cooldown60", "Rate limited"
    if status >= 500:
        return "servererror", f"Server error {status}"
    return "reject", message or "ImgBB error"


def _url_from_data(data: dict) -> str:
    display = data.get("display_url") or ""
    url = display if display.startswith("http") else data.get("url", "")
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


class Uploader:
    def __init__(
        self,
        keys: list[ImgbbKey],
        *,
        http_post=requests.post,
        store: PoolStore | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.http_post = http_post
        self.store = store
        self.sleep = sleep
        self.clock = clock
        self._cursor = 0
        self._keys = [
            {
                "label": k.label,
                "key": k.key,
                "tail": k.key[-4:],
                "disabled": False,
                "cooldown_until": 0.0,
                "failures": 0,
                "last_error": "",
            }
            for k in keys
            if k.enabled and k.key
        ]

    def upload(self, jpeg: bytes, name: str) -> str:
        digest = hashlib.sha256(jpeg).hexdigest()
        if self.store is not None:
            cached = self.store.get_upload(digest)
            if cached:
                return cached
        if not self._keys:
            raise UploadError("No ImgBB API key saved. Add one in Settings.")

        slug = _slugify(name)
        n = len(self._keys)
        max_attempts = 3 * n + 2
        attempts = 0
        wait_rounds = 0

        while attempts < max_attempts:
            key_idx = None
            for _ in range(n):
                k = self._keys[self._cursor % n]
                if not k["disabled"] and k["cooldown_until"] <= self.clock():
                    key_idx = self._cursor % n
                    break
                self._cursor += 1
            if key_idx is None:
                candidates = [k for k in self._keys if not k["disabled"]]
                if not candidates or wait_rounds >= n:
                    break
                wait_rounds += 1
                earliest = min(k["cooldown_until"] for k in candidates)
                self.sleep(max(0.0, min(120.0, earliest - self.clock())))
                continue

            self._cursor += 1
            attempts += 1
            key_state = self._keys[key_idx]
            try:
                resp = self.http_post(
                    IMGBB_URL,
                    data={"key": key_state["key"], "name": slug},
                    files={"image": (slug + ".jpg", jpeg, "image/jpeg")},
                    timeout=60,
                )
            except Exception:
                key_state["failures"] += 1
                key_state["cooldown_until"] = self.clock() + min(60.0, 5.0 * key_state["failures"])
                key_state["last_error"] = "Network error"
                continue

            kind, payload = _classify(resp)
            if kind == "success":
                url = _url_from_data(payload)
                if self.store is not None:
                    self.store.put_upload(digest, url, "imgbb")
                return url
            if kind == "disabled":
                key_state["disabled"] = True
                key_state["last_error"] = payload
                continue
            if kind == "cooldown60":
                key_state["cooldown_until"] = self.clock() + 60.0
                key_state["last_error"] = payload
                continue
            if kind == "servererror":
                key_state["cooldown_until"] = self.clock() + 10.0
                key_state["last_error"] = payload
                continue
            raise UploadError(f"ImgBB rejected the image: {payload}")

        raise UploadError(
            "All ImgBB keys failed: "
            + "; ".join(f"{k['label']}: {k['last_error'] or 'not attempted'}" for k in self._keys)
        )

    def key_states(self) -> list[dict]:
        now = self.clock()
        states = []
        for k in self._keys:
            if k["disabled"]:
                state = "disabled"
            elif k["cooldown_until"] > now:
                state = "cooldown"
            else:
                state = "ok"
            states.append({"label": k["label"], "tail": k["tail"], "state": state, "last_error": k["last_error"]})
        return states


def _tiny_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (32, 32), color=(200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_key(key: str, *, http_post=requests.post) -> tuple[bool, str]:
    jpeg = _tiny_jpeg()
    try:
        resp = http_post(
            IMGBB_URL,
            data={"key": key, "expiration": 60},
            files={"image": ("test.jpg", jpeg, "image/jpeg")},
            timeout=60,
        )
    except Exception as e:
        return False, f"Could not reach ImgBB: {str(e)[:80]}"

    kind, payload = _classify(resp)
    if kind == "success":
        return True, "Key works"
    if kind == "disabled":
        return False, "Invalid key"
    if kind == "cooldown60":
        return False, "Rate limited — try again later"
    return False, str(payload)

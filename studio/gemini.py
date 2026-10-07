"""Gemini REST client (free tier): model fallback, throttling, disk cache. Never exposes the API key."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import time
from pathlib import Path

import requests

from studio.config import atomic_write_text

log = logging.getLogger("studio.gemini")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS: tuple[str, ...] = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
                           "gemini-3.5-flash", "gemini-2.5-flash")
_TIMEOUT = 240
_EXHAUSTED_SECONDS = 3600

# Shared by every instance: one process, many jobs, one free quota.
_lock = threading.Lock()
_last_start: float | None = None
_exhausted: dict[str, float] = {}


class GeminiError(Exception):
    """str(exc) is a plain-English message for the user."""


class GeminiQuotaError(GeminiError):
    """Every model is out of free quota right now."""


def text_part(text: str) -> dict:
    return {"text": text}


def image_part(data: bytes, mime: str = "image/jpeg") -> dict:
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}}


def _error_info(resp) -> tuple[str, str, float | None, bool]:
    """(message, status, retry delay seconds, is per-day quota) from an error response."""
    try:
        err = resp.json().get("error", {})
    except (ValueError, AttributeError):
        return "", "", None, False
    if not isinstance(err, dict):
        return "", "", None, False
    delay, per_day = None, False
    for d in err.get("details") or []:
        if not isinstance(d, dict):
            continue
        for v in d.get("violations") or []:
            if "PerDay" in str(v.get("quotaId", "")):
                per_day = True
        raw = d.get("retryDelay")
        if isinstance(raw, str) and raw.endswith("s"):
            try:
                delay = float(raw[:-1])
            except ValueError:
                pass
    return str(err.get("message", "")), str(err.get("status", "")), delay, per_day


class Gemini:
    def __init__(self, api_key: str, *, cache_dir: Path | None = None, models: tuple[str, ...] = MODELS,
                 post=requests.post, get=requests.get, sleep=time.sleep, clock=time.monotonic,
                 min_interval: float = 6.5):
        self._key = api_key.strip()
        self._cache_dir = cache_dir
        self._models = models
        self._post, self._get, self._sleep, self._clock = post, get, sleep, clock
        self._min_interval = min_interval
        self.last_model = ""

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _headers(self) -> dict:
        return {"x-goog-api-key": self._key, "Content-Type": "application/json"}

    def _cache_path(self, system: str, parts: list[dict], schema: dict, high_res: bool) -> Path | None:
        if self._cache_dir is None:
            return None
        stable = [{"image": hashlib.sha256(p["inlineData"]["data"].encode()).hexdigest()}
                  if "inlineData" in p else p for p in parts]
        blob = json.dumps({"system": system, "schema": schema, "high_res": high_res, "parts": stable},
                          sort_keys=True)
        return self._cache_dir / (hashlib.sha256(blob.encode()).hexdigest() + ".json")

    def _throttled_post(self, url: str, body: dict):
        global _last_start
        with _lock:
            if _last_start is not None:
                wait = self._min_interval - (self._clock() - _last_start)
                if wait > 0:
                    self._sleep(wait)
            _last_start = self._clock()
        return self._post(url, headers=self._headers(), json=body, timeout=_TIMEOUT)

    def generate_json(self, system: str, parts: list[dict], schema: dict, *, high_res: bool = False,
                      max_output_tokens: int = 65536) -> dict:
        if not self.available:
            raise GeminiError("Add your free Gemini API key in Settings first.")
        cache_file = self._cache_path(system, parts, schema, high_res)
        if cache_file is not None and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(cached, dict):
                    self.last_model = "cache"
                    return cached
            except ValueError:
                pass

        gen_config = {"responseMimeType": "application/json", "responseJsonSchema": schema,
                      "maxOutputTokens": max_output_tokens}
        if high_res:
            gen_config["mediaResolution"] = "MEDIA_RESOLUTION_HIGH"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": gen_config}

        only_quota, reason = True, ""
        for model in self._models:
            if self._clock() < _exhausted.get(model, 0.0):
                continue
            result, reason_m, is_quota = self._try_model(model, body)
            if result is not None:
                if cache_file is not None:
                    atomic_write_text(cache_file, json.dumps(result, ensure_ascii=False))
                self.last_model = model
                return result
            reason = reason_m
            only_quota = only_quota and is_quota
        if only_quota:
            raise GeminiQuotaError(
                "The free Gemini quota is used up for now on every model. It resets around 12:30 PM "
                "India time; you can also use the Gemini website prompt.")
        raise GeminiError(f"Gemini could not answer right now ({reason}). Try again in a few minutes.")

    def _try_model(self, model: str, body: dict) -> tuple[dict | None, str, bool]:
        """Returns (answer, failure reason, failed on quota). Raises GeminiError when retrying is pointless."""
        url = f"{API_BASE}/models/{model}:generateContent"
        retried_429 = retried_5xx = retried_res = False
        while True:
            try:
                resp = self._throttled_post(url, body)
            except requests.RequestException as e:
                log.warning("%s request failed (%s)", model, type(e).__name__)
                if retried_5xx:
                    return None, "network error", False
                retried_5xx = True
                self._sleep(5)
                continue
            code = resp.status_code
            if code == 200:
                return self._read_answer(model, resp)
            message, status, delay, per_day = _error_info(resp)
            log.warning("%s returned HTTP %s %s", model, code, status)
            if code == 429:
                if per_day:
                    _exhausted[model] = self._clock() + _EXHAUSTED_SECONDS
                    return None, "daily quota used up", True
                if retried_429:
                    return None, "rate limit", True
                retried_429 = True
                self._sleep(min(delay or 20, 60))
                continue
            if code in (401, 403) or (code == 400 and "api key" in message.lower()):
                raise GeminiError("Your Gemini key was rejected. Check it in Settings.")
            if code == 400:
                if "mediaResolution" in body["generationConfig"] and not retried_res:
                    retried_res = True
                    gen = {k: v for k, v in body["generationConfig"].items() if k != "mediaResolution"}
                    body = {**body, "generationConfig": gen}
                    continue
                raise GeminiError(f"Gemini rejected the request: {message[:200]}")
            if code == 404:
                return None, "model not available", False
            if code >= 500:
                if retried_5xx:
                    return None, f"server error {code}", False
                retried_5xx = True
                self._sleep(5)
                continue
            return None, f"HTTP {code}", False

    def _read_answer(self, model: str, resp) -> tuple[dict | None, str, bool]:
        try:
            data = resp.json()
            cand = data["candidates"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            log.warning("%s gave no answer", model)
            return None, "empty answer", False
        finish = cand.get("finishReason")
        if finish != "STOP":
            log.warning("%s stopped early: finishReason=%s", model, finish)
            return None, f"stopped early: {finish}", False
        texts = [p.get("text", "") for p in cand.get("content", {}).get("parts", [])
                 if isinstance(p, dict) and not p.get("thought")]
        try:
            answer = json.loads("".join(texts))
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            log.warning("%s: answer was not a JSON object (finishReason=%s)", model, finish)
            return None, "unreadable answer", False
        usage = data.get("usageMetadata") or {}
        log.info("%s answered (prompt tokens %s, output tokens %s)", model,
                 usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
        return answer, "", False

    def check_key(self) -> tuple[bool, str]:
        if not self.available:
            return False, "No Gemini key entered."
        try:
            resp = self._get(f"{API_BASE}/models?pageSize=1", headers=self._headers(), timeout=30)
        except requests.RequestException:
            return False, "Could not reach Gemini. Check your internet connection."
        if resp.status_code == 200:
            return True, "Gemini key works"
        if resp.status_code in (400, 401, 403):
            return False, "Your Gemini key was rejected."
        return False, f"Gemini answered with an error (HTTP {resp.status_code})."

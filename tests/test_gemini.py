"""Tests for studio.gemini (offline: fake post/get, sleep, clock)."""
from __future__ import annotations

import json
import logging

import pytest

from studio import gemini
from studio.gemini import Gemini, GeminiError, GeminiQuotaError, image_part, text_part
from tests.conftest import FakeResponse

KEY = "AIzaSECRETKEY123"
SCHEMA = {"type": "object"}


@pytest.fixture(autouse=True)
def clean_state():
    gemini._last_start = None
    gemini._exhausted.clear()
    yield
    gemini._last_start = None
    gemini._exhausted.clear()


def ok(text='{"a": 1}', finish="STOP", parts=None):
    parts = parts if parts is not None else [{"text": text}]
    body = {"candidates": [{"content": {"parts": parts}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}
    return FakeResponse(200, json.dumps(body))


def err(code, message="x", status="ERR", details=None):
    return FakeResponse(code, json.dumps({"error": {"code": code, "message": message,
                                                    "status": status, "details": details or []}}))


def per_day():
    return err(429, status="RESOURCE_EXHAUSTED", details=[
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}])


def per_minute(delay="7s"):
    return err(429, status="RESOURCE_EXHAUSTED", details=[
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}])


class Fake:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.sleeps = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json, timeout))
        return self.responses.pop(0)

    get = post

    def sleep(self, s):
        self.sleeps.append(s)

    def clock(self):
        return 0.0

    def client(self, **kw):
        return Gemini(KEY, post=self.post, get=self.get, sleep=self.sleep, clock=self.clock, **kw)


def test_happy_request_shape():
    f = Fake(ok())
    g = f.client()
    assert g.generate_json("sys", [text_part("hi")], SCHEMA) == {"a": 1}
    url, headers, body, timeout = f.calls[0]
    assert url.endswith("/models/gemini-3.8-flash:generateContent")
    assert headers["x-goog-api-key"] == KEY and KEY not in url
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["contents"][0]["parts"] == [{"text": "hi"}]
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"] == SCHEMA
    assert cfg["maxOutputTokens"] == 65536 and "mediaResolution" not in cfg
    assert g.last_model == "gemini-3.8-flash"
    f2 = Fake(ok())
    f2.client().generate_json("sys", [text_part("hi")], SCHEMA, high_res=True)
    assert f2.calls[0][2]["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_HIGH"


def test_thought_parts_skipped():
    f = Fake(ok(parts=[{"text": "thinking", "thought": True}, {"text": '{"a":2}'}]))
    assert f.client().generate_json("s", [text_part("x")], SCHEMA) == {"a": 2}


def test_per_day_quota_falls_back_and_is_remembered():
    f = Fake(per_day(), ok())
    assert f.client().generate_json("s", [text_part("x")], SCHEMA) == {"a": 1}
    assert f.calls[1][0].endswith("gemini-3.7-flash:generateContent")
    f.responses.append(ok())
    f.client().generate_json("s", [text_part("y")], SCHEMA)
    assert f.calls[2][0].endswith("gemini-3.7-flash:generateContent")


def test_per_minute_429_sleeps_and_retries_same_model():
    f = Fake(per_minute("7s"), ok())
    g = f.client()
    assert g.generate_json("s", [text_part("x")], SCHEMA) == {"a": 1}
    assert 7 in f.sleeps
    assert g.last_model == "gemini-3.8-flash"


def test_all_models_per_day_raises_quota_error():
    f = Fake(*[per_day() for _ in gemini.MODELS])
    with pytest.raises(GeminiQuotaError):
        f.client().generate_json("s", [text_part("x")], SCHEMA)
    with pytest.raises(GeminiQuotaError):
        f.client().generate_json("s", [text_part("x")], SCHEMA)
    assert len(f.calls) == len(gemini.MODELS)


def test_bad_key_stops_immediately():
    f = Fake(err(400, "API key not valid. Please pass a valid API key."), ok())
    with pytest.raises(GeminiError, match="Settings"):
        f.client().generate_json("s", [text_part("x")], SCHEMA)
    assert len(f.calls) == 1


def test_max_tokens_moves_to_next_model():
    f = Fake(ok(finish="MAX_TOKENS"), ok('{"b": 3}'))
    g = f.client()
    assert g.generate_json("s", [text_part("x")], SCHEMA) == {"b": 3}
    assert g.last_model == "gemini-3.7-flash"


def test_cache_hit_and_different_image_misses(tmp_path):
    f = Fake(ok(), ok('{"c": 1}'))
    g = f.client(cache_dir=tmp_path)
    parts = [text_part("x"), image_part(b"img1")]
    assert g.generate_json("s", parts, SCHEMA) == {"a": 1}
    assert g.generate_json("s", parts, SCHEMA) == {"a": 1}
    assert len(f.calls) == 1 and g.last_model == "cache"
    assert g.generate_json("s", [text_part("x"), image_part(b"img2")], SCHEMA) == {"c": 1}
    assert len(f.calls) == 2
    assert KEY not in "".join(p.read_text() for p in tmp_path.iterdir())


def test_throttle_waits_between_requests():
    f = Fake(ok(), ok())
    g = f.client()
    g.generate_json("s", [text_part("1")], SCHEMA)
    g.generate_json("s", [text_part("2")], SCHEMA)
    assert f.sleeps == [pytest.approx(6.5)]


def test_no_key_and_check_key():
    f = Fake()
    with pytest.raises(GeminiError):
        Gemini("  ", post=f.post).generate_json("s", [], SCHEMA)
    assert f.calls == []
    assert Fake(FakeResponse(200, "{}")).client().check_key() == (True, "Gemini key works")
    works, msg = Fake(err(400, "API key not valid")).client().check_key()
    assert works is False and msg


def test_key_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    f = Fake(per_day(), ok())
    f.client().generate_json("s", [text_part("x")], SCHEMA)
    f2 = Fake(err(400, "API key not valid"))
    with pytest.raises(GeminiError):
        f2.client().generate_json("s", [text_part("y")], SCHEMA)
    assert KEY not in caplog.text

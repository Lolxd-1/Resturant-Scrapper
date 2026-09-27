"""Offline HTTP fakes and shared fixtures used across the test suite."""
from __future__ import annotations

import json

import pytest
from openpyxl import Workbook


class FakeResponse:
    def __init__(self, status_code=200, text="", content=None, headers=None, url=""):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers if headers is not None else {}
        self.url = url

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.routes: dict[str, list] = {}
        self.calls: list[tuple[str, dict | None]] = []

    def add(self, url_prefix, *responses):
        self.routes.setdefault(url_prefix, []).extend(responses)

    def _next(self, url):
        matches = [prefix for prefix in self.routes if url.startswith(prefix)]
        if not matches:
            return FakeResponse(404, "not found", url=url)
        prefix = max(matches, key=len)
        queue = self.routes[prefix]
        item = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, params=None, timeout=None, **kw):
        self.calls.append((url, params))
        return self._next(url)

    def post(self, url, data=None, files=None, timeout=None, **kw):
        self.calls.append((url, data))
        return self._next(url)


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("MENUSTUDIO_HOME", str(home))
    return home


def make_xlsx(path, rows, sheet_title="Sheet1"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path

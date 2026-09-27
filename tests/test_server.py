"""Tests for studio.server (FastAPI app, background worker, SSE) — offline (FakeSession HTTP)."""
from __future__ import annotations

import io
import json
import time
import zipfile

from fastapi.testclient import TestClient

from studio import server as server_mod
from studio.models import PoolItem, RestaurantMenu
from studio.pipeline import Engine
from studio.store import PoolStore
from studio.zomato import Http
from tests.conftest import FakeResponse, FakeSession, make_xlsx
from tests.test_pipeline import FoodVision, noise_jpeg

IMG = "https://b.zmtcdn.com/data/dish/"
RES_URL = "https://www.zomato.com/pune/pizza-place"


def _build_engine(tmp_path) -> Engine:
    session = FakeSession()
    http = Http(session=session, min_interval=0.0, sleep=lambda s: None)
    url = IMG + "cheese1.jpg"
    session.add(url, FakeResponse(200, content=noise_jpeg(1)))
    store = PoolStore(tmp_path / "pool.sqlite")
    items = [PoolItem(0, "Cheese Pizza", "Pizza", "Delivery", "", "veg", url,
                      "r1", "Pizza Place", RES_URL, "pune", "")]
    store.upsert_menu(RestaurantMenu("r1", "Pizza Place", RES_URL, "pune", "", items))
    return Engine(store, FoodVision(), http)


def make_app(tmp_path, start_worker=True):
    engine = _build_engine(tmp_path)
    output_dir = tmp_path / "outputs"
    config_path = tmp_path / "config" / "settings.json"

    def factory():
        return engine

    app = server_mod.create_app(engine_factory=factory, output_dir=output_dir,
                                config_path=config_path, start_worker=start_worker)
    return app, output_dir, config_path


def wait_for_engine(app, timeout=5.0):
    worker = app.state.worker
    deadline = time.time() + timeout
    while worker.engine is None and time.time() < deadline:
        time.sleep(0.02)
    assert worker.engine is not None


def upload_menu(client, tmp_path, rows, name="menu.xlsx"):
    path = make_xlsx(tmp_path / name, [["Item Name", "Category", "Description", "Price"], *rows])
    with open(path, "rb") as f:
        return client.post(
            "/api/menu/preview",
            files={"file": (name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )


def _disable_live_search(client):
    r = client.put("/api/settings", json={
        "imgbb_keys": [], "strictness": "balanced", "live_search": False,
        "live_budget_menus": 0, "default_city": "pune",
    })
    assert r.status_code == 200


def _run_simple_job(client, tmp_path, vendor="Test Cafe"):
    _disable_live_search(client)
    r = upload_menu(client, tmp_path, [["Cheese Pizza", "Pizza", "", 199]])
    assert r.status_code == 200
    upload_id = r.json()["upload_id"]
    r2 = client.post("/api/jobs", json={"upload_id": upload_id, "vendor": vendor, "city": "pune"})
    assert r2.status_code == 200
    job_id = r2.json()["id"]

    deadline = time.time() + 30
    job = None
    while time.time() < deadline:
        jr = client.get(f"/api/jobs/{job_id}")
        job = jr.json()
        if job["job"]["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.1)
    assert job is not None and job["job"]["status"] == "done", job
    return job_id, job


# ---- TC1 ----

def test_health_and_index(tmp_path):
    app, *_ = make_app(tmp_path)
    client = TestClient(app)

    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app": "menustudio", "version": server_mod.studio.__version__}

    r2 = client.get("/")
    assert r2.status_code == 200
    assert "Menu Studio" in r2.text


# ---- TC2 ----

def test_settings_roundtrip_and_validation(tmp_path):
    app, *_ = make_app(tmp_path)
    client = TestClient(app)
    key1 = "a" * 32
    key2 = "b" * 32

    r = client.put("/api/settings", json={
        "imgbb_keys": [{"label": "One", "key": key1, "enabled": True},
                       {"label": "Two", "key": key2, "enabled": True}],
        "strictness": "balanced", "live_search": True, "live_budget_menus": 100, "default_city": "pune",
    })
    assert r.status_code == 200
    assert key1 not in r.text and key2 not in r.text
    body = r.json()
    assert [k["tail"] for k in body["imgbb_keys"]] == [key1[-4:], key2[-4:]]

    r2 = client.get("/api/settings")
    assert key1 not in r2.text and key2 not in r2.text
    assert sorted(r2.json()["cities"]) == r2.json()["cities"]

    r3 = client.put("/api/settings", json={"imgbb_keys": [{"id": 0, "label": "Main"}]})
    assert r3.status_code == 200
    assert r3.json()["imgbb_keys"][0]["tail"] == key1[-4:]
    assert r3.json()["imgbb_keys"][0]["label"] == "Main"

    r4 = client.put("/api/settings", json={"imgbb_keys": [{"label": "Bad", "key": "short"}]})
    assert r4.status_code == 400
    assert r4.json()["detail"] == "That doesn't look like an ImgBB key"


# ---- TC3 ----

def test_menu_preview(tmp_path):
    app, *_ = make_app(tmp_path)
    client = TestClient(app)

    r = upload_menu(client, tmp_path, [["Cheese Pizza", "Pizza", "", 199], ["Cold Coffee", "Beverages", "", 120]])
    assert r.status_code == 200
    data = r.json()
    assert data["rows"][0]["name"] == "Cheese Pizza"
    assert {c["name"] for c in data["categories"]} == {"Pizza", "Beverages"}
    assert data["upload_id"]

    xls_path = tmp_path / "menu.xls"
    xls_path.write_bytes(b"not really an xls file")
    with open(xls_path, "rb") as f:
        r2 = client.post("/api/menu/preview", files={"file": ("menu.xls", f, "application/vnd.ms-excel")})
    assert r2.status_code == 200
    assert r2.json()["errors"]

    big = b"0" * (11 * 1024 * 1024)
    r3 = client.post("/api/menu/preview", files={"file": ("big.xlsx", io.BytesIO(big), "application/octet-stream")})
    assert r3.status_code == 413


# ---- TC4 ----

def test_job_flow_files_and_zip(tmp_path):
    app, output_dir, config_path = make_app(tmp_path)
    client = TestClient(app)
    wait_for_engine(app)

    job_id, job = _run_simple_job(client, tmp_path)
    assert job["results"]

    r = client.get(f"/api/jobs/{job_id}/files/ready")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"

    r2 = client.get(f"/api/jobs/{job_id}/zip")
    assert r2.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r2.content)).namelist()
    assert sum(1 for n in names if n.endswith(".xlsx")) == 3


# ---- TC5 ----

def test_events_replay_includes_done_and_closes(tmp_path):
    app, *_ = make_app(tmp_path)
    client = TestClient(app)
    wait_for_engine(app)

    job_id, _job = _run_simple_job(client, tmp_path)

    r = client.get(f"/api/jobs/{job_id}/events?after=-1")
    assert r.status_code == 200
    events = []
    for block in r.text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    assert any(e["type"] == "done" for e in events)


# ---- TC6 ----

def test_validation_404_and_400(tmp_path):
    app, *_ = make_app(tmp_path)
    client = TestClient(app)

    r = client.get("/api/jobs/../../etc/files/ready")
    assert r.status_code == 404

    job_id, _job = _run_simple_job(client, tmp_path)
    r2 = client.get(f"/api/jobs/{job_id}/files/unknownkind")
    assert r2.status_code == 404

    r3 = client.post("/api/jobs", json={"vendor": "", "upload_id": "x"})
    assert r3.status_code == 400


# ---- TC7 ----

def test_choose_null_marks_needs_photo(tmp_path):
    app, *_ = make_app(tmp_path)
    client = TestClient(app)
    wait_for_engine(app)

    job_id, job = _run_simple_job(client, tmp_path)
    sku = job["results"][0]["sku"]

    r = client.post(f"/api/jobs/{job_id}/dishes/{sku}/choose", json={"alt_index": None})
    assert r.status_code == 200
    assert r.json()["status"] == "needs_photo"


# ---- TC8 ----

def test_app_self_test():
    import app as app_module
    assert app_module.main(["--self-test"]) == 0

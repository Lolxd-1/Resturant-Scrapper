"""Tests for studio.pipeline.choose_alternate and the zomato_scrapper.py headless CLI."""
from __future__ import annotations

import os
import threading
import time

import pytest

from studio import imaging, pipeline
from studio.pipeline import JobOptions, choose_alternate
from studio.sheets import safe_vendor
from tests.test_pipeline import Env, branded_jpeg, sheet
from tests.test_sheets import make_template
from zomato_scrapper import main


@pytest.fixture(autouse=True)
def small_template(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "TEMPLATE_PATH", make_template(tmp_path / "template.xlsx"))


def _seeded_env(tmp_path):
    env = Env(tmp_path)
    env.pool("pizza-place", [("Cheese Pizza", "Pizza", "veg", "cheese1")])
    env.pool("cafe-two", [("Cheese Pizza", "Pizza", "veg", "cheese2")])
    menu = env.menu([["Cheese Pizza", "Pizza", "", 199]])
    engine = env.engine()
    env.run(menu, JobOptions(vendor="Test Cafe", live_search=False), engine=engine)
    return env, engine


# ---- TC1: swapping to an alternate rebuilds the sheets ----

def test_choose_alternate_swaps_photo_and_rebuilds(tmp_path):
    env, engine = _seeded_env(tmp_path)
    job_dir = tmp_path / "job1"
    before = env.results()["Cheese Pizza"]
    assert before["alternates"], "test setup should give this dish an alternate"
    old_img = before["zomato_img"]
    alt_img = before["alternates"][0]["zomato_img"]

    ready_path = job_dir / f"{safe_vendor('Test Cafe')}_SmartBiz_UPLOAD_READY.xlsx"
    old_time = ready_path.stat().st_mtime - 100
    os.utime(ready_path, (old_time, old_time))

    result = choose_alternate(engine, job_dir, before["sku"], 0, env.uploader)

    assert result.zomato_img == alt_img
    assert any(a["zomato_img"] == old_img for a in result.alternates)
    assert result.status == "ready"

    after = env.results()["Cheese Pizza"]
    assert after["zomato_img"] == alt_img
    assert any(a["zomato_img"] == old_img for a in after["alternates"])

    assert ready_path.stat().st_mtime > old_time
    ws = sheet(env, "Test Cafe", "UPLOAD_READY")
    assert ws["P2"].value == result.hosted_url


def test_fix3_tc6_choose_alternate_rejects_branded_photo(tmp_path, monkeypatch):
    env, engine = _seeded_env(tmp_path)
    before = env.results()["Cheese Pizza"]
    monkeypatch.setattr(imaging, "fetch_full", lambda url, http: (branded_jpeg("ZOMATO"), (420, 420)))

    with pytest.raises(ValueError, match="That photo shows zomato branding — pick another"):
        choose_alternate(engine, tmp_path / "job1", before["sku"], 0, env.uploader)

    assert env.results()["Cheese Pizza"]["zomato_img"] == before["zomato_img"]


# ---- TC2: marking a dish as needing an owner photo ----

def test_choose_alternate_mark_needs_photo(tmp_path):
    env, engine = _seeded_env(tmp_path)
    job_dir = tmp_path / "job1"
    before = env.results()["Cheese Pizza"]

    result = choose_alternate(engine, job_dir, before["sku"], None, env.uploader)

    assert result.status == "needs_photo"
    assert result.reason == "Marked by you: needs owner photo"
    assert result.local_image == "" and result.hosted_url == "" and result.zomato_img == ""
    assert any(a["zomato_img"] == before["zomato_img"] for a in result.alternates)

    assert sheet(env, "Test Cafe", "UPLOAD_READY")["D2"].value is None
    assert sheet(env, "Test Cafe", "PENDING")["D2"].value == "Cheese Pizza"


# ---- TC3: bad inputs raise ValueError ----

def test_choose_alternate_errors(tmp_path):
    env, engine = _seeded_env(tmp_path)
    job_dir = tmp_path / "job1"
    sku = env.results()["Cheese Pizza"]["sku"]

    with pytest.raises(ValueError):
        choose_alternate(engine, job_dir, "NOPE-999", 0, env.uploader)

    with pytest.raises(ValueError):
        choose_alternate(engine, job_dir, sku, 99, env.uploader)


# ---- FIX1 TC1: concurrent swaps on one job keep both edits ----

def test_fix1_tc1_concurrent_swaps_keep_both_edits(tmp_path, monkeypatch):
    env = Env(tmp_path)
    env.pool("pizza-place", [("Cheese Pizza", "Pizza", "veg", "cheese1"), ("Veg Burger", "Burgers", "veg", "burger1")])
    env.pool("cafe-two", [("Cheese Pizza", "Pizza", "veg", "cheese2"), ("Veg Burger", "Burgers", "veg", "burger2")])
    menu = env.menu([["Cheese Pizza", "Pizza", "", 199], ["Veg Burger", "Burgers", "", 149]])
    engine = env.engine()
    env.run(menu, JobOptions(vendor="Test Cafe", live_search=False), engine=engine)
    job_dir = tmp_path / "job1"
    pizza, burger = env.results()["Cheese Pizza"], env.results()["Veg Burger"]
    assert pizza["alternates"] and burger["zomato_img"], "test setup should give both dishes photos"
    alt_img = pizza["alternates"][0]["zomato_img"]

    real_fetch = imaging.fetch_full
    first_fetching = threading.Event()

    def slow_fetch(url, http):
        first_fetching.set()
        time.sleep(0.3)
        return real_fetch(url, http)

    monkeypatch.setattr(imaging, "fetch_full", slow_fetch)
    swap = threading.Thread(target=choose_alternate,
                            args=(engine, job_dir, pizza["sku"], 0, env.uploader), kwargs={"rebuild": False})
    swap.start()
    assert first_fetching.wait(5)
    mark = threading.Thread(target=choose_alternate,
                            args=(engine, job_dir, burger["sku"], None, env.uploader), kwargs={"rebuild": False})
    mark.start()
    swap.join(10)
    mark.join(10)

    after = env.results()
    assert after["Cheese Pizza"]["zomato_img"] == alt_img
    assert after["Veg Burger"]["status"] == "needs_photo"
    assert after["Veg Burger"]["zomato_img"] == ""


# ---- TC4: CLI, no upload ----

def test_cli_no_upload(tmp_path, monkeypatch, capsys):
    env = Env(tmp_path)
    env.pool("pizza-place", [("Cheese Pizza", "Pizza", "veg", "cheese1")])
    menu = env.menu([["Cheese Pizza", "Pizza", "", 199]])
    monkeypatch.setattr(pipeline, "build_engine", lambda *a, **kw: env.engine())
    out_dir = tmp_path / "out"

    rc = main(["--menu-excel", str(menu), "--vendor", "Test Cafe", "--no-upload",
              "--no-live-search", "--out", str(out_dir)])

    assert rc == 0
    stem = safe_vendor("Test Cafe")
    for fname in (f"{stem}_SmartBiz_UPLOAD_READY.xlsx", f"{stem}_SmartBiz_PENDING.xlsx",
                 f"{stem}_Photo_Report.xlsx"):
        assert (out_dir / fname).is_file()
    assert "UPLOAD_READY" in capsys.readouterr().out


# ---- TC5: CLI, unreadable menu file ----

def test_cli_bad_file(tmp_path, monkeypatch, capsys):
    env = Env(tmp_path)
    monkeypatch.setattr(pipeline, "build_engine", lambda *a, **kw: env.engine())
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not an excel file", encoding="utf-8")

    rc = main(["--menu-excel", str(bad), "--vendor", "Test Cafe", "--no-upload",
              "--no-live-search", "--out", str(tmp_path / "out2")])

    assert rc == 1
    assert "Could not open the file" in capsys.readouterr().out

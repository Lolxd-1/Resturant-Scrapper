"""Tests for studio.store.PoolStore (offline; no network access)."""
from __future__ import annotations

import gzip
import json
import threading
import time

import numpy as np
import pytest

from studio.models import PoolItem, RestaurantMenu
from studio.store import PoolStore


def make_menu(res_id, name, url, city="pune", cuisines="North Indian", items=None):
    return RestaurantMenu(res_id=res_id, name=name, url=url, city=city, cuisines=cuisines, items=items or [])


def make_item(name, category, menu_name, description, diet, img_url, res_id, res_name, res_url, city):
    return PoolItem(
        item_id=0, name=name, category=category, menu_name=menu_name, description=description,
        diet=diet, img_url=img_url, res_id=res_id, res_name=res_name, res_url=res_url, city=city,
        chain_key="",
    )


def write_seed(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ---- TC1: upsert_menu then all_items, counts ----

def test_tc1_upsert_menu_and_all_items(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    url = "https://www.zomato.com/pune/test-res"
    items = [
        make_item("Chicken Biryani", "Mains", "Menu A", "Spicy biryani", "nonveg",
                   "https://b.zmtcdn.com/img1.jpg", "1", "Test Res", url, "pune"),
    ]
    menu = make_menu("1", "Test Res", url, items=items)
    inserted = store.upsert_menu(menu)
    assert inserted == 1

    all_items = store.all_items()
    assert len(all_items) == 1
    item = all_items[0]
    assert item.name == "Chicken Biryani"
    assert item.res_name == "Test Res"
    assert item.res_url == url
    assert item.city == "pune"
    assert item.chain_key == "test res"
    assert store.count_items() == 1
    assert store.count_restaurants() == 1
    store.close()


# ---- TC2: upsert_menu twice replaces items, updates fetched_at ----

def test_tc2_upsert_menu_replaces_items(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    url = "https://www.zomato.com/pune/test-res"
    item1 = make_item("Dish A", "Mains", "Menu", "", "veg", "https://b.zmtcdn.com/a.jpg", "1", "R", url, "pune")
    menu1 = make_menu("1", "R", url, items=[item1])
    store.upsert_menu(menu1)
    t1 = store.menu_fetched_at(url)

    item2 = make_item("Dish B", "Mains", "Menu", "", "veg", "https://b.zmtcdn.com/b.jpg", "1", "R", url, "pune")
    menu2 = make_menu("1", "R", url, items=[item2])
    store.upsert_menu(menu2)
    t2 = store.menu_fetched_at(url)

    items = store.items_for_restaurant(url)
    assert len(items) == 1
    assert items[0].name == "Dish B"
    assert store.count_items() == 1
    assert t2 >= t1
    store.close()


# ---- TC3: ensure_seeded imports gzip JSONL, second call no-op, malformed skipped, live not overwritten ----

def test_tc3_ensure_seeded(tmp_path):
    seed_path = tmp_path / "seed.jsonl.gz"
    rows = []
    for i in range(3):
        res_url = f"https://www.zomato.com/pune/res-{i}"
        rows.append({"r": res_url, "rn": f"Res {i}", "c": "pune", "n": f"Item {i}",
                     "cat": "Mains", "m": "Menu", "d": "desc", "dt": "veg",
                     "i": f"https://b.zmtcdn.com/{i}.jpg"})
    seed_lines = [json.dumps(r) for r in rows]
    seed_lines.append("not valid json {")

    with gzip.open(seed_path, "wt", encoding="utf-8") as f:
        for line in seed_lines:
            f.write(line + "\n")

    store = PoolStore(tmp_path / "pool.db")

    # restaurant 0 already stored as "live" before seeding -> must not be overwritten
    live_url = "https://www.zomato.com/pune/res-0"
    live_item = make_item("Live Item", "Mains", "Menu", "", "veg",
                           "https://b.zmtcdn.com/live.jpg", "99", "Live Res", live_url, "pune")
    store.upsert_menu(make_menu("99", "Live Res", live_url, items=[live_item]))

    inserted = store.ensure_seeded(seed_path)
    assert inserted == 2  # only res-1 and res-2 seeded; res-0 skipped (already live)

    assert store.count_restaurants() == 3
    live_items = store.items_for_restaurant(live_url)
    assert len(live_items) == 1
    assert live_items[0].name == "Live Item"

    seeded_items = store.items_for_restaurant("https://www.zomato.com/pune/res-1")
    assert len(seeded_items) == 1
    assert seeded_items[0].name == "Item 1"
    assert store.menu_fetched_at("https://www.zomato.com/pune/res-1") == 0.0

    second = store.ensure_seeded(seed_path)
    assert second == 0
    store.close()


def test_tc3_ensure_seeded_missing_file(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    assert store.ensure_seeded(tmp_path / "missing.jsonl.gz") == 0
    store.close()


# ---- TC4: uploads ----

def test_tc4_uploads(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    assert store.get_upload("abc123") is None
    store.put_upload("abc123", "https://i.ibb.co/xyz.jpg", "imgbb")
    assert store.get_upload("abc123") == "https://i.ibb.co/xyz.jpg"
    store.close()


# ---- TC5: embeddings round-trip float32 dim 512 ----

def test_tc5_embeddings_roundtrip(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    vec = np.random.rand(512).astype(np.float32)
    store.put_embedding("key1", vec)
    got = store.get_embedding("key1")
    assert got is not None
    assert got.dtype == np.float32
    assert np.array_equal(got, vec)
    assert store.get_embedding("missing") is None
    store.close()


# ---- TC6: bad images ----

def test_tc6_bad_images(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    assert store.is_bad_image("https://b.zmtcdn.com/bad.jpg") is False
    store.mark_bad_image("https://b.zmtcdn.com/bad.jpg", "not food")
    assert store.is_bad_image("https://b.zmtcdn.com/bad.jpg") is True
    assert store.is_bad_image("https://b.zmtcdn.com/other.jpg") is False
    store.close()


# ---- FIX2 TC3: is_bad_image ignores marks whose reason starts with "network" (defensive, old DBs) ----

def test_fix2_tc3_is_bad_image_ignores_network_reason(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    store.mark_bad_image("https://b.zmtcdn.com/flaky.jpg", "network")
    assert store.is_bad_image("https://b.zmtcdn.com/flaky.jpg") is False
    store.mark_bad_image("https://b.zmtcdn.com/gone.jpg", "download failed")
    assert store.is_bad_image("https://b.zmtcdn.com/gone.jpg") is True
    store.close()


# ---- TC7: unicode round-trip ----

def test_tc7_unicode_roundtrip(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    url = "https://www.zomato.com/pune/unicode-res"
    item = make_item("बिरयानी éè", "Mains", "Menu", "स्वादिष्ट भोजन 🍛", "nonveg",
                       "https://b.zmtcdn.com/u.jpg", "1", "ज्ञ Res", url, "pune")
    store.upsert_menu(make_menu("1", "ज्ञ Res", url, items=[item]))
    got = store.items_for_restaurant(url)[0]
    assert got.name == "बिरयानी éè"
    assert got.description == "स्वादिष्ट भोजन 🍛"
    assert got.res_name == "ज्ञ Res"
    store.close()


# ---- TC8: thread-safety, 4 threads x 25 upserts ----

def test_tc8_thread_safety(tmp_path):
    store = PoolStore(tmp_path / "pool.db")
    errors = []

    def worker(thread_id):
        try:
            for i in range(25):
                url = f"https://www.zomato.com/pune/res-{thread_id}-{i}"
                item = make_item(f"Dish {i}", "Mains", "Menu", "", "veg",
                                   f"https://b.zmtcdn.com/{thread_id}-{i}.jpg", str(i),
                                   f"Res {thread_id}-{i}", url, "pune")
                store.upsert_menu(make_menu(str(i), f"Res {thread_id}-{i}", url, items=[item]))
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert store.count_restaurants() == 100
    store.close()


# ---- TC10: items_for_restaurant scales with the restaurant's own items, not the whole pool ----

def test_tc10_items_for_restaurant_is_scoped_not_a_full_scan(tmp_path, monkeypatch):
    store = PoolStore(tmp_path / "pool.db")
    res_rows = []
    item_rows = []
    for r in range(200):
        url = f"https://www.zomato.com/pune/res-{r}"
        res_rows.append((url, str(r), f"Res {r}", "pune", "", f"res {r}", 0.0, "seed"))
        for i in range(100):
            item_rows.append((url, f"Item {i}", "Mains", "Menu", "", "veg", f"https://b.zmtcdn.com/{r}-{i}.jpg"))
    with store._conn:
        store._conn.executemany(
            "INSERT INTO restaurants (res_url, res_id, name, city, cuisines, chain_key, fetched_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            res_rows,
        )
        store._conn.executemany(
            "INSERT INTO items (res_url, name, category, menu_name, description, diet, img_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            item_rows,
        )
    assert store.count_items() == 20_000

    target_url = "https://www.zomato.com/pune/res-199"
    item = make_item("New Dish", "Mains", "Menu", "", "veg", "https://b.zmtcdn.com/new.jpg",
                      "199", "Res 199", target_url, "pune")
    store.upsert_menu(make_menu("199", "Res 199", target_url, items=[item]))

    def boom():
        raise AssertionError("items_for_restaurant must not call all_items()")

    monkeypatch.setattr(store, "all_items", boom)

    t0 = time.perf_counter()
    items = store.items_for_restaurant(target_url)
    elapsed = time.perf_counter() - t0

    assert len(items) == 1
    assert items[0].name == "New Dish"
    assert elapsed < 0.05
    store.close()


# ---- TC9: reopening the same path sees previous data ----

def test_tc9_reopen_sees_previous_data(tmp_path):
    path = tmp_path / "pool.db"
    store = PoolStore(path)
    url = "https://www.zomato.com/pune/persisted-res"
    item = make_item("Dish", "Mains", "Menu", "", "veg", "https://b.zmtcdn.com/p.jpg",
                       "1", "Persisted Res", url, "pune")
    store.upsert_menu(make_menu("1", "Persisted Res", url, items=[item]))
    store.close()

    store2 = PoolStore(path)
    assert store2.count_restaurants() == 1
    assert store2.count_items() == 1
    items = store2.items_for_restaurant(url)
    assert len(items) == 1
    assert items[0].name == "Dish"
    store2.close()

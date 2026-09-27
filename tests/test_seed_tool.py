"""Tests for tools.build_seed_pool (offline; no real network access)."""
from __future__ import annotations

import gzip
import json

import pytest

import tools.build_seed_pool as build_seed_pool
from studio.models import PoolItem, RestaurantMenu
from studio.store import PoolStore
from studio.zomato import Http, ZomatoBlocked, ZomatoClient
from tools.build_seed_pool import _build_parser, crawl, export_seed, import_cache, import_pairs
from tests.conftest import FakeResponse, FakeSession
from tests.fixtures.zomato.make_pages import item, menu_state, state_html


def _mk_item(res_url, res_name, city, name, category="Mains", menu_name="Menu",
             description="", diet="veg", img_url="https://b.zmtcdn.com/x.jpg"):
    return PoolItem(
        item_id=0, name=name, category=category, menu_name=menu_name, description=description,
        diet=diet, img_url=img_url, res_id="r", res_name=res_name, res_url=res_url,
        city=city, chain_key="",
    )


# ---- TC1: import_cache on synthetic order pages -> restaurants + items stored ----

def test_tc1_import_cache_two_pages(tmp_path):
    cache_dir = tmp_path / "zcache"
    cache_dir.mkdir()
    state1 = menu_state(1, "Res One", "/pune/res-one", menus=[
        ("Menu", [("Mains", [item("Chicken Biryani", "https://b.zmtcdn.com/a.jpg", diet="nonveg")])]),
    ])
    state2 = menu_state(2, "Res Two", "/mumbai/res-two", menus=[
        ("Menu", [("Starters", [item("Paneer Tikka", "https://b.zmtcdn.com/b.jpg", diet="veg")])]),
    ])
    (cache_dir / "https_www_zomato_com_pune_res_one_order.html").write_text(state_html(state1), encoding="utf-8")
    (cache_dir / "https_www_zomato_com_mumbai_res_two_order.html").write_text(state_html(state2), encoding="utf-8")

    store = PoolStore(tmp_path / "pool.sqlite")
    imported = import_cache(store, cache_dir)
    assert imported == 2
    assert store.count_restaurants() == 2

    by_name = {it.name: it for it in store.all_items()}
    assert by_name["Chicken Biryani"].category == "Mains"
    assert by_name["Chicken Biryani"].diet == "nonveg"
    assert by_name["Paneer Tikka"].category == "Starters"
    assert by_name["Paneer Tikka"].diet == "veg"
    store.close()


def test_tc1_import_cache_missing_dir_returns_zero(tmp_path):
    store = PoolStore(tmp_path / "pool.sqlite")
    assert import_cache(store, tmp_path / "nope") == 0
    store.close()


# ---- TC2: import_pairs skips slugs already in the store, infers diet ----

def test_tc2_import_pairs_skips_existing_and_infers_diet(tmp_path):
    store = PoolStore(tmp_path / "pool.sqlite")
    existing_url = "https://www.zomato.com/pune/existing-slug"
    store.upsert_menu(RestaurantMenu(
        res_id="1", name="Existing", url=existing_url, city="pune", cuisines="",
        items=[_mk_item(existing_url, "Existing", "pune", "Whatever")],
    ))

    pairs_path = tmp_path / "pairs.json"
    pairs_path.write_text(json.dumps([
        {"name": "Should Be Skipped", "img": "https://b.zmtcdn.com/z.jpg", "rest": "existing-slug"},
        {"name": "Chicken Tikka", "img": "https://b.zmtcdn.com/c.jpg", "rest": "new-slug"},
        {"name": "Paneer Tikka", "img": "https://b.zmtcdn.com/p.jpg", "rest": "new-slug"},
    ]), encoding="utf-8")

    imported = import_pairs(store, pairs_path)
    assert imported == 2

    all_items = store.all_items()
    assert not any(it.name == "Should Be Skipped" for it in all_items)

    new_items = {it.name: it for it in all_items if it.res_url.endswith("/new-slug")}
    assert set(new_items) == {"Chicken Tikka", "Paneer Tikka"}
    assert new_items["Chicken Tikka"].diet == "nonveg"
    assert new_items["Paneer Tikka"].diet == "unknown"
    store.close()


def test_tc2_import_pairs_missing_file_returns_zero(tmp_path):
    store = PoolStore(tmp_path / "pool.sqlite")
    assert import_pairs(store, tmp_path / "nope.json") == 0
    store.close()


# ---- TC3: crawl dedupes a restaurant shared across listings; fetches each once ----

class _FakeCrawlClient:
    def __init__(self, listings, menus):
        self.listings = listings
        self.menus = menus
        self.fetch_calls: list[str] = []
        self.listing_calls: list[tuple[str, str]] = []

    def listing(self, city, cuisine):
        self.listing_calls.append((city, cuisine))
        result = self.listings.get((city, cuisine), [])
        if isinstance(result, Exception):
            raise result
        return list(result)

    def fetch_menu(self, url):
        self.fetch_calls.append(url)
        result = self.menus.get(url)
        if isinstance(result, Exception):
            raise result
        return result


def _make_crawl_fixture():
    url_a = "https://www.zomato.com/pune/res-a"
    url_b = "https://www.zomato.com/pune/res-b"
    url_c = "https://www.zomato.com/mumbai/res-c"
    listings = {
        ("pune", "north-indian"): [url_a, url_b],
        ("mumbai", "north-indian"): [url_b, url_c],
    }
    menus = {
        url_a: RestaurantMenu(res_id="a", name="A", url=url_a, city="pune", cuisines="",
                               items=[_mk_item(url_a, "A", "pune", "Dish A")]),
        url_b: RestaurantMenu(res_id="b", name="B", url=url_b, city="pune", cuisines="",
                               items=[_mk_item(url_b, "B", "pune", "Dish B")]),
        url_c: RestaurantMenu(res_id="c", name="C", url=url_c, city="mumbai", cuisines="",
                               items=[_mk_item(url_c, "C", "mumbai", "Dish C")]),
    }
    return listings, menus, (url_a, url_b, url_c)


def test_tc3_crawl_dedupes_shared_restaurant(tmp_path):
    listings, menus, (url_a, url_b, url_c) = _make_crawl_fixture()
    client = _FakeCrawlClient(listings, menus)
    store = PoolStore(tmp_path / "pool.sqlite")

    fetched = crawl(store, client, ["pune", "mumbai"], ["north-indian"], max_restaurants=10, workers=2)

    assert fetched == 3
    assert client.fetch_calls.count(url_b) == 1
    assert sorted(client.fetch_calls) == sorted([url_a, url_b, url_c])
    assert store.count_restaurants() == 3
    store.close()


def test_tc3_crawl_stops_at_max_restaurants(tmp_path):
    listings, menus, (url_a, url_b, url_c) = _make_crawl_fixture()
    client = _FakeCrawlClient(listings, menus)
    store = PoolStore(tmp_path / "pool.sqlite")

    fetched = crawl(store, client, ["pune", "mumbai"], ["north-indian"], max_restaurants=2, workers=1)

    assert fetched == 2
    assert store.count_restaurants() == 2
    assert url_c not in client.fetch_calls
    store.close()


# ---- TC5: blocked twice -> crawl returns without raising ----

def test_tc5_crawl_blocked_twice_returns_cleanly(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(build_seed_pool.time, "sleep", lambda s: sleeps.append(s))

    class _BlockedClient:
        def __init__(self):
            self.listing_calls = 0

        def listing(self, city, cuisine):
            self.listing_calls += 1
            raise ZomatoBlocked("blocked")

        def fetch_menu(self, url):
            raise AssertionError("fetch_menu should never be reached")

    store = PoolStore(tmp_path / "pool.sqlite")
    client = _BlockedClient()

    fetched = crawl(store, client, ["pune", "mumbai"], ["north-indian"], max_restaurants=10, workers=1)

    assert fetched == 0
    assert sleeps == [600]
    assert client.listing_calls == 2
    store.close()


# ---- S2 TC4: --localities N crawls locality listings too; --extra-cities is accepted ----

def test_s2_tc4_crawl_localities_requests_locality_listing_urls(tmp_path):
    fake_session = FakeSession()
    fake_session.add("https://www.zomato.com/pune",
                      FakeResponse(200, text=(
                          '<a href="/pune/kothrud-restaurants">Kothrud</a>'
                          '<a href="/pune/baner-restaurants">Baner</a>'
                          '<a href="/pune/wakad-restaurants">Wakad</a>'
                      )))
    fake_session.add("https://www.zomato.com/pune/restaurants/north-indian", FakeResponse(200, text=""))
    fake_session.add("https://www.zomato.com/pune/kothrud-restaurants/north-indian", FakeResponse(200, text=""))
    fake_session.add("https://www.zomato.com/pune/baner-restaurants/north-indian", FakeResponse(200, text=""))
    http = Http(session=fake_session, min_interval=0.0, sleep=lambda s: None)
    client = ZomatoClient(http)
    store = PoolStore(tmp_path / "pool.sqlite")

    crawl(store, client, ["pune"], ["north-indian"], max_restaurants=10, workers=1, localities=2)

    called = {url for url, _ in fake_session.calls}
    assert "https://www.zomato.com/pune/kothrud-restaurants/north-indian" in called
    assert "https://www.zomato.com/pune/baner-restaurants/north-indian" in called
    assert "https://www.zomato.com/pune/wakad-restaurants/north-indian" not in called
    store.close()


def test_s2_tc4_extra_cities_flag_accepted():
    args = _build_parser().parse_args(["--crawl", "--extra-cities", "kolhapur,satara", "--localities", "2"])
    assert args.extra_cities == "kolhapur,satara"
    assert args.localities == 2


# ---- TC4: export_seed -> gzip JSONL with the exact seed keys; ensure_seeded round-trips ----

def test_tc4_export_seed_shape_and_roundtrip(tmp_path):
    store = PoolStore(tmp_path / "pool.sqlite")
    url = "https://www.zomato.com/pune/res-a"
    long_desc = "x" * 300
    items = [
        _mk_item(url, "Res A", "pune", "B Dish", description=long_desc, diet="veg",
                  img_url="https://b.zmtcdn.com/b.jpg"),
        _mk_item(url, "Res A", "pune", "A Dish", diet="nonveg", img_url="https://b.zmtcdn.com/a.jpg"),
        _mk_item(url, "Res A", "pune", "No Image", img_url=""),
    ]
    store.upsert_menu(RestaurantMenu(res_id="1", name="Res A", url=url, city="pune", cuisines="", items=items))

    out_path = tmp_path / "seed.jsonl.gz"
    stats = export_seed(store, out_path)

    assert stats == {"restaurants": 1, "items": 2, "bytes": out_path.stat().st_size}

    with gzip.open(out_path, "rt", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]

    assert len(lines) == 2
    for line in lines:
        assert set(line) == {"r", "rn", "c", "n", "cat", "m", "d", "dt", "i"}
    assert [line["n"] for line in lines] == ["A Dish", "B Dish"]
    assert len(next(l for l in lines if l["n"] == "B Dish")["d"]) == 200

    fresh = PoolStore(tmp_path / "pool2.sqlite")
    inserted = fresh.ensure_seeded(out_path)
    assert inserted == 2
    assert fresh.count_items() == 2
    store.close()
    fresh.close()

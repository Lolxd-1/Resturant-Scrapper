"""Tests for studio.swiggy (offline; no real network access)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.swiggy import IMG_BASE, SEARCH_URL, SwiggyBlocked, SwiggyClient, parse_dish_search
from studio.zomato import Http
from tests.conftest import FakeResponse

FIXTURES = Path(__file__).parent / "fixtures" / "swiggy"
DISH_GROUP = "type.googleapis.com/swiggy.presentation.food.v2.DishGroup"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_client(fake_session, **kwargs):
    kwargs.setdefault("min_interval", 0.0)
    kwargs.setdefault("sleep", lambda s: None)
    kwargs.setdefault("clock", lambda: 0.0)
    return SwiggyClient(Http(session=fake_session, **kwargs))


def all_items(menus):
    return [i for m in menus for i in m.items]


def wrap(card):
    return {"data": {"cards": [{"groupedCard": {"cardGroupMap": {"DISH": {"cards": [
        {"card": {"card": card}}]}}}}]}}


def test_tc1_egg_roast_menu_and_item():
    menus = parse_dish_search(json.loads(load("dish_search_egg_roast.json")), "pune")
    vishal = next(m for m in menus if m.url == (
        "https://www.swiggy.com/city/pune/vishal-restaurant-fatima-nagar-wanowrie-rest127657"))
    assert vishal.name == "Vishal Restaurant"
    egg = next(i for i in vishal.items if i.name == "Egg Roast")
    assert egg.diet == "nonveg"
    assert egg.img_url.startswith(IMG_BASE + "FOOD_CATALOG/IMAGES/CMS/2026/1/26/6d4fc1de")
    assert "Appam Egg Roast 3pc" not in [i.name for i in all_items(menus)]


def test_tc2_mushroom_uttapam_item():
    menus = parse_dish_search(json.loads(load("dish_search_mushroom_uttapam.json")), "pune")
    item = next(i for i in all_items(menus) if i.name == "Mushroom Veg Oats Uttapam")
    assert item.diet == "veg"
    assert item.menu_name == "Swiggy"
    assert item.chain_key == "banana leaf"


def test_tc3_malformed_inputs_do_not_raise():
    group = {"@type": DISH_GROUP}
    info = {"id": 1, "name": "R", "slugs": {"restaurant": "r", "city": "pune"}}
    assert parse_dish_search({}, "pune") == []
    assert parse_dish_search({"data": None}, "pune") == []
    assert parse_dish_search(wrap(group), "pune") == []
    nameless = {**group, "restaurant": {"info": info}, "dishes": [{"info": {"imageId": "x"}}]}
    assert parse_dish_search(wrap(nameless), "pune") == []
    mixed = {**group, "restaurant": {"info": info},
             "dishes": [{"info": {"imageId": "x"}}, {"info": {"name": "Dosa", "imageId": "y"}}]}
    assert [i.name for i in all_items(parse_dish_search(wrap(mixed), "pune"))] == ["Dosa"]


def test_tc4_search_dishes_calls_search_url(fake_session):
    fake_session.add(SEARCH_URL, FakeResponse(200, load("dish_search_egg_roast.json")))
    menus = make_client(fake_session).search_dishes("egg roast", "pune")
    assert any(m.name == "Vishal Restaurant" for m in menus)
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0][1] == {
        "lat": "18.5204", "lng": "73.8567", "str": "egg roast",
        "submitAction": "ENTER", "selectedPLTab": "DISH",
    }


def test_tc5_unknown_city_makes_no_request(fake_session):
    assert make_client(fake_session).search_dishes("egg roast", "atlantis") == []
    assert fake_session.calls == []


def test_tc6_403_raises_swiggy_blocked(fake_session):
    fake_session.add(SEARCH_URL, FakeResponse(403, "denied"))
    with pytest.raises(SwiggyBlocked):
        make_client(fake_session, max_retries=0).search_dishes("egg roast", "pune")


def test_tc7_non_json_returns_empty(fake_session):
    fake_session.add(SEARCH_URL, FakeResponse(200, "<html>"))
    assert make_client(fake_session).search_dishes("egg roast", "pune") == []


def test_tc8_bad_status_code_returns_empty(fake_session):
    fake_session.add(SEARCH_URL, FakeResponse(200, '{"statusCode": 1}'))
    assert make_client(fake_session).search_dishes("egg roast", "pune") == []

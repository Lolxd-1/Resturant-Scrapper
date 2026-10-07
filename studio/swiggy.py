"""Swiggy dish search client: one public dish search -> pool items with catalog photos."""
from __future__ import annotations

import json
import logging
import re

from studio.models import PoolItem, RestaurantMenu
from studio.zomato import Http, ZomatoBlocked, chain_key

log = logging.getLogger("studio.swiggy")

SEARCH_URL = "https://www.swiggy.com/dapi/restaurants/search/v3"
IMG_BASE = "https://media-assets.swiggy.com/swiggy/image/upload/"

SWIGGY_CITIES: dict[str, tuple[str, str]] = {
    "pune": ("18.5204", "73.8567"),
    "mumbai": ("19.0760", "72.8777"),
    "ncr": ("28.6139", "77.2090"),
    "bangalore": ("12.9716", "77.5946"),
    "hyderabad": ("17.3850", "78.4867"),
    "chennai": ("13.0827", "80.2707"),
    "kolkata": ("22.5726", "88.3639"),
    "ahmedabad": ("23.0225", "72.5714"),
    "nagpur": ("21.1458", "79.0882"),
    "nashik": ("19.9975", "73.7898"),
    "aurangabad": ("19.8762", "75.3433"),
    "kolhapur": ("16.7050", "74.2433"),
    "indore": ("22.7196", "75.8577"),
    "jaipur": ("26.9124", "75.7873"),
    "surat": ("21.1702", "72.8311"),
}

_WS_RE = re.compile(r"\s+")


class SwiggyBlocked(Exception):
    pass


def _dicts(value) -> list[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _dish_groups(data) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        return []
    groups: list[dict] = []
    for top in _dicts(data["data"].get("cards")):
        grouped = top.get("groupedCard")
        group_map = grouped.get("cardGroupMap") if isinstance(grouped, dict) else None
        dish = group_map.get("DISH") if isinstance(group_map, dict) else None
        for entry in _dicts(dish.get("cards") if isinstance(dish, dict) else None):
            card = entry.get("card")
            card = card.get("card") if isinstance(card, dict) else None
            if isinstance(card, dict) and str(card.get("@type", "")).endswith("DishGroup"):
                groups.append(card)
    return groups


def parse_dish_search(data: dict, city: str) -> list[RestaurantMenu]:
    menus: dict[str, RestaurantMenu] = {}
    seen: dict[str, set[tuple[str, str]]] = {}
    for group in _dish_groups(data):
        restaurant = group.get("restaurant")
        info = restaurant.get("info") if isinstance(restaurant, dict) else None
        if not isinstance(info, dict) or info.get("id") is None or not info.get("name"):
            continue
        res_id = str(info["id"])
        res_name = str(info["name"])
        slugs = info.get("slugs") if isinstance(info.get("slugs"), dict) else {}
        if slugs.get("city") and slugs.get("restaurant"):
            url = f"https://www.swiggy.com/city/{slugs['city']}/{slugs['restaurant']}-rest{res_id}"
        else:
            url = f"https://www.swiggy.com/restaurants/{res_id}"
        menu = menus.get(url)
        if menu is None:
            menu = menus[url] = RestaurantMenu(
                res_id=res_id, name=res_name, url=url,
                city=slugs.get("city") or city, cuisines="", items=[],
            )
            seen[url] = set()
        ck = chain_key(res_name)
        for dish in _dicts(group.get("dishes")):
            dish_info = dish.get("info")
            if not isinstance(dish_info, dict):
                continue
            name = str(dish_info.get("name") or "").strip()
            image_id = dish_info.get("imageId")
            if not name or not image_id:
                continue
            img_url = IMG_BASE + str(image_id)
            if (name, img_url) in seen[url]:
                continue
            seen[url].add((name, img_url))
            menu.items.append(PoolItem(
                item_id=0,
                name=name,
                category=dish_info.get("category") or "",
                menu_name="Swiggy",
                description=_WS_RE.sub(" ", dish_info.get("description") or "").strip()[:300],
                diet="veg" if dish_info.get("isVeg") == 1 else "nonveg",
                img_url=img_url,
                res_id=res_id,
                res_name=res_name,
                res_url=url,
                city=menu.city,
                chain_key=ck,
            ))
    return [m for m in menus.values() if m.items]


class SwiggyClient:
    def __init__(self, http: Http):
        self.http = http

    def search_dishes(self, query: str, city: str) -> list[RestaurantMenu]:
        coords = SWIGGY_CITIES.get(city)
        if coords is None:
            return []
        lat, lng = coords
        try:
            resp = self.http.get(SEARCH_URL, params={
                "lat": lat, "lng": lng, "str": query,
                "submitAction": "ENTER", "selectedPLTab": "DISH",
            })
        except ZomatoBlocked as exc:
            raise SwiggyBlocked(str(exc)) from exc
        if resp is None:
            return []
        try:
            data = json.loads(resp.text)
        except ValueError:
            log.debug("swiggy: non-JSON response for %r in %s", query, city)
            return []
        if not isinstance(data, dict) or data.get("statusCode", 0) != 0:
            return []
        return parse_dish_search(data, city)

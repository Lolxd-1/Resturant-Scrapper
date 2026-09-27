"""Synthetic Zomato HTML/JSON builders for offline tests (studio/zomato.py)."""
from __future__ import annotations

import json

_DIET_SLUGS = {"veg": ["veg"], "nonveg": ["non-veg"], "egg": ["egg"], "unknown": []}


def state_html(state: dict) -> str:
    """Wrap a state dict exactly like a Zomato page embeds __PRELOADED_STATE__."""
    return "<html><script>window.__PRELOADED_STATE__ = JSON.parse(" + json.dumps(json.dumps(state)) + ");</script></html>"


def item(name: str, img: str | None, diet: str = "veg", desc: str = "") -> dict:
    return {
        "id": name,
        "name": name,
        "desc": desc,
        "dietary_slugs": _DIET_SLUGS.get(diet, []),
        "item_image_url": img,
    }


def menu_state(res_id, name: str, res_url: str, menus, is_perm_closed: bool = False) -> dict:
    """menus: list of (menu_name, [(category_name, [item dicts])])."""
    menu_list = []
    for menu_name, categories in menus:
        cat_list = []
        for category_name, items in categories:
            cat_list.append({"category": {"name": category_name, "items": [{"item": it} for it in items]}})
        menu_list.append({"menu": {"name": menu_name, "categories": cat_list}})

    return {
        "pages": {
            "current": {"resId": res_id},
            "restaurant": {
                str(res_id): {
                    "sections": {
                        "SECTION_BASIC_INFO": {
                            "name": name,
                            "resUrl": res_url,
                            "is_perm_closed": is_perm_closed,
                            "cuisine_string": "",
                        }
                    },
                    "order": {"menuList": {"menus": menu_list}},
                }
            },
        }
    }


def search_state(click_urls) -> dict:
    """click_urls: clickUrl string per entry, or None for an entry with no cardAction."""
    entries = []
    for url in click_urls:
        entry = {"info": {"resId": 1, "name": "x"}}
        if url is not None:
            entry["cardAction"] = {"clickUrl": url}
        entries.append(entry)
    return {"pages": {"search": {"tab_1": {"sections": {"SECTION_SEARCH_RESULT": entries}}}}}


def suggest_json(entries) -> str:
    return json.dumps({"results": entries})

"""Zomato HTTP client and page parsers: polite fetching + menu/search extraction."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from studio.models import PoolItem, RestaurantMenu

log = logging.getLogger("studio.zomato")

CITIES: dict[str, int] = {
    "ncr": 1,
    "kolkata": 2,
    "mumbai": 3,
    "bangalore": 4,
    "pune": 5,
    "hyderabad": 6,
    "chennai": 7,
    "lucknow": 8,
    "kochi": 9,
    "jaipur": 10,
    "ahmedabad": 11,
    "chandigarh": 12,
    "goa": 13,
    "indore": 14,
    "nashik": 16,
    "ludhiana": 20,
    "guwahati": 21,
    "amritsar": 22,
    "kanpur": 23,
    "aurangabad": 25,
    "bhopal": 26,
    "ranchi": 27,
    "visakhapatnam": 28,
    "bhubaneswar": 29,
    "coimbatore": 30,
    "mangalore": 31,
    "vadodara": 32,
    "nagpur": 33,
    "agra": 34,
    "dehradun": 35,
    "mysore": 36,
    "surat": 38,
    "varanasi": 39,
    "patna": 40,
    "udaipur": 11054,
    "raipur": 11310,
}

DEFAULT_SEARCH_CITIES: tuple[str, ...] = (
    "pune", "mumbai", "ncr", "bangalore", "hyderabad", "chennai", "kolkata",
    "ahmedabad", "jaipur", "lucknow", "chandigarh", "indore", "nagpur",
    "nashik", "surat", "vadodara", "kochi", "goa", "bhopal", "aurangabad",
)

CUISINE_SLUGS: tuple[str, ...] = (
    "north-indian", "south-indian", "chinese", "maharashtrian", "street-food",
    "fast-food", "pizza", "burger", "sandwich", "rolls", "momos", "biryani",
    "mughlai", "desserts", "bakery", "beverages", "shake", "juices",
    "ice-cream", "cafe", "coffee", "tea", "italian", "pasta", "continental",
    "mexican", "gujarati", "rajasthani", "bengali", "kerala", "andhra",
    "hyderabadi", "chettinad", "seafood", "kebab", "bbq", "healthy-food",
    "salad", "mithai", "thai", "asian", "tibetan", "lebanese", "arabian",
    "waffle", "mangalorean", "goan", "punjabi", "awadhi", "bihari",
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_TRAILING_SEGMENTS = ("/order", "/info", "/menu", "/reviews", "/photos")
_STATE_RE = re.compile(r'__PRELOADED_STATE__\s*=\s*JSON\.parse\(("(?:[^"\\]|\\.)*")\)', re.S)
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_DIET_MAP = {"veg": "veg", "non-veg": "nonveg", "egg": "egg"}
_LOCALITY_EXCLUDE = frozenset({"delivery", "best", "new"})


class ZomatoBlocked(Exception):
    pass


@dataclass
class SuggestResult:
    restaurants: list[tuple[str, str]]
    chains: list[str]
    dishes: list[tuple[str, str]]


class Http:
    def __init__(self, session=None, min_interval: float = 0.6, max_retries: int = 4,
                 timeout: float = 25.0, sleep=time.sleep, clock=time.monotonic):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        })
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.sleep = sleep
        self.clock = clock
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        interval = self.min_interval / 4 if host in ("b.zmtcdn.com", "media-assets.swiggy.com") else self.min_interval
        with self._lock:
            now = self.clock()
            last = self._last_request.get(host)
            wait = 0.0
            if last is not None:
                wait = max(0.0, interval - (now - last))
            self._last_request[host] = now + wait
        if wait > 0:
            self.sleep(wait)

    def _backoff(self, attempt: int, resp=None) -> None:
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    self.sleep(min(60, int(retry_after)))
                    return
                except (TypeError, ValueError):
                    pass
        self.sleep(min(30, 2 ** attempt) + 0.1 * attempt)

    def get(self, url: str, params: dict | None = None) -> requests.Response | None:
        resp, _ = self.get_ex(url, params)
        return resp

    def get_ex(self, url: str, params: dict | None = None) -> tuple[requests.Response | None, str]:
        """Like get(), but also reports why a None came back: "network" (connection/timeout/
        retries exhausted) or "http" (a definitive non-200 such as 404/410)."""
        host = urlsplit(url).netloc
        is_html_page = "zomato.com" in host and "/webroutes/" not in url
        attempts = self.max_retries + 1

        for attempt in range(1, attempts + 1):
            self._throttle(host)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == attempts:
                    log.warning("zomato request failed: %s (%s)", url, exc)
                    return None, "network"
                self._backoff(attempt)
                continue

            status = resp.status_code
            if status == 200:
                blocked = (
                    is_html_page
                    and "captcha" in resp.text.lower()
                    and "__PRELOADED_STATE__" not in resp.text
                )
                if blocked:
                    if attempt == attempts:
                        raise ZomatoBlocked(url)
                    self._backoff(attempt, resp)
                    continue
                return resp, ""
            if status in (404, 410):
                return None, "http"
            if status == 403:
                if attempt == attempts:
                    raise ZomatoBlocked(url)
                self._backoff(attempt, resp)
                continue
            if status in _RETRYABLE_STATUSES:
                if attempt == attempts:
                    log.warning("zomato request failed: %s (status %s)", url, status)
                    return None, "network"
                self._backoff(attempt, resp)
                continue
            return None, "http"
        return None, "network"


def parse_state(html: str) -> dict | None:
    match = _STATE_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(json.loads(match.group(1)))
    except (json.JSONDecodeError, ValueError):
        return None


def canonical_res_url(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    for suffix in _TRAILING_SEGMENTS:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    path = path.rstrip("/").lower()
    return f"https://www.zomato.com{path}"


def city_of(res_url: str) -> str:
    path = urlsplit(res_url).path.strip("/")
    return path.split("/", 1)[0] if path else ""


def chain_key(name: str) -> str:
    lowered = name.lower().replace("'", "")
    return _NON_ALNUM_RE.sub(" ", lowered).strip()


def _absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"https://www.zomato.com{url}"
    return f"https://www.zomato.com/{url}"


def _extract_res_urls(html: str, city: str) -> list[str]:
    pattern = re.compile(rf"/{re.escape(city)}/([a-z0-9\-]{{4,}})/(?:info|order)")
    seen: set[str] = set()
    urls: list[str] = []
    for slug in pattern.findall(html):
        if slug in seen:
            continue
        seen.add(slug)
        urls.append(canonical_res_url(f"/{city}/{slug}"))
    return urls


def parse_menu(state: dict, fallback_url: str = "") -> RestaurantMenu | None:
    try:
        res_id = str(state["pages"]["current"]["resId"])
        restaurant = state["pages"]["restaurant"][res_id]
        info = restaurant["sections"]["SECTION_BASIC_INFO"]
        name = info["name"]
    except (KeyError, TypeError):
        return None

    url = canonical_res_url(info.get("resUrl") or fallback_url)
    city = city_of(url)
    cuisines = info.get("cuisine_string") or ""

    if info.get("is_perm_closed") is True:
        return RestaurantMenu(res_id=res_id, name=name, url=url, city=city, cuisines=cuisines, items=[])

    ck = chain_key(name)
    items: list[PoolItem] = []
    seen: set[tuple[str, str]] = set()
    try:
        for menu_entry in restaurant["order"]["menuList"]["menus"]:
            menu = menu_entry["menu"]
            menu_name = menu["name"]
            for cat_entry in menu["categories"]:
                category_obj = cat_entry["category"]
                category = category_obj["name"]
                for item_entry in category_obj["items"]:
                    item = item_entry["item"]
                    image = item.get("item_image_url")
                    if not image:
                        for media in item.get("media") or []:
                            candidate = (media or {}).get("image", {}).get("url")
                            if candidate:
                                image = candidate
                                break
                    if not image or not image.startswith(("http://", "https://")):
                        continue
                    image = image.split("?", 1)[0]

                    item_name = (item.get("name") or "").strip()
                    dedup_key = (item_name, image)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    slugs = item.get("dietary_slugs") or []
                    diet = _DIET_MAP.get(slugs[0], "unknown") if slugs else "unknown"

                    description = _WS_RE.sub(" ", item.get("desc") or "").strip()[:300]

                    items.append(PoolItem(
                        item_id=0,
                        name=item_name,
                        category=category,
                        menu_name=menu_name,
                        description=description,
                        diet=diet,
                        img_url=image,
                        res_id=res_id,
                        res_name=name,
                        res_url=url,
                        city=city,
                        chain_key=ck,
                    ))
    except (KeyError, TypeError, AttributeError) as exc:
        log.debug("parse_menu: bad menu shape for %s: %s", url, exc)
        return None

    return RestaurantMenu(res_id=res_id, name=name, url=url, city=city, cuisines=cuisines, items=items)


class ZomatoClient:
    def __init__(self, http: Http):
        self.http = http

    def fetch_menu(self, res_url: str) -> RestaurantMenu | None:
        canonical = canonical_res_url(res_url)
        resp = self.http.get(canonical + "/order")
        if resp is None:
            return None
        state = parse_state(resp.text)
        if state is None:
            return None
        menu = parse_menu(state, fallback_url=canonical)
        if menu is not None:
            log.info("menu %s: %d imaged items", canonical.rsplit("/", 1)[-1], len(menu.items))
        return menu

    def suggest(self, query: str, city: str) -> SuggestResult:
        city_id = CITIES.get(city)
        if city_id is None:
            return SuggestResult(restaurants=[], chains=[], dishes=[])

        resp = self.http.get(
            "https://www.zomato.com/webroutes/search/autoSuggest",
            params={"addressId": 0, "entityId": city_id, "entityType": "city", "q": query, "context": "delivery"},
        )
        if resp is None:
            return SuggestResult(restaurants=[], chains=[], dishes=[])
        try:
            data = resp.json()
        except ValueError:
            return SuggestResult(restaurants=[], chains=[], dishes=[])
        if not isinstance(data, dict):
            return SuggestResult(restaurants=[], chains=[], dishes=[])

        restaurants: list[tuple[str, str]] = []
        chains: list[str] = []
        dishes: list[tuple[str, str]] = []
        for entry in (data.get("results") or []):
            entity_type = entry.get("entityType")
            action = entry.get("actionInfo") or {}
            click_url = action.get("clickUrl")
            if entity_type == "restaurant":
                if not click_url:
                    continue
                info = entry.get("info") or {}
                name = info.get("name") or entry.get("name") or ""
                restaurants.append((name, canonical_res_url(click_url)))
            elif entity_type == "chain_outlets":
                if not click_url:
                    continue
                chains.append(_absolute_url(click_url))
            elif entity_type == "universal_dish":
                dishes.append((entry.get("entityId", ""), entry.get("name", "")))
        return SuggestResult(restaurants=restaurants, chains=chains, dishes=dishes)

    def listing(self, city: str, cuisine: str, locality: str = "") -> list[str]:
        prefix = f"{locality}-restaurants" if locality else "restaurants"
        resp = self.http.get(f"https://www.zomato.com/{city}/{prefix}/{cuisine}")
        if resp is None:
            return []
        return _extract_res_urls(resp.text, city)

    def localities(self, city: str) -> list[str]:
        # Locality links live on the city home page, not on /<city>/restaurants.
        resp = self.http.get(f"https://www.zomato.com/{city}")
        if resp is None:
            return []
        pattern = re.compile(rf"/{re.escape(city)}/([a-z0-9-]+)-restaurants(?:[/\"?]|$)")
        seen: set[str] = set()
        out: list[str] = []
        for slug in pattern.findall(resp.text):
            if slug in seen or slug in _LOCALITY_EXCLUDE:
                continue
            seen.add(slug)
            out.append(slug)
            if len(out) >= 40:
                break
        return out

    def chain_outlets(self, chain_url: str) -> list[str]:
        url = _absolute_url(chain_url)
        resp = self.http.get(url)
        if resp is None:
            return []
        state = parse_state(resp.text)
        if state is not None:
            return self._walk_search_results(state)
        final_url = getattr(resp, "url", "") or url
        city = city_of(canonical_res_url(final_url))
        return _extract_res_urls(resp.text, city)

    def dish_restaurants(self, city: str, dish_id: str) -> list[str]:
        resp = self.http.get(
            f"https://www.zomato.com/{city}/delivery",
            params={"dishv2_id": dish_id, "category": 1},
        )
        if resp is None:
            return []
        state = parse_state(resp.text)
        if state is None:
            return []
        return self._walk_search_results(state)

    @staticmethod
    def _walk_search_results(state: dict) -> list[str]:
        urls: list[str] = []
        search = (state.get("pages") or {}).get("search") or {}
        for value in search.values():
            if not isinstance(value, dict):
                continue
            entries = ((value.get("sections") or {}).get("SECTION_SEARCH_RESULT")) or []
            for entry in entries:
                click_url = (entry.get("cardAction") or {}).get("clickUrl")
                if not click_url:
                    continue
                urls.append(canonical_res_url(click_url))
        return urls

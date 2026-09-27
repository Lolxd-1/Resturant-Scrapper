"""CLI tool: build data/seed_pool.jsonl.gz from cached pages, legacy pairs, and a polite crawl."""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import config
from studio.models import PoolItem, RestaurantMenu
from studio.store import PoolStore
from studio.zomato import (
    CUISINE_SLUGS,
    DEFAULT_SEARCH_CITIES,
    Http,
    ZomatoBlocked,
    ZomatoClient,
    chain_key,
    parse_menu,
    parse_state,
)

log = logging.getLogger("tools.build_seed_pool")

_NONVEG_KEYWORDS = ("chicken", "murgh", "mutton", "fish", "prawn", "keema", "meat")
_EGG_KEYWORDS = ("egg", "anda", "omelette")


def _legacy_diet(name: str) -> str:
    """Keyword-based diet guess for legacy pairs.json entries (studio.text.item_proteins doesn't exist yet)."""
    lower = name.lower()
    if any(k in lower for k in _NONVEG_KEYWORDS):
        return "nonveg"
    if any(k in lower for k in _EGG_KEYWORDS):
        return "egg"
    return "unknown"


def import_cache(store: PoolStore, cache_dir: Path) -> int:
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return 0
    imported = 0
    for path in sorted(cache_dir.glob("*order.html")):
        html = path.read_text(encoding="utf-8", errors="ignore")
        state = parse_state(html)
        if state is None:
            continue
        menu = parse_menu(state)
        if menu is None:
            continue
        store.upsert_menu(menu)
        imported += len(menu.items)
    return imported


def import_pairs(store: PoolStore, pairs_path: Path) -> int:
    pairs_path = Path(pairs_path)
    if not pairs_path.exists():
        return 0
    try:
        entries = json.loads(pairs_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    existing_urls = {it.res_url for it in store.all_items()}
    by_slug: dict[str, list[dict]] = {}
    for entry in entries:
        slug = entry.get("rest")
        if not slug:
            continue
        by_slug.setdefault(slug, []).append(entry)

    imported = 0
    for slug, rows in by_slug.items():
        if any(u.endswith("/" + slug) for u in existing_urls):
            continue
        res_name = slug.replace("-", " ").title()
        url = f"https://www.zomato.com/legacy/{slug}"
        items = []
        for row in rows:
            name = (row.get("name") or "").strip()
            img = row.get("img") or ""
            if not name or not img:
                continue
            items.append(PoolItem(
                item_id=0, name=name, category="", menu_name="", description="",
                diet=_legacy_diet(name), img_url=img, res_id=f"legacy-{slug}",
                res_name=res_name, res_url=url, city="legacy", chain_key=chain_key(res_name),
            ))
        if not items:
            continue
        store.upsert_menu(RestaurantMenu(
            res_id=f"legacy-{slug}", name=res_name, url=url, city="legacy", cuisines="", items=items,
        ))
        imported += len(items)
    return imported


def _safe_fetch(client: ZomatoClient, url: str):
    try:
        return client.fetch_menu(url), False
    except ZomatoBlocked:
        return None, True


def crawl(store: PoolStore, client: ZomatoClient, cities: list[str], cuisines: list[str],
          max_restaurants: int, workers: int, log=print) -> int:
    fetched = 0
    seen_urls: set[str] = set()
    blocked_once = False

    for city in cities:
        for cuisine in cuisines:
            try:
                urls = client.listing(city, cuisine)
            except ZomatoBlocked:
                if blocked_once:
                    return fetched
                log("Blocked by Zomato; waiting 10 minutes")
                time.sleep(600)
                blocked_once = True
                continue

            todo = []
            for url in urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                if store.menu_fetched_at(url) is not None:
                    continue
                todo.append(url)
            if not todo:
                continue

            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(lambda u: _safe_fetch(client, u), todo))

            for menu, blocked in results:
                if blocked:
                    if blocked_once:
                        return fetched
                    log("Blocked by Zomato; waiting 10 minutes")
                    time.sleep(600)
                    blocked_once = True
                    continue
                if menu is not None:
                    store.upsert_menu(menu)
                    fetched += 1
                    if fetched % 25 == 0:
                        log(f"[{city}/{cuisine}] {fetched} restaurants, {store.count_items():,} items")
                if fetched >= max_restaurants:
                    return fetched
    return fetched


def export_seed(store: PoolStore, out_path: Path) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    by_res: dict[str, list[PoolItem]] = {}
    for it in store.all_items():
        if not it.img_url:
            continue
        by_res.setdefault(it.res_url, []).append(it)

    restaurants = 0
    written = 0
    with gzip.open(out_path, "wt", encoding="utf-8", compresslevel=9) as f:
        for res_url in sorted(by_res):
            res_items = sorted(by_res[res_url], key=lambda it: (it.category, it.name))
            restaurants += 1
            for it in res_items:
                line = {
                    "r": it.res_url, "rn": it.res_name, "c": it.city,
                    "n": it.name, "cat": it.category, "m": it.menu_name,
                    "d": (it.description or "")[:200], "dt": it.diet, "i": it.img_url,
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                written += 1

    stats = {"restaurants": restaurants, "items": written, "bytes": out_path.stat().st_size}
    print(f"seed pool: {restaurants} restaurants, {written} items, {stats['bytes']} bytes -> {out_path}")
    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build data/seed_pool.jsonl.gz from cached pages, legacy pairs, and a polite crawl.")
    parser.add_argument("--work-db", default=str(config.home_dir() / "seed_work.sqlite"))
    parser.add_argument("--from-cache")
    parser.add_argument("--from-pairs")
    parser.add_argument("--crawl", action="store_true")
    parser.add_argument("--cities", default="all")
    parser.add_argument("--cuisines", default="all")
    parser.add_argument("--max-restaurants", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--export")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not (args.from_cache or args.from_pairs or args.crawl or args.export):
        parser.print_help()
        return

    store = PoolStore(Path(args.work_db))
    try:
        if args.from_cache:
            n = import_cache(store, Path(args.from_cache))
            print(f"cache: imported {n} items")
        if args.from_pairs:
            n = import_pairs(store, Path(args.from_pairs))
            print(f"pairs: imported {n} items")
        if args.crawl:
            cities = list(DEFAULT_SEARCH_CITIES) if args.cities == "all" else [
                c.strip() for c in args.cities.split(",") if c.strip()
            ]
            cuisines = list(CUISINE_SLUGS) if args.cuisines == "all" else [
                c.strip() for c in args.cuisines.split(",") if c.strip()
            ]
            client = ZomatoClient(Http())
            n = crawl(store, client, cities, cuisines, args.max_restaurants, args.workers)
            print(f"crawl: fetched {n} new restaurants")
        if args.export:
            export_seed(store, Path(args.export))
    finally:
        store.close()


if __name__ == "__main__":
    main()

"""SQLite-backed pool store: menus, upload cache, embeddings cache, bad-image cache."""
from __future__ import annotations

import gzip
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from studio.models import PoolItem, RestaurantMenu
from studio.zomato import canonical_res_url, chain_key

log = logging.getLogger("studio.store")

_BATCH_SIZE = 5000


class PoolStore:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._items_cache: list[PoolItem] | None = None
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS restaurants ("
                "res_url TEXT PRIMARY KEY, res_id TEXT, name TEXT, city TEXT, "
                "cuisines TEXT, chain_key TEXT, fetched_at REAL, source TEXT)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS items ("
                "item_id INTEGER PRIMARY KEY AUTOINCREMENT, res_url TEXT, name TEXT, "
                "category TEXT, menu_name TEXT, description TEXT, diet TEXT, img_url TEXT)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_res_url ON items(res_url)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_img_url ON items(img_url)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS uploads ("
                "sha256 TEXT PRIMARY KEY, url TEXT, host TEXT, created_at REAL)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS embeddings (k TEXT PRIMARY KEY, dim INTEGER, vec BLOB)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS bad_images (img_url TEXT PRIMARY KEY, reason TEXT, at REAL)"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- restaurants / items ----

    def upsert_menu(self, menu: RestaurantMenu) -> int:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO restaurants (res_url, res_id, name, city, cuisines, chain_key, fetched_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'live') "
                "ON CONFLICT(res_url) DO UPDATE SET "
                "res_id=excluded.res_id, name=excluded.name, city=excluded.city, "
                "cuisines=excluded.cuisines, chain_key=excluded.chain_key, "
                "fetched_at=excluded.fetched_at, source='live'",
                (
                    menu.url, menu.res_id, menu.name, menu.city, menu.cuisines,
                    chain_key(menu.name), time.time(),
                ),
            )
            self._conn.execute("DELETE FROM items WHERE res_url = ?", (menu.url,))
            rows = [
                (menu.url, it.name, it.category, it.menu_name, it.description, it.diet, it.img_url)
                for it in menu.items
            ]
            if rows:
                self._conn.executemany(
                    "INSERT INTO items (res_url, name, category, menu_name, description, diet, img_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            self._items_cache = None
            return len(rows)

    def add_items(self, menu: RestaurantMenu) -> list[PoolItem]:
        """Merge a menu's new items into the pool without deleting anything."""
        ck = chain_key(menu.name)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO restaurants (res_url, res_id, name, city, cuisines, chain_key, fetched_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'swiggy') "
                "ON CONFLICT(res_url) DO NOTHING",
                (menu.url, menu.res_id, menu.name, menu.city, menu.cuisines, ck, time.time()),
            )
            known = set(self._conn.execute(
                "SELECT name, img_url FROM items WHERE res_url = ?", (menu.url,)
            ).fetchall())
            inserted: list[PoolItem] = []
            for it in menu.items:
                if (it.name, it.img_url) in known:
                    continue
                known.add((it.name, it.img_url))
                cur = self._conn.execute(
                    "INSERT INTO items (res_url, name, category, menu_name, description, diet, img_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (menu.url, it.name, it.category, it.menu_name, it.description, it.diet, it.img_url),
                )
                inserted.append(PoolItem(
                    item_id=cur.lastrowid, name=it.name, category=it.category, menu_name=it.menu_name,
                    description=it.description, diet=it.diet, img_url=it.img_url,
                    res_id=menu.res_id, res_name=menu.name, res_url=menu.url, city=menu.city,
                    chain_key=ck,
                ))
            if self._items_cache is not None:
                self._items_cache.extend(inserted)
            return inserted

    def menu_fetched_at(self, res_url: str) -> float | None:
        canonical = canonical_res_url(res_url)
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched_at FROM restaurants WHERE res_url = ?", (canonical,)
            ).fetchone()
        return row[0] if row else None

    def all_items(self) -> list[PoolItem]:
        with self._lock:
            if self._items_cache is not None:
                return self._items_cache
            rows = self._conn.execute(
                "SELECT i.item_id, i.name, i.category, i.menu_name, i.description, i.diet, i.img_url, "
                "r.res_id, r.name, r.res_url, r.city, r.chain_key "
                "FROM items i JOIN restaurants r ON r.res_url = i.res_url"
            ).fetchall()
            items = [PoolItem(*row) for row in rows]
            self._items_cache = items
            return items

    def items_for_restaurant(self, res_url: str) -> list[PoolItem]:
        canonical = canonical_res_url(res_url)
        with self._lock:
            rows = self._conn.execute(
                "SELECT i.item_id, i.name, i.category, i.menu_name, i.description, i.diet, i.img_url, "
                "r.res_id, r.name, r.res_url, r.city, r.chain_key "
                "FROM items i JOIN restaurants r ON r.res_url = i.res_url "
                "WHERE i.res_url = ?",
                (canonical,),
            ).fetchall()
        return [PoolItem(*row) for row in rows]

    def count_items(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()
        return row[0]

    def count_restaurants(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM restaurants").fetchone()
        return row[0]

    # ---- seed import ----

    def ensure_seeded(self, seed_path: Path) -> int:
        seed_path = Path(seed_path)
        with self._lock:
            if not seed_path.exists():
                log.info("ensure_seeded: no seed file at %s", seed_path)
                return 0
            stat = seed_path.stat()
            sig = f"{stat.st_size}:{stat.st_mtime_ns}"
            row = self._conn.execute("SELECT v FROM meta WHERE k = 'seed_sig'").fetchone()
            if row is not None and row[0] == sig:
                return 0

            live_res_urls: set[str] = {
                r[0] for r in self._conn.execute(
                    "SELECT res_url FROM restaurants WHERE source = 'live'"
                ).fetchall()
            }

            restaurants: dict[str, dict] = {}
            items_by_res: dict[str, list[tuple]] = {}
            with gzip.open(seed_path, "rt", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        res_url = obj["r"]
                        name = obj["n"]
                        img_url = obj["i"]
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
                    if res_url in live_res_urls:
                        continue
                    restaurants.setdefault(res_url, {
                        "res_name": obj.get("rn", ""),
                        "city": obj.get("c", ""),
                    })
                    items_by_res.setdefault(res_url, []).append((
                        res_url, name, obj.get("cat", ""), obj.get("m", ""),
                        obj.get("d", ""), obj.get("dt", "unknown"), img_url,
                    ))

            inserted = 0
            with self._conn:
                res_rows = [
                    (res_url, "", info["res_name"], info["city"], "", chain_key(info["res_name"]), 0.0, "seed")
                    for res_url, info in restaurants.items()
                ]
                for i in range(0, len(res_rows), _BATCH_SIZE):
                    self._conn.executemany(
                        "INSERT INTO restaurants (res_url, res_id, name, city, cuisines, chain_key, fetched_at, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(res_url) DO NOTHING",
                        res_rows[i:i + _BATCH_SIZE],
                    )

                all_item_rows = [row for rows in items_by_res.values() for row in rows]
                for i in range(0, len(all_item_rows), _BATCH_SIZE):
                    batch = all_item_rows[i:i + _BATCH_SIZE]
                    self._conn.executemany(
                        "INSERT INTO items (res_url, name, category, menu_name, description, diet, img_url) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    inserted += len(batch)

                self._conn.execute(
                    "INSERT INTO meta (k, v) VALUES ('seed_sig', ?) "
                    "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                    (sig,),
                )
            self._items_cache = None
            return inserted

    # ---- uploads ----

    def get_upload(self, sha256: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT url FROM uploads WHERE sha256 = ?", (sha256,)).fetchone()
        return row[0] if row else None

    def put_upload(self, sha256: str, url: str, host: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO uploads (sha256, url, host, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(sha256) DO UPDATE SET url=excluded.url, host=excluded.host, created_at=excluded.created_at",
                (sha256, url, host, time.time()),
            )

    # ---- embeddings ----

    def get_embedding(self, key: str) -> np.ndarray | None:
        with self._lock:
            row = self._conn.execute("SELECT dim, vec FROM embeddings WHERE k = ?", (key,)).fetchone()
        if row is None:
            return None
        dim, blob = row
        return np.frombuffer(blob, dtype=np.float32).reshape(dim).copy()

    def put_embedding(self, key: str, vec: np.ndarray) -> None:
        arr = np.asarray(vec, dtype=np.float32)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO embeddings (k, dim, vec) VALUES (?, ?, ?) "
                "ON CONFLICT(k) DO UPDATE SET dim=excluded.dim, vec=excluded.vec",
                (key, arr.shape[0], arr.tobytes()),
            )

    # ---- bad images ----

    def mark_bad_image(self, img_url: str, reason: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO bad_images (img_url, reason, at) VALUES (?, ?, ?) "
                "ON CONFLICT(img_url) DO UPDATE SET reason=excluded.reason, at=excluded.at",
                (img_url, reason, time.time()),
            )

    def is_bad_image(self, img_url: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT reason FROM bad_images WHERE img_url = ?", (img_url,)).fetchone()
        if row is None:
            return False
        return not row[0].startswith("network")

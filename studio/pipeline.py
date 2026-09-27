"""Job engine: menu -> own/chain source -> pool match -> live search -> vision check -> photos -> upload -> sheets."""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Callable

import numpy as np
from rapidfuzz import fuzz

from studio import imaging, sheets
from studio.brand import GENERIC, BrandGuard, brand_words_from_pool
from studio.config import SEED_POOL_PATH, TEMPLATE_PATH, atomic_write_text, models_dir, pool_db_path
from studio.hosting import UploadError, Uploader
from studio.lexicon import HEAD_CUISINES, HEAD_GROUP, TOKEN_CUISINES
from studio.matcher import PoolIndex, rank, same_dish_menu_match
from studio.menu import derive_sku_prefix, read_menu
from studio.models import (
    Candidate,
    DishQuery,
    DishResult,
    PoolItem,
    RestaurantMenu,
    Settings,
    dish_result_from_dict,
    dish_result_to_dict,
)
from studio.spelling import Speller
from studio.store import PoolStore
from studio.text import normalize, parse_dish, size_base_key
from studio.vision import (
    CLOSE_AGREE_MIN,
    FOOD_MIN_PROB,
    HEAD_HARD_VETO,
    HEAD_SOFT_VETO,
    Vision,
    consensus,
    food_prob,
    head_margin,
    load_vision,
    raw_agreement,
    text_sim,
)
from studio.zomato import CITIES, DEFAULT_SEARCH_CITIES, Http, ZomatoBlocked, ZomatoClient, chain_key

log = logging.getLogger("studio.pipeline")

STAGE_LABELS = {
    "read": "Reading the menu",
    "source": "Looking for the restaurant on Zomato",
    "match": "Matching dishes",
    "search": "Searching Zomato",
    "verify": "Checking photos",
    "photos": "Downloading photos",
    "upload": "Uploading photos",
    "build": "Building sheets",
}

GROUP_CATEGORY = {
    "drink_glass": "Beverages", "hot_cup": "Hot Beverages", "dessert": "Desserts",
    "flatbread": "Breads", "rice": "Rice & Biryani", "curry": "Main Course",
    "bread_snack": "Snacks", "pizza": "Pizza", "noodle_pasta": "Pasta & Noodles",
    "fried_snack": "Snacks", "south": "South Indian", "dumpling": "Momos",
    "egg": "Egg Specials", "grill": "Starters", "plate": "Thalis",
    "bowl": "Soups & Salads", "roll": "Rolls & Wraps",
}

BLOCKED_MESSAGE = "Zomato is limiting requests from this PC; continuing with photos already found."
NO_KEY_MESSAGE = "No ImgBB API key saved. Add one in Settings."
FALLBACK_CITIES = ("pune", "mumbai", "ncr", "bangalore")
MAX_SOURCE_OUTLETS = 25
_READ_AS_LOG_CAP = 200
DEFAULT_CUISINES = ("north-indian", "street-food", "fast-food")
SEARCH_ROUNDS = ((0, 3), (3, 8), (8, 20))
_TIER_RANK = {"exact": 0, "strong": 1, "close": 2}
_PAREN_RE = re.compile(r"\([^)]*\)?")


@dataclass
class JobOptions:
    vendor: str
    city: str = ""
    zomato_url: str = ""
    sku_prefix: str = ""
    upload: bool = True
    strictness: str = "balanced"
    live_search: bool = True
    live_budget_menus: int = 250


class JobCancelled(Exception):
    pass


class Engine:
    def __init__(self, store: PoolStore, vision: Vision, http: Http):
        self.store = store
        self.vision = vision
        self.http = http
        self.client = ZomatoClient(http)
        self.index = PoolIndex(store.all_items())
        self.blocked_until: float = 0.0

    @property
    def blocked(self) -> bool:
        return time.monotonic() < self.blocked_until

    def add_menu(self, menu: RestaurantMenu) -> int:
        n = self.store.upsert_menu(menu)
        self.index.add(self.store.items_for_restaurant(menu.url))
        return n


def build_engine(settings: Settings | None = None, *, allow_download: bool = True,
                 on_status: Callable[[str], None] | None = None) -> Engine:
    status = on_status or (lambda message: None)
    status("Opening the photo library")
    store = PoolStore(pool_db_path())
    store.ensure_seeded(SEED_POOL_PATH)
    status("Loading the visual check")
    vision = load_vision(models_dir(), allow_download=allow_download)
    return Engine(store, vision, Http())


def new_job_id(vendor: str) -> str:
    slug = normalize(vendor).replace(" ", "-")[:40].strip("-") or "job"
    return f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"


def load_job(job_dir: Path) -> dict:
    return json.loads((Path(job_dir) / "job.json").read_text(encoding="utf-8"))


def list_jobs(output_dir: Path) -> list[dict]:
    jobs = []
    for job_file in Path(output_dir).glob("*/job.json"):
        try:
            job = json.loads(job_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        job["id"] = job_file.parent.name
        jobs.append(job)
    return sorted(jobs, key=lambda j: (str(j.get("created", "")), j["id"]), reverse=True)


def infer_category(q: DishQuery) -> str:
    return GROUP_CATEGORY.get(HEAD_GROUP.get(q.head or ""), "Menu")


def _cuisines_for(q: DishQuery) -> tuple[str, ...]:
    """Cuisine slugs to crawl for a dish: its head's cuisines, else the cuisines its
    dish-name words imply (Kaju Kolhapuri has no head word but "kolhapuri" does)."""
    if q.head:
        return HEAD_CUISINES.get(q.head, DEFAULT_CUISINES)
    found: list[str] = []
    for t in (q.variants[0] if q.variants else ()):
        for c in TOKEN_CUISINES.get(t, ()):
            if c not in found:
                found.append(c)
    return tuple(found) if found else DEFAULT_CUISINES


class _Group:
    """Menu rows that share one photo decision (size variants of one dish)."""

    def __init__(self, key: str, q: DishQuery):
        self.key = key
        self.q = q
        self.rows: list[DishResult] = []
        self.cands: list[Candidate] = []
        self.source = ""          # "own" / "chain" when picked from the vendor's own menus
        self.failed = False
        self.resumed = False


_DISK_FULL_MESSAGE = "Your computer's disk is almost full (%.1f GB free). Free up at least 1 GB and press Resume."


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_job_locks: dict[Path, threading.RLock] = {}
_job_locks_guard = threading.Lock()


def job_lock(job_dir: Path) -> threading.RLock:
    """Per-job lock serialising every read-modify-write of results.json/job.json."""
    key = Path(job_dir).resolve()
    with _job_locks_guard:
        return _job_locks.setdefault(key, threading.RLock())


def _write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def _head_keep(margins: np.ndarray, tiers: list[str]) -> list[bool]:
    """Final head-check keep decision (see TUNE1): hard veto always applies; the soft
    veto only removes outliers among several candidates of the same or better tier,
    or a lone "close" tier candidate.
    """
    soft_ok = margins >= HEAD_SOFT_VETO
    keep = []
    for i, tier in enumerate(tiers):
        if margins[i] < HEAD_HARD_VETO:
            keep.append(False)
            continue
        others_ok = any(soft_ok[j] for j in range(len(tiers))
                        if j != i and _TIER_RANK[tiers[j]] <= _TIER_RANK[tier])
        if tier == "close" or others_ok:
            keep.append(bool(soft_ok[i]))
        else:
            keep.append(True)
    return keep


def _combine_scores(c: Candidate, big_brand: bool) -> float:
    """Rank score (about 0..1) for a candidate that already passed every hard gate.

    Inputs, all 0..1: c.score.text (name match; exact >= 0.90, strong 0.75-0.90,
    close 0.55-0.75), c.consensus (how much this photo agrees with the other
    candidates' photos of the same dish), c.vision (CLIP similarity between the
    photo and the dish name). big_brand: photo comes from a big chain that is not
    the vendor (may show that chain's logo box). Candidates are sorted by tier
    first, so this only orders photos WITHIN a tier.
    """
    # TODO(human): choose the weighting policy (the line below is the baseline default).
    score = 0.60 * c.score.text + 0.20 * c.consensus + 0.20 * c.vision
    return score - 0.03 if big_brand else score


def _cand_dict(c: Candidate) -> dict:
    return {
        "item_name": c.item.name, "restaurant": c.item.res_name, "restaurant_url": c.item.res_url,
        "zomato_img": c.item.img_url, "tier": c.score.tier, "confidence": round(c.final, 3), "source": c.source,
    }


def _pick_dict(r: DishResult) -> dict:
    return {
        "item_name": r.item_name, "restaurant": r.restaurant, "restaurant_url": r.restaurant_url,
        "zomato_img": r.zomato_img, "tier": r.tier, "confidence": r.confidence, "source": r.source,
    }


def _summarize(results: list[DishResult], files: dict[str, Path], *,
               vision: bool, duration_s: float, warnings: list[str]) -> dict:
    total = len(results)
    count = Counter(r.status for r in results)
    photos = sum(1 for r in results if r.local_image)
    return {
        "total": total, "ready": count["ready"], "needs_photo": count["needs_photo"],
        "needs_price": count["needs_price"], "errors": count["error"],
        "coverage": round(photos / total, 3) if total else 0.0,
        "vision": vision,
        "duration_s": round(duration_s, 1),
        "files": {k: p.name for k, p in files.items()},
        "warnings": list(warnings),
    }


def _apply_pick(r: DishResult, d: dict) -> None:
    r.item_name, r.restaurant, r.restaurant_url = d["item_name"], d["restaurant"], d["restaurant_url"]
    r.zomato_img, r.tier, r.confidence, r.source = d["zomato_img"], d["tier"], d["confidence"], d["source"]


def _confident(cands: list[Candidate]) -> bool:
    good = [c for c in cands if c.score.tier in ("exact", "strong")]
    return bool(good) and (len({c.item.res_url for c in good}) >= 2 or cands[0].score.tier == "exact")


def _settle(r: DishResult, upload: bool) -> None:
    if r.status == "error":
        return
    if r.local_image and r.price is None:
        r.status, r.reason = "needs_price", "Add a price, then upload"
    elif r.local_image and (r.hosted_url or not upload):
        r.status = "ready"
    else:
        r.status = "needs_photo"


def _chain_sizes(items: list[PoolItem]) -> Counter:
    return Counter(ck for _, ck in {(it.res_url, it.chain_key) for it in items})


def _brand_guard(sizes: Counter, vendor: str) -> BrandGuard:
    vendor_tokens = brand_words_from_pool({chain_key(vendor): 1}, min_outlets=0)
    return BrandGuard(brand_words_from_pool(sizes) - vendor_tokens)


def _query_text(name: str) -> str:
    return size_base_key(_PAREN_RE.sub(" ", name))


def run_job(engine: Engine, menu_path: Path, job_dir: Path, opts: JobOptions, *,
            uploader: Uploader | None, on_event: Callable[[dict], None] | None = None,
            cancel: threading.Event | None = None) -> dict:
    menu_path, job_dir = Path(menu_path), Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    menu_copy = job_dir / f"menu{menu_path.suffix.lower()}"
    if menu_path.resolve() != menu_copy.resolve():
        shutil.copyfile(menu_path, menu_copy)

    job_file = job_dir / "job.json"
    results_file = job_dir / "results.json"
    old_created = None
    if job_file.exists():
        try:
            old_created = load_job(job_dir).get("created")
        except (OSError, ValueError):
            pass

    free_gb = shutil.disk_usage(job_dir).free / 1_000_000_000
    if free_gb < 0.5:
        message = _DISK_FULL_MESSAGE % free_gb
        job = {
            "id": job_dir.name, "vendor": opts.vendor, "options": asdict(opts), "status": "failed",
            "stage": "read", "created": old_created or _now(), "updated": _now(), "summary": None,
            "error": message, "menu_file": menu_copy.name,
        }
        try:
            with job_lock(job_dir):
                _write_json(job_file, job)
        except OSError:
            pass
        if on_event is not None:
            on_event({"type": "error", "message": message})
        return _summarize([], {}, vision=engine.vision.available, duration_s=0.0, warnings=[])

    job = {
        "id": job_dir.name, "vendor": opts.vendor, "options": asdict(opts), "status": "running",
        "stage": "read", "created": old_created or _now(), "updated": _now(), "summary": None,
        "error": None, "menu_file": menu_copy.name,
    }
    old_by_sku: dict[str, DishResult] = {}
    if results_file.exists():
        try:
            old_by_sku = {d["sku"]: dish_result_from_dict(d)
                          for d in json.loads(results_file.read_text(encoding="utf-8"))}
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("could not read previous results in %s; starting fresh", job_dir.name)

    with open(job_dir / "log.txt", "a", encoding="utf-8") as log_file:

        def emit(ev: dict) -> None:
            if ev["type"] in ("log", "stage", "error"):
                text = ev.get("message") or f"[{ev.get('stage')}] {ev.get('label')} {ev.get('progress', 0):.0%}"
                log_file.write(f"{datetime.now():%H:%M:%S} {text}\n")
                log_file.flush()
            if on_event is not None:
                try:
                    on_event(ev)
                except Exception:
                    log.exception("on_event handler failed")

        def save_job(**changes) -> None:
            job.update(changes, updated=_now())
            with job_lock(job_dir):
                _write_json(job_file, job)

        save_job()
        run = _Run(engine, opts, job_dir, uploader, emit, save_job, cancel, old_by_sku)
        if engine.blocked:
            minutes = math.ceil((engine.blocked_until - time.monotonic()) / 60)
            run.say(f"Live search paused for {minutes} more minutes (Zomato limited this PC)")

        try:
            ok = run.read(menu_copy)
            if not ok:
                summary = run.summary({})
                save_job(status="failed", error=run.read_error, summary=summary)
                return summary
            run.source()
            run.match()
            run.search()
            run.verify()
            run.photos()
            run.upload()
            run.settle_all()
            run.write_results()
            run.stage("build")
            files = run.build()
            summary = run.summary(files)
            save_job(status="done", summary=summary)
            emit({"type": "done", "summary": summary})
            return summary
        except JobCancelled:
            run.settle_all()
            run.write_results()
            files = {}
            try:
                files = run.build()
            except Exception:
                log.exception("building outputs after cancel failed")
            summary = run.summary(files)
            emit({"type": "log", "message": "Job cancelled"})
            save_job(status="cancelled", summary=summary)
            return summary
        except Exception as exc:
            log.exception("job %s failed", job_dir.name)
            if isinstance(exc, OSError) and exc.errno == 28:
                message = _DISK_FULL_MESSAGE % (shutil.disk_usage(job_dir).free / 1_000_000_000)
            else:
                message = f"{type(exc).__name__}: {exc}"[:300]
            run.settle_all()
            try:
                run.write_results()
            except OSError:
                pass
            summary = run.summary({})
            emit({"type": "error", "message": message})
            save_job(status="failed", error=message, summary=summary)
            return summary


class _Run:
    """State of one run_job call; methods are the pipeline stages in order."""

    def __init__(self, engine: Engine, opts: JobOptions, job_dir: Path, uploader: Uploader | None,
                 emit, save_job, cancel: threading.Event | None, old_by_sku: dict[str, DishResult]):
        self.engine = engine
        self.opts = opts
        self.job_dir = job_dir
        self.uploader = uploader
        self.emit = emit
        self.save_job = save_job
        self.cancel = cancel
        self.old_by_sku = old_by_sku
        self.started = time.monotonic()
        self.results: list[DishResult] = []
        self.groups: list[_Group] = []
        self.warnings: list[str] = []
        self.read_error = ""
        self.live_urls: set[str] = set()
        self.used_images: dict[str, str] = {}
        self.vendor_key = chain_key(opts.vendor)
        self.brand_guard: BrandGuard | None = None
        self.big_chains: set[str] = set()

    # ---- helpers ----

    def check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise JobCancelled()

    def stage(self, stage_id: str, progress: float = 0.0) -> None:
        if progress == 0.0:
            self.check()
            self.save_job(stage=stage_id)
        self.emit({"type": "stage", "stage": stage_id, "label": STAGE_LABELS[stage_id], "progress": round(progress, 3)})

    def say(self, message: str) -> None:
        log.info(message)
        self.emit({"type": "log", "message": message})

    def write_results(self) -> None:
        data = [dish_result_to_dict(r) for r in self.results]
        with job_lock(self.job_dir):
            _write_json(self.job_dir / "results.json", data)

    def fail_group(self, g: _Group, exc: Exception) -> None:
        log.warning("dish %r failed: %s", g.q.display, exc, exc_info=True)
        g.failed = True
        for r in g.rows:
            r.status, r.reason = "error", f"Could not process this dish ({type(exc).__name__})"

    def emit_rows(self, rows: list[DishResult]) -> None:
        for r in rows:
            _settle(r, self.opts.upload)
            self.emit({"type": "dish", "result": dish_result_to_dict(r)})

    def ranked(self, q: DishQuery) -> list[Candidate]:
        index, store = self.engine.index, self.engine.store
        cands = [c for c in rank(q, index.retrieve(q), index.idf) if not store.is_bad_image(c.item.img_url)]
        for c in cands:
            if c.item.res_url in self.live_urls:
                c.source = "live"
        return cands

    def settle_all(self) -> None:
        for r in self.results:
            _settle(r, self.opts.upload)

    def build(self) -> dict[str, Path]:
        return sheets.build_outputs(self.results, TEMPLATE_PATH, self.job_dir, self.opts.vendor,
                                    vision_on=self.engine.vision.available,
                                    logo_on=self.brand_guard is None or self.brand_guard.available)

    def summary(self, files: dict[str, Path]) -> dict:
        return _summarize(self.results, files, vision=self.engine.vision.available,
                           duration_s=time.monotonic() - self.started, warnings=self.warnings)

    # ---- stages ----

    def read(self, menu_file: Path) -> bool:
        self.stage("read")
        parsed = read_menu(menu_file)
        if parsed.errors:
            self.read_error = parsed.errors[0]
            self.emit({"type": "error", "message": self.read_error})
            return False
        self.warnings += parsed.warnings
        prefix = re.sub(r"[^A-Z0-9]", "", self.opts.sku_prefix.upper())[:6] or derive_sku_prefix(self.opts.vendor)
        by_key: dict[str, _Group] = {}
        speller = Speller(self.engine.index.word_counts())
        self.say(f"Spelling helper ready: {len(speller.vocab)} words")
        read_as: set[str] = set()
        for row in parsed.rows:
            fixed = speller.fix_text(row.name)
            changed = fixed != " ".join(row.name.lower().split())
            if changed and row.name not in read_as and len(read_as) < _READ_AS_LOG_CAP:
                read_as.add(row.name)
                self.say(f"Read '{row.name}' as '{fixed}'")
            q = parse_dish(fixed, speller.fix_text(row.category), row.description, display=row.name)
            r = DishResult(row=row.row, sku=f"{prefix}-{row.row:03d}", name=row.name,
                           category=row.category or infer_category(q), description=row.description,
                           price=row.price)
            self.results.append(r)
            key = q.base_key or f"#{row.row}"
            if key not in by_key:
                by_key[key] = _Group(key, q)
                self.groups.append(by_key[key])
            by_key[key].rows.append(r)
        self.say(f"Menu has {len(self.results)} dishes ({len(self.groups)} distinct)")
        return True

    def source(self) -> None:
        self.stage("source")
        opts, engine = self.opts, self.engine
        if sum(ch.isalpha() for ch in opts.vendor) < 3:
            return
        kind, items, names = "", [], []
        try:
            if opts.zomato_url:
                kind, urls = "own", [opts.zomato_url]
            else:
                kind, urls = "", []
                own_items = [it for it in engine.store.all_items() if it.chain_key == self.vendor_key]
                outlets = {it.res_url: it.res_name for it in own_items}
                # Same-name places with an all-generic name ("Spice Kitchen") are usually unrelated.
                if len(outlets) >= 3 and any(t not in GENERIC for t in self.vendor_key.split()):
                    kind, items, names = "chain", own_items, list(outlets.values())
                else:
                    kind, urls = self._find_vendor()
            if kind and not items:
                for url in urls:
                    menu = engine.client.fetch_menu(url)
                    if menu is None:
                        continue
                    engine.add_menu(menu)
                    items += engine.store.items_for_restaurant(menu.url)
                    names.append(menu.name)
        except ZomatoBlocked:
            self._blocked()
        except Exception as exc:
            log.warning("source: vendor lookup failed for %s: %s", opts.vendor, exc)
        if not names:
            self.say("Vendor not found on Zomato; using photos from other restaurants")
            return
        self.say(f"Vendor found on Zomato as {kind}: {names[0]} ({len(names)} outlets)")
        # Other outlets of the same brand already in the pool carry products the fetched ones lack.
        brands = {chain_key(n) for n in names}
        own_urls = {it.res_url for it in items} if kind == "own" else set()
        outlets: dict[str, dict[int, PoolItem]] = {}
        for it in items + [it for it in engine.store.all_items() if it.chain_key in brands]:
            outlets.setdefault(it.res_url, {})[it.item_id] = it
        top = sorted(outlets.items(), key=lambda kv: (kv[0] in own_urls, len(kv[1])), reverse=True)
        top = top[:MAX_SOURCE_OUTLETS]
        items = [it for _, menu in top for it in menu.values()]
        self.say(f"Using {len(top)} outlets of {names[0]}")
        for g in self.groups:
            self.check()
            hit = same_dish_menu_match(g.q, items, engine.index.idf)
            if hit is not None:
                hit.source = kind
                g.cands, g.source = [hit], kind

    def _find_vendor(self) -> tuple[str, list[str]]:
        opts, client = self.opts, self.engine.client
        cities = [opts.city] if opts.city in CITIES else list(FALLBACK_CITIES)
        for city in cities:
            self.check()
            sr = client.suggest(opts.vendor, city)
            if sr.chains:
                outlets = client.chain_outlets(sr.chains[0])[:4]
                if outlets:
                    return "chain", outlets
            same = list(dict.fromkeys(
                url for name, url in sr.restaurants
                if chain_key(name) == self.vendor_key or fuzz.ratio(chain_key(name), self.vendor_key) >= 92))
            if len(same) >= 2:
                return "chain", same[:4]
            if len(same) == 1 and opts.city == city:
                return "own", same
        return "", []

    def _blocked(self) -> None:
        self.engine.blocked_until = time.monotonic() + 1800
        self.warnings.append(BLOCKED_MESSAGE)
        log.warning(BLOCKED_MESSAGE)
        self.emit({"type": "log", "message": BLOCKED_MESSAGE})

    def match(self) -> None:
        self.stage("match")
        todo = [g for g in self.groups if not g.source]
        for i, g in enumerate(todo):
            self.check()
            try:
                g.cands = self.ranked(g.q)
            except Exception as exc:
                self.fail_group(g, exc)
            self.stage("match", (i + 1) / len(todo))

    def search(self) -> None:
        opts, engine = self.opts, self.engine
        if not opts.live_search or opts.live_budget_menus <= 0 or engine.blocked:
            return
        unresolved = [g for g in self.groups
                      if not g.source and not g.failed and any(g.q.variants) and not _confident(g.cands)]
        if not unresolved:
            return
        self.stage("search")
        cities = list(dict.fromkeys(c for c in [opts.city, *DEFAULT_SEARCH_CITIES] if c in CITIES))
        budget = opts.live_budget_menus
        cache: dict[tuple, list[str]] = {}
        tried: set[str] = set()
        client = engine.client

        def cached(kind: str, *args: str) -> list[str]:
            key = (kind, *args)
            if key not in cache:
                if kind == "suggest":
                    cache[key] = [url for _, url in client.suggest(*args).restaurants]
                else:
                    cache[key] = client.listing(*args)
            return cache[key]

        try:
            for lo, hi in SEARCH_ROUNDS:
                round_cities = cities[lo:hi]
                if not unresolved or budget <= 0 or not round_cities:
                    break
                per_group = []
                for i, g in enumerate(unresolved):
                    self.check()
                    text = _query_text(g.q.raw)
                    cuisines = _cuisines_for(g.q)[:3]
                    urls = []
                    for city in round_cities:
                        try:
                            urls += cached("suggest", text, city)
                        except Exception as exc:
                            log.warning("search: suggest failed for %s: %s", city, exc)
                            continue
                        for cuisine in cuisines:
                            try:
                                urls += cached("listing", city, cuisine)
                            except Exception as exc:
                                log.warning("search: listing failed for %s/%s: %s", city, cuisine, exc)
                                continue
                    per_group.append(urls)
                    self.stage("search", (i + 1) / len(unresolved))
                targets = []
                for batch in zip_longest(*per_group):
                    for url in batch:
                        if url and url not in tried and engine.store.menu_fetched_at(url) is None:
                            tried.add(url)
                            targets.append(url)
                targets = targets[:budget]
                budget -= len(targets)
                try:
                    self._fetch_menus(targets)
                finally:
                    for g in unresolved:
                        g.cands = self.ranked(g.q)
                    unresolved = [g for g in unresolved if not _confident(g.cands)]
        except ZomatoBlocked:
            self._blocked()

    def _fetch_menus(self, urls: list[str]) -> None:
        if not urls:
            return
        self.say(f"Fetching {len(urls)} restaurant menus from Zomato")
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self.engine.client.fetch_menu, url): url for url in urls}
            try:
                for future in as_completed(futures):
                    self.check()
                    try:
                        menu = future.result()
                    except ZomatoBlocked:
                        raise
                    except Exception as exc:
                        log.warning("menu fetch failed for %s: %s", futures[future], exc)
                        continue
                    if menu is not None:
                        self.engine.add_menu(menu)
                        self.live_urls.add(menu.url)
            except BaseException:
                for future in futures:
                    future.cancel()
                raise

    def verify(self) -> None:
        self.stage("verify")
        engine = self.engine
        sizes = _chain_sizes(engine.store.all_items())
        with ThreadPoolExecutor(max_workers=6) as pool:
            for i, g in enumerate(self.groups):
                self.check()
                if not g.failed:
                    try:
                        self._verify_group(g, pool, sizes)
                    except Exception as exc:
                        self.fail_group(g, exc)
                self.stage("verify", (i + 1) / len(self.groups))
        self.write_results()

    def _verify_group(self, g: _Group, pool: ThreadPoolExecutor, sizes: Counter) -> None:
        engine, vision, store = self.engine, self.engine.vision, self.engine.store
        top = g.cands[:8]
        vecs: dict[str, np.ndarray] = {}
        if vision.available:
            for c in top:
                vec = store.get_embedding(c.item.img_url)
                if vec is not None:
                    vecs[c.item.img_url] = vec
        need = [c for c in top if c.item.img_url not in vecs]
        thumbs = list(pool.map(lambda c: imaging.fetch_thumb_ex(c.item.img_url, engine.http), need))
        fetched = []
        for c, (thumb, reason) in zip(need, thumbs):
            if thumb is None:
                if reason != "network":
                    store.mark_bad_image(c.item.img_url, "thumb failed")
            else:
                fetched.append((c.item.img_url, thumb))
        if vision.available and fetched:
            for (url, _), vec in zip(fetched, vision.embed_images([t for _, t in fetched])):
                store.put_embedding(url, vec)
                vecs[url] = vec
        ok_urls = vecs.keys() if vision.available else {url for url, _ in fetched}
        survivors = [c for c in top if c.item.img_url in ok_urls]

        kept: list[Candidate] = []
        if vision.available and survivors:
            mat = np.stack([vecs[c.item.img_url] for c in survivors])
            food = food_prob(vision, mat)
            margins = head_margin(vision, mat, g.q.head)
            keep_head = _head_keep(margins, [c.score.tier for c in survivors])
            cons = consensus(mat, np.array([c.score.text for c in survivors]))
            ts = text_sim(vision, mat, g.q.raw)
            for j, c in enumerate(survivors):
                # The vendor's own/chain menu names this exact dish, so only a clear mismatch vetoes it.
                own_menu = c.source in ("own", "chain")
                c.food_ok = bool(food[j] >= FOOD_MIN_PROB)
                c.type_ok = bool(margins[j] >= HEAD_HARD_VETO if own_menu else keep_head[j])
                c.consensus, c.vision = float(cons[j]), float(ts[j])
                if not (c.food_ok and c.type_ok):
                    continue
                big_brand = (c.source in ("pool", "live") and sizes[c.item.chain_key] >= 5
                             and c.item.chain_key != self.vendor_key)
                c.final = _combine_scores(c, big_brand)
                kept.append(c)
        else:
            for c in survivors:
                c.final = c.score.text
            kept = survivors
        keep_close = (self.opts.strictness != "strict" and vision.available
                      and not any(c.score.tier in ("exact", "strong") for c in kept))
        gated = []
        for c in kept:
            if c.score.tier == "close" and c.source not in ("own", "chain"):
                others = [vecs[o.item.img_url] for o in kept if o.item.res_url != c.item.res_url]
                if not (keep_close and others and raw_agreement(
                        np.stack([vecs[c.item.img_url], *others]))[0] >= CLOSE_AGREE_MIN):
                    continue
            gated.append(c)
        kept = gated
        kept.sort(key=lambda c: (_TIER_RANK[c.score.tier], -c.final))

        if not kept:
            if not any(g.q.variants):
                reason = "Name is not in English letters — add an English name"
            elif g.q.is_combo:
                reason = "Combo dish — ask the owner for a photo of the combo"
            elif g.cands:
                best = g.cands[0].item
                reason = f"Only uncertain matches found (best: {best.name} @ {best.res_name})"
            else:
                reason = "Not found on Zomato"
            for r in g.rows:
                r.reason = reason
            return

        best = kept[0]
        if self.used_images.get(best.item.img_url, g.key) != g.key:
            best = next((c for c in kept[1:] if c.score.tier == best.score.tier
                         and self.used_images.get(c.item.img_url, g.key) == g.key), best)
        self.used_images[best.item.img_url] = g.key
        pick = _cand_dict(best)
        alternates = [_cand_dict(c) for c in kept if c is not best][:4]
        for r in g.rows:
            _apply_pick(r, pick)
            r.alternates = [dict(a) for a in alternates]

    def photos(self) -> None:
        self.stage("photos")
        sizes = _chain_sizes(self.engine.store.all_items())
        self.brand_guard = _brand_guard(sizes, self.opts.vendor)
        self.big_chains = {k for k, n in sizes.items() if n >= 5 and k != self.vendor_key}
        (self.job_dir / "images").mkdir(exist_ok=True)
        for i, g in enumerate(self.groups):
            self.check()
            if not g.failed and g.rows[0].zomato_img:
                try:
                    self._photo_group(g)
                except Exception as exc:
                    self.fail_group(g, exc)
            self.emit_rows([r for r in g.rows
                            if not (self.opts.upload and r.local_image and not r.hosted_url)])
            self.stage("photos", (i + 1) / len(self.groups))
        if not self.brand_guard.available:
            message = f"Logo check unavailable: {self.brand_guard.reason}"
            self.warnings.append(message)
            self.say(message)

    def _photo_group(self, g: _Group) -> None:
        old = [self.old_by_sku.get(r.sku) for r in g.rows]
        if all(o is not None and o.zomato_img == r.zomato_img and o.hosted_url
               and (self.job_dir / o.local_image).is_file() for o, r in zip(old, g.rows)):
            for o, r in zip(old, g.rows):
                r.local_image, r.image_size, r.hosted_url = o.local_image, o.image_size, o.hosted_url
            g.resumed = True
            return
        first = g.rows[0]
        options = [{"item_name": first.item_name, "restaurant": first.restaurant,
                    "restaurant_url": first.restaurant_url, "zomato_img": first.zomato_img,
                    "tier": first.tier, "confidence": first.confidence, "source": first.source}] \
            + first.alternates
        branded = big_chain = ""
        for opt in options:
            is_fallback = opt is not options[0]
            if is_fallback and self.used_images.get(opt["zomato_img"], g.key) != g.key:
                continue
            got, reason = imaging.fetch_full_ex(opt["zomato_img"], self.engine.http)
            if got is None:
                if reason != "network":
                    self.engine.store.mark_bad_image(opt["zomato_img"], "download failed")
                continue
            jpeg, (w, h) = got
            hit = self.brand_guard.brands_in(jpeg)
            if hit:
                branded = sorted(hit)[0]
                self.say(f"Skipped a photo showing {branded} for {first.name}")
                continue
            # Without OCR, a big chain's photo may carry its logo box, as in text-only mode.
            if (not self.brand_guard.available and opt["source"] not in ("own", "chain")
                    and chain_key(opt["restaurant"]) in self.big_chains):
                big_chain = opt["restaurant"]
                continue
            for r in g.rows:
                if is_fallback:
                    _apply_pick(r, opt)
                    r.alternates = [a for a in r.alternates if a["zomato_img"] != opt["zomato_img"]]
                r.local_image = f"images/{r.sku}.jpg"
                r.image_size = f"{w}x{h}"
                (self.job_dir / r.local_image).write_bytes(jpeg)
            if is_fallback:
                self.used_images[opt["zomato_img"]] = g.key
            return
        for r in g.rows:
            if branded:
                r.reason = f"Only photos with {branded} branding found — ask the owner for a photo"
            elif big_chain:
                r.reason = (f"Only photos from {big_chain} found and the logo check is unavailable"
                            " — ask the owner for a photo")
            else:
                r.reason = "Photo download failed"

    def upload(self) -> None:
        if not self.opts.upload:
            return
        self.stage("upload")
        todo = [g for g in self.groups
                if not g.failed and not g.resumed and any(r.local_image and not r.hosted_url for r in g.rows)]
        stop_error = "" if self.uploader is not None else NO_KEY_MESSAGE
        for i, g in enumerate(todo):
            self.check()
            rows = [r for r in g.rows if r.local_image and not r.hosted_url]
            try:
                if stop_error:
                    raise UploadError(stop_error)
                url = self.uploader.upload((self.job_dir / rows[0].local_image).read_bytes(), rows[0].name)
                for r in rows:
                    r.hosted_url = url
            except UploadError as exc:
                message = str(exc)
                if message.startswith("No ImgBB API key"):
                    stop_error = message
                for r in rows:
                    r.status, r.reason = "error", message
            except Exception as exc:
                self.fail_group(g, exc)
            self.write_results()
            self.emit_rows(rows)
            self.stage("upload", (i + 1) / len(todo))


def rebuild_outputs(engine_or_none: Engine | None, job_dir: Path) -> dict:
    """Rebuild the three output files from results.json and store the new summary in job.json.

    Leaves job.json's sheets_stale flag alone: only the caller knows whether a newer swap happened
    while the sheets were being built.
    """
    job_dir = Path(job_dir)
    with job_lock(job_dir):
        job = load_job(job_dir)
        data = json.loads((job_dir / "results.json").read_text(encoding="utf-8"))
    results = [dish_result_from_dict(d) for d in data]
    prev_summary = job.get("summary") or {}
    vision_on = engine_or_none.vision.available if engine_or_none is not None \
        else bool(prev_summary.get("vision", True))
    logo_on = not any(w.startswith("Logo check unavailable") for w in prev_summary.get("warnings", []))
    files = sheets.build_outputs(results, TEMPLATE_PATH, job_dir, job["vendor"], vision_on=vision_on,
                                 logo_on=logo_on)
    summary = _summarize(results, files, vision=vision_on,
                         duration_s=prev_summary.get("duration_s", 0.0),
                         warnings=prev_summary.get("warnings", []))
    with job_lock(job_dir):
        job = load_job(job_dir)
        job["summary"] = summary
        job.pop("rebuild_error", None)
        job["updated"] = _now()
        _write_json(job_dir / "job.json", job)
    return summary


def choose_alternate(engine: Engine, job_dir: Path, sku: str, alt_index: int | None,
                     uploader: Uploader | None, *, rebuild: bool = True) -> DishResult:
    """Swap sku's photo to one of its stored alternates, or mark it as needing an owner photo."""
    job_dir = Path(job_dir)
    with job_lock(job_dir):
        results_file = job_dir / "results.json"
        data = json.loads(results_file.read_text(encoding="utf-8"))
        by_sku = {d["sku"]: i for i, d in enumerate(data)}
        try:
            idx = by_sku[sku]
        except KeyError:
            raise ValueError(f"Unknown SKU {sku}")
        r = dish_result_from_dict(data[idx])
        job = load_job(job_dir)
        upload = bool(job.get("options", {}).get("upload", True))

        if alt_index is None:
            r.alternates = [_pick_dict(r), *r.alternates]
            r.local_image, r.hosted_url, r.zomato_img = "", "", ""
            r.status, r.reason = "needs_photo", "Marked by you: needs owner photo"
        else:
            try:
                alt = r.alternates[alt_index]
            except IndexError:
                raise ValueError("No such alternate")
            got = imaging.fetch_full(alt["zomato_img"], engine.http)
            if got is None:
                raise ValueError("That photo could not be downloaded")
            jpeg, (w, h) = got
            brands = _brand_guard(_chain_sizes(engine.store.all_items()), job["vendor"]).brands_in(jpeg)
            if brands:
                raise ValueError(f"That photo shows {sorted(brands)[0]} branding — pick another")
            old_pick = _pick_dict(r) if r.zomato_img else None
            alternates = list(r.alternates)
            if old_pick is not None:
                alternates[alt_index] = old_pick
            else:
                alternates.pop(alt_index)
            r.alternates = alternates
            r.item_name, r.restaurant, r.restaurant_url = alt["item_name"], alt["restaurant"], alt["restaurant_url"]
            r.zomato_img, r.tier, r.confidence, r.source = alt["zomato_img"], alt["tier"], alt["confidence"], alt["source"]
            r.local_image = f"images/{sku}.jpg"
            r.image_size = f"{w}x{h}"
            (job_dir / r.local_image).write_bytes(jpeg)
            r.hosted_url = ""
            if upload and uploader is not None:
                try:
                    r.hosted_url = uploader.upload(jpeg, r.name)
                except UploadError as exc:
                    raise ValueError(str(exc)) from exc
            r.status, r.reason = "", ""
            _settle(r, upload)

        data[idx] = dish_result_to_dict(r)
        _write_json(results_file, data)

        if rebuild:
            rebuild_outputs(engine, job_dir)
        else:
            job["sheets_stale"] = True
            job["updated"] = _now()
            _write_json(job_dir / "job.json", job)


        return r

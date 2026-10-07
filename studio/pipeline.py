"""Job engine: menu -> own/chain source -> pool match -> live search -> vision check -> photos -> upload -> sheets."""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import string
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from rapidfuzz import fuzz

from studio import imaging, sheets
from studio.brand import GENERIC, BrandGuard, brand_words_from_pool
from studio.config import SEED_POOL_PATH, TEMPLATE_PATH, ai_cache_dir, atomic_write_text, models_dir, pool_db_path
from studio.gemini import Gemini, GeminiError, image_part, text_part
from studio.hosting import UploadError, Uploader
from studio.lexicon import HEAD_CUISINES, HEAD_GROUP, TOKEN_CUISINES
from studio.matcher import PoolIndex, rank, same_dish_menu_match
from studio.menu import derive_sku_prefix, read_menu
from studio.models import (
    Candidate,
    DishQuery,
    DishResult,
    MenuRow,
    PoolItem,
    RestaurantMenu,
    Settings,
    dish_result_from_dict,
    dish_result_to_dict,
)
from studio.prompts import ENRICH_SCHEMA, ENRICH_SYSTEM, JUDGE_SCHEMA, JUDGE_SYSTEM
from studio.reader import _clean_item
from studio.spelling import Speller
from studio.store import PoolStore
from studio.swiggy import SWIGGY_CITIES, SwiggyBlocked, SwiggyClient
from studio.text import lookalike_names, normalize, parse_dish, size_base_key
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
    "judge": "AI photo check",
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
SWIGGY_BLOCKED_MESSAGE = "Swiggy is limiting requests from this PC; continuing without it."
SWIGGY_MAX_REQUESTS = 600
AI_ENRICH_BATCH = 120       # dishes per Gemini enrich call
AI_JUDGE_BATCH = 25         # dishes per Gemini photo-check call
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
    def __init__(self, store: PoolStore, vision: Vision, http: Http, swiggy: SwiggyClient | None = None,
                 gemini: Gemini | None = None):
        self.store = store
        self.vision = vision
        self.http = http
        self.client = ZomatoClient(http)
        self.swiggy = swiggy          # None = Swiggy search disabled
        self.gemini = gemini          # None = AI helpers off; the server sets it per job
        self.index = PoolIndex(store.all_items())
        self.blocked_until: float = 0.0

    @property
    def blocked(self) -> bool:
        return time.monotonic() < self.blocked_until

    def add_menu(self, menu: RestaurantMenu) -> int:
        n = self.store.upsert_menu(menu)
        self.index.add(self.store.items_for_restaurant(menu.url))
        return n

    def add_items(self, menu: RestaurantMenu) -> int:
        items = self.store.add_items(menu)
        self.index.add(items)
        return len(items)


def build_engine(settings: Settings | None = None, *, allow_download: bool = True,
                 on_status: Callable[[str], None] | None = None) -> Engine:
    status = on_status or (lambda message: None)
    status("Opening the photo library")
    store = PoolStore(pool_db_path())
    store.ensure_seeded(SEED_POOL_PATH)
    status("Loading the visual check")
    vision = load_vision(models_dir(), allow_download=allow_download)
    http = Http()
    gemini = None
    if settings is not None and settings.gemini_key:
        gemini = Gemini(settings.gemini_key, cache_dir=ai_cache_dir())
    return Engine(store, vision, http, SwiggyClient(http), gemini)


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

    def __init__(self, key: str, q: DishQuery, rungs: Sequence[DishQuery] = ()):
        self.key = key
        self.q = q
        self.rungs = [q, *rungs]  # rung 0 = the dish's own name, then its look-alike names
        self.option_rung: int | None = None  # rung that is this dish without its bracketed option
        self.rows: list[DishResult] = []
        self.cands: list[Candidate] = []
        self.kept: list[Candidate] = []  # photos the verify stage kept, best first
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
        "rung": c.rung,
    }


def _pick_dict(r: DishResult) -> dict:
    return {
        "item_name": r.item_name, "restaurant": r.restaurant, "restaurant_url": r.restaurant_url,
        "zomato_img": r.zomato_img, "tier": r.tier, "confidence": r.confidence, "source": r.source,
        "rung": int(r.lookalike),
    }


def _summarize(results: list[DishResult], files: dict[str, Path], *,
               vision: bool, duration_s: float, warnings: list[str]) -> dict:
    total = len(results)
    count = Counter(r.status for r in results)
    photos = sum(1 for r in results if r.local_image)
    return {
        "total": total, "ready": count["ready"], "review": count["review"], "needs_photo": count["needs_photo"],
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
    cands = [c for c in cands if c.rung == 0]
    good = [c for c in cands if c.score.tier in ("exact", "strong")]
    return bool(good) and (len({c.item.res_url for c in good}) >= 2 or cands[0].score.tier == "exact")


def _settle(r: DishResult, upload: bool) -> None:
    if r.status == "error":
        return
    if r.local_image and r.price is None:
        r.status, r.reason = "needs_price", "Add a price, then upload"
    elif r.local_image and r.lookalike and not r.approved:
        r.status, r.reason = "review", r.reason or "Look-alike photo — approve it or search again"
    elif r.local_image and (r.hosted_url or not upload):
        r.status = "ready"
    else:
        r.status = "needs_photo"


def _awaits_upload(r: DishResult) -> bool:
    """Has a photo still to upload; an unapproved look-alike is never uploaded."""
    return bool(r.local_image) and not r.hosted_url and not (r.lookalike and not r.approved)


def _rank_pool(engine: Engine, q: DishQuery) -> list[Candidate]:
    index, store = engine.index, engine.store
    cands = [c for c in rank(q, index.retrieve(q), index.idf) if not store.is_bad_image(c.item.img_url)]
    for c in cands:
        if c.item.res_url.startswith("https://www.swiggy.com/"):
            c.source = "swiggy"
    return cands


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
            run.judge()
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
        gemini = engine.gemini
        self.gemini = gemini if gemini is not None and gemini.available else None  # None after a Gemini error

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

    def ai_failed(self, message: str) -> None:
        """Stop calling Gemini for the rest of the job (free quota is tiny) and warn once."""
        self.gemini = None
        self.warnings.append(message)
        self.say(message)

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
        cands = _rank_pool(self.engine, q)
        for c in cands:
            if c.item.res_url in self.live_urls:
                c.source = "live"
        return cands

    def ranked_group(self, g: _Group) -> list[Candidate]:
        """Candidates of every rung, rung 0 first; a photo found by an earlier rung is not repeated."""
        seen: set[str] = set()
        cands: list[Candidate] = []
        for i, rq in enumerate(g.rungs):
            for c in self.ranked(rq):
                if c.item.img_url not in seen:
                    seen.add(c.item.img_url)
                    c.rung = i
                    cands.append(c)
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
        self._enrich(parsed.rows)
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
            category = speller.fix_text(row.category)
            q = parse_dish(fixed, category, row.description, display=row.name)
            if row.diet:
                q = replace(q, diet=row.diet)
            rungs: list[DishQuery] = []
            # Names derived from the speller's lower-case text are shown in Title Case.
            for name in row.photo_names or [string.capwords(n) for n in lookalike_names(fixed)]:
                rq = parse_dish(speller.fix_text(name), category, "", display=name)
                if row.diet:
                    rq = replace(rq, diet=row.diet)
                if any(rq.variants) and rq.base_key not in {q.base_key, *(x.base_key for x in rungs)}:
                    rungs.append(rq)
            r = DishResult(row=row.row, sku=f"{prefix}-{row.row:03d}", name=row.name,
                           category=row.category or infer_category(q), description=row.description,
                           price=row.price, diet=row.diet or (q.diet if q.diet != "unknown" else ""),
                           photo_names=[rq.display for rq in rungs])
            self.results.append(r)
            key = q.base_key or f"#{row.row}"
            if key not in by_key:
                by_key[key] = _Group(key, q, rungs)
                if "(" in row.name:
                    plain = _query_text(row.name)
                    by_key[key].option_rung = next(
                        (i for i, rq in enumerate(by_key[key].rungs) if rq.base_key == plain), None)
                self.groups.append(by_key[key])
            by_key[key].rows.append(r)
        self.say(f"Menu has {len(self.results)} dishes ({len(self.groups)} distinct)")
        return True

    def _enrich(self, rows: list[MenuRow]) -> None:
        """Fill rows' empty diet / photo names / description with one Gemini call per AI_ENRICH_BATCH rows."""
        todo = [row for row in rows if not row.photo_names or not row.diet]
        if self.gemini is None or not todo:
            return
        filled = 0
        try:
            for start in range(0, len(todo), AI_ENRICH_BATCH):
                batch = {row.row: row for row in todo[start:start + AI_ENRICH_BATCH]}
                dishes = [{"id": row.row, "name": row.name, "category": row.category, "description": row.description}
                          for row in batch.values()]
                answer = self.gemini.generate_json(ENRICH_SYSTEM, [text_part(json.dumps(dishes, ensure_ascii=False))],
                                                   ENRICH_SCHEMA, max_output_tokens=32768)
                for raw in answer.get("items") or []:
                    row = batch.pop(raw.get("id"), None) if isinstance(raw, dict) else None
                    if row is None:
                        continue
                    got = _clean_item({**raw, "name": row.name})
                    before = (row.diet, row.photo_names, row.description)
                    row.diet = row.diet or got["diet"]
                    row.photo_names = row.photo_names or got["photo_names"]
                    row.description = row.description or got["description"]
                    filled += (row.diet, row.photo_names, row.description) != before
        except GeminiError as exc:
            self.ai_failed(f"AI helper unavailable: {exc}")
        if filled:
            self.say(f"AI filled details for {filled} dishes")

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
                g.cands = self.ranked_group(g)
            except Exception as exc:
                self.fail_group(g, exc)
            self.stage("match", (i + 1) / len(todo))

    def search(self) -> None:
        opts, engine = self.opts, self.engine
        zomato_ok = opts.live_budget_menus > 0 and not engine.blocked
        if not opts.live_search or not (zomato_ok or engine.swiggy is not None):
            return
        unresolved = [g for g in self.groups
                      if not g.source and not g.failed and any(g.q.variants) and not _confident(g.cands)]
        if not unresolved:
            return
        self.stage("search")
        if engine.swiggy is not None:
            self._swiggy_search(unresolved)
            unresolved = [g for g in unresolved if not _confident(g.cands)]
        if not unresolved or not zomato_ok:
            return
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
                        g.cands = self.ranked_group(g)
                    unresolved = [g for g in unresolved if not _confident(g.cands)]
        except ZomatoBlocked:
            self._blocked()

    def _swiggy_search(self, groups: list[_Group]) -> None:
        """Swiggy dish search one rung at a time: every open dish's own name before any look-alike name."""
        opts, engine = self.opts, self.engine
        cities = [c for c in dict.fromkeys([opts.city, "pune", "mumbai", "bangalore"]) if c in SWIGGY_CITIES][:2]
        planned = sum(len(cities) + max(0, min(len(g.rungs), 3) - 1) for g in groups) or 1
        done: set[tuple[str, str]] = set()
        open_groups = groups
        try:
            for i in range(3):
                searching = [g for g in open_groups if i < len(g.rungs)]
                capped = False
                for city in cities[:2 if i == 0 else 1]:
                    for g in searching:
                        self.check()
                        key = (_query_text(g.rungs[i].raw), city)
                        if key in done:
                            continue
                        if len(done) >= SWIGGY_MAX_REQUESTS:
                            capped = True
                            break
                        done.add(key)
                        for menu in engine.swiggy.search_dishes(*key):
                            engine.add_items(menu)
                        self.stage("search", min(1.0, len(done) / planned))
                    if capped:
                        break
                still_open = []
                for g in searching:
                    g.cands = self.ranked_group(g)
                    if not (_confident(g.cands) or any(c.rung <= i and c.score.tier in ("exact", "strong")
                                                       for c in g.cands)):
                        still_open.append(g)
                if capped:
                    return
                open_groups = still_open
        except SwiggyBlocked:
            self.warnings.append(SWIGGY_BLOCKED_MESSAGE)
            self.say(SWIGGY_BLOCKED_MESSAGE)

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

    def _screen(self, top: list[Candidate], pool: ThreadPoolExecutor) -> tuple[dict[str, np.ndarray], list[Candidate]]:
        """Fetch thumbnails/embeddings for top; returns (embeddings by img_url, candidates with a usable photo)."""
        engine, vision, store = self.engine, self.engine.vision, self.engine.store
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
        return vecs, [c for c in top if c.item.img_url in ok_urls]

    def _verify_group(self, g: _Group, pool: ThreadPoolExecutor, sizes: Counter) -> None:
        vision = self.engine.vision
        zero = [c for c in g.cands if c.rung == 0]
        vecs, survivors = self._screen(zero[:8], pool)

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
        rung = 0
        if not kept:
            rung, kept = self._lookalike_kept(g, pool, sizes)
        kept.sort(key=lambda c: (_TIER_RANK[c.score.tier], -c.final))
        g.kept = kept

        if not kept:
            if not any(g.q.variants):
                reason = "Name is not in English letters — add an English name"
            elif g.q.is_combo:
                reason = "Combo dish — ask the owner for a photo of the combo"
            elif zero:
                best = zero[0].item
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
        search_name = g.rungs[rung].display if rung else ""
        for r in g.rows:
            _apply_pick(r, pick)
            r.alternates = [dict(a) for a in alternates]
            r.lookalike, r.search_name = bool(rung), search_name
            if rung:
                r.reason = f"Look-alike photo ({search_name}) — approve it or search again"

    def _lookalike_kept(self, g: _Group, pool: ThreadPoolExecutor, sizes: Counter) -> tuple[int, list[Candidate]]:
        """Screened exact/strong candidates of the first look-alike rung that has any, with that rung."""
        rung = next((c.rung for c in g.cands if c.rung >= 1 and c.score.tier in ("exact", "strong")), 0)
        if not rung:
            return 0, []
        top = [c for c in g.cands if c.rung == rung and c.score.tier in ("exact", "strong")][:4]
        vecs, survivors = self._screen(top, pool)
        vision, rq = self.engine.vision, g.rungs[rung]
        if not (vision.available and survivors):
            for c in survivors:
                c.final = c.score.text
            return rung, survivors
        mat = np.stack([vecs[c.item.img_url] for c in survivors])
        food = food_prob(vision, mat)
        margins = head_margin(vision, mat, rq.head)
        cons = consensus(mat, np.array([c.score.text for c in survivors]))
        ts = text_sim(vision, mat, rq.raw)
        kept = []
        for j, c in enumerate(survivors):
            c.food_ok = bool(food[j] >= FOOD_MIN_PROB)
            c.type_ok = bool(margins[j] >= HEAD_SOFT_VETO)
            c.consensus, c.vision = float(cons[j]), float(ts[j])
            if c.food_ok and c.type_ok:
                big_brand = (c.source in ("pool", "live") and sizes[c.item.chain_key] >= 5
                             and c.item.chain_key != self.vendor_key)
                c.final = _combine_scores(c, big_brand)
                kept.append(c)
        return rung, kept

    def judge(self) -> None:
        if self.gemini is None:
            return
        store = self.engine.store
        todo: list[tuple[_Group, list[Candidate]]] = []
        for g in self.groups:
            if g.failed or g.rows[0].source in ("own", "chain"):
                continue
            # Nothing kept: let the AI rescue rung-0 matches the CLIP check may have vetoed wrongly.
            cands = g.kept[:4] or [c for c in g.cands if c.rung == 0 and c.score.tier in ("exact", "strong")
                                   and not store.is_bad_image(c.item.img_url)][:4]
            if cands:
                todo.append((g, cands))
        if not todo:
            return
        self.stage("judge")
        judged = 0
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for start in range(0, len(todo), AI_JUDGE_BATCH):
                    self.check()
                    judged += self._judge_batch(todo[start:start + AI_JUDGE_BATCH], pool)
                    self.stage("judge", min(1.0, (start + AI_JUDGE_BATCH) / len(todo)))
        except GeminiError as exc:
            self.ai_failed(f"AI photo check unavailable: {exc}")
        if judged:
            self.say(f"AI checked photos for {judged} dishes")

    def _judge_batch(self, batch: list[tuple[_Group, list[Candidate]]], pool: ThreadPoolExecutor) -> int:
        """One Gemini call for the batch's photos; applies the verdicts and returns how many dishes got one."""
        http = self.engine.http
        urls = list(dict.fromkeys(c.item.img_url for _, cands in batch for c in cands))
        thumbs = dict(zip(urls, pool.map(lambda url: imaging.fetch_thumb_ex(url, http)[0], urls)))
        parts: list[dict] = []
        sent: list[tuple[_Group, dict[str, Candidate]]] = []
        for g, cands in batch:
            by_label = dict(zip("ABCD", (c for c in cands if thumbs[c.item.img_url] is not None)))
            if not by_label:
                continue
            i, first = len(sent) + 1, g.rows[0]
            parts.append(text_part(f"Dish {i}: {g.q.display} | category: {first.category or '-'}"
                                   f" | diet: {first.diet or 'unknown'}"))
            for label, c in by_label.items():
                parts += [text_part(f"Dish {i} photo {label}:"), image_part(thumbs[c.item.img_url])]
            sent.append((g, by_label))
        if not sent:
            return 0
        intro = text_part(f"{len(sent)} dishes and their candidate photos. Judge every photo.")
        answer = self.gemini.generate_json(JUDGE_SYSTEM, [intro, *parts], JUDGE_SCHEMA, max_output_tokens=16384)
        photos_by_id = {d.get("id"): d.get("photos") or [] for d in answer.get("dishes") or [] if isinstance(d, dict)}
        judged = 0
        for i, (g, by_label) in enumerate(sent, 1):
            verdicts = {p["label"]: p for p in photos_by_id.get(i, [])
                        if isinstance(p, dict) and p.get("label") in by_label}
            if verdicts:
                self._apply_verdicts(g, [(c, verdicts[label]) for label, c in by_label.items() if label in verdicts])
                judged += 1
        return judged

    def _apply_verdicts(self, g: _Group, judged: list[tuple[Candidate, dict]]) -> None:
        """Re-pick g's photo from the AI verdicts. Look-alikes always need approval: only a "same" photo
        of the dish itself (rung 0, or the dish without its bracketed option) becomes ready."""
        def order(cv: tuple[Candidate, dict]) -> tuple[bool, float]:
            quality = cv[1].get("quality")
            return cv[1]["verdict"] != "same", -(quality if isinstance(quality, (int, float)) else 0)

        ok = sorted(((c, v) for c, v in judged if v.get("clean") is True and v.get("verdict") in ("same", "similar")),
                    key=order)
        if not ok:
            what = "matching photo" if judged[0][0].rung == 0 else "matching look-alike photo"
            empty = {"item_name": "", "restaurant": "", "restaurant_url": "", "zomato_img": "", "tier": "",
                     "confidence": 0.0, "source": ""}
            for r in g.rows:
                _apply_pick(r, empty)
                r.alternates, r.lookalike = [], False
                r.reason = f"AI found no {what} ({len(judged)} checked)"
            return
        best, verdict = ok[0][0], ok[0][1]["verdict"]
        if self.used_images.get(best.item.img_url, g.key) != g.key:
            best = next((c for c, v in ok[1:] if v["verdict"] == verdict
                         and self.used_images.get(c.item.img_url, g.key) == g.key), best)
        self.used_images[best.item.img_url] = g.key
        pick = _cand_dict(best)
        alternates = [_cand_dict(c) for c, _ in ok if c is not best][:4]
        for r in g.rows:
            _apply_pick(r, pick)
            r.alternates = [dict(a) for a in alternates]
            if verdict == "same" and best.rung in (0, g.option_rung):
                r.lookalike, r.search_name, r.reason = False, "", ""
            elif best.rung == 0:
                r.lookalike, r.search_name = True, g.q.display
                r.reason = "Similar photo — approve it or search again"
            else:
                r.lookalike = True

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
            self.emit_rows([r for r in g.rows if not (self.opts.upload and _awaits_upload(r))])
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
                r.approved, r.lookalike, r.search_name, r.reason = o.approved, o.lookalike, o.search_name, o.reason
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
                if not g.failed and not g.resumed and any(_awaits_upload(r) for r in g.rows)]
        stop_error = "" if self.uploader is not None else NO_KEY_MESSAGE
        for i, g in enumerate(todo):
            self.check()
            rows = [r for r in g.rows if _awaits_upload(r)]
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
            r.lookalike = r.approved = False
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
            r.approved, r.lookalike = True, bool(alt.get("rung"))
            if not r.lookalike:
                r.search_name = ""
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


def _sku_index(data: list[dict], sku: str) -> int:
    for i, d in enumerate(data):
        if d["sku"] == sku:
            return i
    raise ValueError(f"Unknown SKU {sku}")


def search_photos(engine: Engine, job_dir: Path, sku: str, query: str) -> DishResult:
    """Find photos of `query` (pool, then Swiggy) and store them as sku's alternates; its photo is kept."""
    job_dir = Path(job_dir)
    results_file = job_dir / "results.json"
    with job_lock(job_dir):
        data = json.loads(results_file.read_text(encoding="utf-8"))
        r = dish_result_from_dict(data[_sku_index(data, sku)])
        city = load_job(job_dir).get("options", {}).get("city", "")
    q = parse_dish(query, r.category, "", display=query)
    if r.diet:
        q = replace(q, diet=r.diet)
    if not any(q.variants):
        raise ValueError("Type a dish name to search for")
    cands = _rank_pool(engine, q)
    if engine.swiggy is not None and sum(c.score.tier in ("exact", "strong") for c in cands) < 4:
        try:
            for slug in dict.fromkeys([city if city in SWIGGY_CITIES else "pune", "mumbai"]):
                for menu in engine.swiggy.search_dishes(_query_text(query), slug):
                    engine.add_items(menu)
        except SwiggyBlocked:
            pass
        cands = _rank_pool(engine, q)
    top = cands[:8]
    for c in top:
        c.final = c.score.text

    with job_lock(job_dir):
        data = json.loads(results_file.read_text(encoding="utf-8"))
        idx = _sku_index(data, sku)
        r = dish_result_from_dict(data[idx])
        r.alternates = [dict(_cand_dict(c), rung=max(c.rung, 1)) for c in top]
        r.search_name = query
        data[idx] = dish_result_to_dict(r)
        _write_json(results_file, data)
    return r


def approve_dishes(engine: Engine, job_dir: Path, skus: list[str], uploader: Uploader | None) -> list[DishResult]:
    """Approve the look-alike photos of skus that are in review: upload them (if the job uploads) and settle."""
    job_dir = Path(job_dir)
    results_file = job_dir / "results.json"
    with job_lock(job_dir):
        data = json.loads(results_file.read_text(encoding="utf-8"))
        idxs = [_sku_index(data, sku) for sku in skus]
        job = load_job(job_dir)
        upload = bool(job.get("options", {}).get("upload", True))
        results = []
        try:
            for idx in idxs:
                r = dish_result_from_dict(data[idx])
                results.append(r)
                if r.status != "review":
                    continue
                if not (job_dir / r.local_image).is_file():
                    raise ValueError(f"Photo file missing for {r.sku}; search again")
                if upload:
                    if uploader is None:
                        raise ValueError(NO_KEY_MESSAGE)
                    try:
                        r.hosted_url = uploader.upload((job_dir / r.local_image).read_bytes(), r.name)
                    except UploadError as exc:
                        raise ValueError(str(exc)) from exc
                r.approved = True
                r.status, r.reason = "", ""
                _settle(r, upload)
                data[idx] = dish_result_to_dict(r)
        finally:
            # Keep the approvals (and uploads) done before an error.
            _write_json(results_file, data)
            job["sheets_stale"] = True
            job["updated"] = _now()
            _write_json(job_dir / "job.json", job)
    return results

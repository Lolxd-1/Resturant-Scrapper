"""FastAPI server exposing the pipeline to the browser UI (JSON + SSE), one background worker thread."""
from __future__ import annotations

import asyncio
import importlib
import io
import json
import logging
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import studio
from studio.config import CONFIG_PATH, OUTPUT_DIR, atomic_write_text, load_settings, save_settings
from studio.hosting import Uploader, test_key
from studio.menu import read_menu
from studio.models import ImgbbKey, Settings, dish_result_to_dict
from studio.pipeline import (
    Engine,
    JobOptions,
    approve_dishes,
    build_engine,
    choose_alternate,
    job_lock,
    list_jobs,
    new_job_id,
    rebuild_outputs,
    run_job,
    search_photos,
)
from studio.zomato import CITIES

log = logging.getLogger("studio.server")

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
JOB_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]{1,40}$")
SKU_RE = re.compile(r"^[A-Z0-9]{1,6}-\d{3,4}$")
KEY_RE = re.compile(r"^[A-Za-z0-9]{20,64}$")
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
FILE_KINDS = ("ready", "pending", "report")
BAD_ZOMATO_URL_MESSAGE = "Open the link in your browser and paste the full zomato.com address"
VC_RUNTIME_STATUS = "Visual check needs the Microsoft VC++ runtime"
VC_RUNTIME_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _validate_zomato_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if "zoma.to" in raw.lower():
        raise HTTPException(400, BAD_ZOMATO_URL_MESSAGE)
    url = raw if re.match(r"^https?://", raw, re.IGNORECASE) else f"https://{raw}"
    host = urlsplit(url).netloc.lower()
    if host not in ("zomato.com", "www.zomato.com"):
        raise HTTPException(400, BAD_ZOMATO_URL_MESSAGE)
    return url
ENGINE_STATUS_MAP = {
    "Opening the photo library": "Loading photo pool…",
    "Loading the visual check": "Preparing visual check (first run downloads ~600 MB)…",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


class EventBus:
    """Per-job buffered events (cap 5000) with a condition variable for SSE polling."""

    CAP = 5000

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._events: dict[str, list[tuple[int, dict]]] = {}
        self._next: dict[str, int] = {}

    def publish(self, job_id: str, ev: dict) -> None:
        with self._cond:
            idx = self._next.get(job_id, 0)
            self._next[job_id] = idx + 1
            lst = self._events.setdefault(job_id, [])
            lst.append((idx, ev))
            if len(lst) > self.CAP:
                del lst[: len(lst) - self.CAP]
            self._cond.notify_all()

    def after(self, job_id: str, after: int) -> list[tuple[int, dict]]:
        with self._cond:
            return [pair for pair in self._events.get(job_id, []) if pair[0] > after]

    def wait_for_more(self, job_id: str, after: int, timeout: float) -> bool:
        """Blocks (call via asyncio.to_thread) until an event with index > after arrives, or timeout."""
        with self._cond:
            deadline = time.monotonic() + timeout
            while True:
                if any(i > after for i, _ in self._events.get(job_id, [])):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)


def onnxruntime_error() -> str:
    """Why onnxruntime cannot load, or "" when it can. Its DLLs need the Microsoft VC++ runtime."""
    try:
        importlib.import_module("onnxruntime")
    except Exception as exc:
        return str(exc) or type(exc).__name__
    return ""


class Worker:
    """One daemon thread running the pipeline queue, plus lazy engine loading and rebuild coalescing."""

    def __init__(self, output_dir: Path, config_path: Path):
        self.output_dir = output_dir
        self.config_path = config_path
        self.engine_factory: Callable[[], Engine] | None = None
        self.engine: Engine | None = None
        self.status = "Loading photo pool…"
        self.current: str | None = None
        self.bus = EventBus()
        self._engine_done = threading.Event()
        self._queue: "queue.Queue" = queue.Queue()
        self._active: set[str] = set()
        self._cancels: dict[str, threading.Event] = {}
        self._rebuild_events: dict[str, threading.Event] = {}
        self._rebuild_lock = threading.Lock()
        self._rebuild_queued: set[str] = set()
        # gen counts swaps per job; built is the newest generation a finished rebuild captured.
        self._gen: dict[str, int] = {}
        self._built: dict[str, int] = {}
        self._build_lock = threading.Lock()

    def set_status(self, status: str) -> None:
        self.status = status

    def start(self) -> None:
        threading.Thread(target=self._load_engine, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()

    def is_active(self, job_id: str) -> bool:
        return job_id in self._active

    def enqueue_run(self, job_id: str, menu_path: Path, opts: JobOptions) -> None:
        self._active.add(job_id)
        self._queue.put(("run", job_id, menu_path, opts))

    def cancel(self, job_id: str) -> None:
        ev = self._cancels.get(job_id)
        if ev is not None:
            ev.set()

    def request_rebuild(self, job_id: str) -> None:
        """Record one more swap for job_id and queue a rebuild (coalesced)."""
        with self._rebuild_lock:
            self._gen[job_id] = self._gen.get(job_id, 0) + 1
            self._rebuild_events.setdefault(job_id, threading.Event()).clear()
            if job_id not in self._rebuild_queued:
                self._rebuild_queued.add(job_id)
                self._queue.put(("rebuild", job_id))

    def wait_rebuild(self, job_id: str, timeout: float = 90.0) -> None:
        job_file = self.output_dir / job_id / "job.json"
        try:
            stale = json.loads(job_file.read_text(encoding="utf-8")).get("sheets_stale")
        except (OSError, ValueError):
            stale = False
        if not stale:
            return
        with self._rebuild_lock:
            ev = self._rebuild_events.get(job_id)
        if ev is None or ev.is_set():
            # Nothing pending: stale from an earlier session or a failed rebuild, so try again now.
            self._rebuild(job_id)
            return
        ev.wait(timeout)

    # ---- background thread bodies ----

    def _load_engine(self) -> None:
        try:
            self.engine = self.engine_factory()
            self.status = VC_RUNTIME_STATUS if onnxruntime_error() else "Ready"
        except Exception as exc:
            log.exception("engine build failed")
            self.status = f"Engine failed: {exc}"
        finally:
            self._engine_done.set()

    def _loop(self) -> None:
        while True:
            task = self._queue.get()
            if task[0] == "run":
                _, job_id, menu_path, opts = task
                self._run(job_id, menu_path, opts)
            else:
                _, job_id = task
                self._rebuild(job_id)

    def _run(self, job_id: str, menu_path: Path, opts: JobOptions) -> None:
        self.current = job_id
        job_dir = self.output_dir / job_id
        try:
            self._engine_done.wait()
            if self.engine is None:
                job_file = job_dir / "job.json"
                job = json.loads(job_file.read_text(encoding="utf-8")) if job_file.exists() else {"id": job_id}
                job.update(status="failed", error=self.status, updated=_now())
                _write_json(job_file, job)
                self.bus.publish(job_id, {"type": "error", "message": self.status})
                return
            settings = load_settings(self.config_path)
            uploader = (
                Uploader(settings.imgbb_keys, store=self.engine.store)
                if any(k.key for k in settings.imgbb_keys) else None
            )
            cancel_event = threading.Event()
            self._cancels[job_id] = cancel_event
            try:
                run_job(self.engine, menu_path, job_dir, opts, uploader=uploader,
                        on_event=lambda ev: self.bus.publish(job_id, ev), cancel=cancel_event)
            except Exception:
                log.exception("job %s crashed", job_id)
                self.bus.publish(job_id, {"type": "error", "message": "Internal error"})
        finally:
            self._cancels.pop(job_id, None)
            self._active.discard(job_id)
            self.current = None

    def _rebuild(self, job_id: str) -> None:
        with self._rebuild_lock:
            self._rebuild_queued.discard(job_id)
            gen = self._gen.get(job_id, 0)
        job_dir = self.output_dir / job_id
        try:
            with self._build_lock:
                if self.engine is not None:
                    rebuild_outputs(self.engine, job_dir)
                    with job_lock(job_dir):
                        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
                        if self._gen.get(job_id, 0) == gen:
                            job["sheets_stale"] = False
                            _write_json(job_dir / "job.json", job)
        except Exception as exc:
            log.exception("rebuild failed for %s", job_id)
            if isinstance(exc, PermissionError):
                name = Path(exc.filename).name if exc.filename else "the sheet"
                message = f"Close the Excel file ({name}) and try again."
            else:
                message = f"Could not update the sheets: {exc}"[:300]
            try:
                with job_lock(job_dir):
                    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
                    job["rebuild_error"] = message
                    _write_json(job_dir / "job.json", job)
            except (OSError, ValueError):
                log.exception("could not record rebuild error for %s", job_id)
        finally:
            with self._rebuild_lock:
                self._built[job_id] = max(self._built.get(job_id, 0), gen)
                ev = self._rebuild_events.setdefault(job_id, threading.Event())
                if self._built[job_id] >= self._gen.get(job_id, 0):
                    ev.set()


def _require_fresh_sheets(job: dict) -> None:
    """Refuse to serve sheets that miss the user's latest photo changes."""
    if job.get("rebuild_error"):
        raise HTTPException(409, job["rebuild_error"])
    if job.get("sheets_stale"):
        raise HTTPException(409, "The sheets are still being updated with your photo changes. Try again in a moment.")


def _make_default_factory(config_path: Path, set_status: Callable[[str], None]) -> Callable[[], Engine]:
    def factory() -> Engine:
        def on_status(msg: str) -> None:
            set_status(ENGINE_STATUS_MAP.get(msg, msg))
        return build_engine(load_settings(config_path), on_status=on_status)
    return factory


def _settings_view(settings: Settings) -> dict:
    return {
        "imgbb_keys": [
            {"id": i, "label": k.label, "tail": k.key[-4:] if k.key else "", "enabled": k.enabled}
            for i, k in enumerate(settings.imgbb_keys)
        ],
        "strictness": settings.strictness,
        "live_search": settings.live_search,
        "live_budget_menus": settings.live_budget_menus,
        "default_city": settings.default_city,
        "cities": sorted(CITIES.keys()),
    }


def create_app(engine_factory: Callable[[], Engine] | None = None, *, output_dir: Path = OUTPUT_DIR,
               config_path: Path = CONFIG_PATH, start_worker: bool = True) -> FastAPI:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir = output_dir / "_uploads"
    config_path = Path(config_path)

    app = FastAPI()
    worker = Worker(output_dir=output_dir, config_path=config_path)
    worker.engine_factory = engine_factory or _make_default_factory(config_path, worker.set_status)
    app.state.worker = worker
    if start_worker:
        worker.start()

    def _job_dir(job_id: str) -> Path:
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404)
        base = output_dir.resolve()
        d = (base / job_id).resolve()
        try:
            d.relative_to(base)
        except ValueError:
            raise HTTPException(404)
        return d

    def _existing_job_dir(job_id: str) -> Path:
        d = _job_dir(job_id)
        if not (d / "job.json").exists():
            raise HTTPException(404)
        return d

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": "menustudio", "version": studio.__version__}

    @app.get("/api/system")
    def system():
        settings = load_settings(config_path)
        engine = worker.engine
        return {
            "ready": engine is not None,
            "status": worker.status,
            "pool_items": engine.store.count_items() if engine else 0,
            "pool_restaurants": engine.store.count_restaurants() if engine else 0,
            "vision": bool(engine.vision.available) if engine else False,
            "vision_reason": engine.vision.reason if engine else "",
            "keys": sum(1 for k in settings.imgbb_keys if k.key),
            "version": studio.__version__,
            "active_job": worker.current,
            "free_gb": round(shutil.disk_usage(output_dir).free / 1_000_000_000, 1),
        }

    @app.get("/api/settings")
    def get_settings():
        return _settings_view(load_settings(config_path))

    @app.put("/api/settings")
    def put_settings(body: dict):
        current = load_settings(config_path)
        keys: list[ImgbbKey] = []
        for i, e in enumerate(body.get("imgbb_keys", [])):
            label = str(e.get("label") or "").strip() or f"Key {i + 1}"
            enabled = bool(e.get("enabled", True))
            key_val = str(e.get("key") or "").strip()
            eid = e.get("id")
            if eid is not None and not key_val:
                try:
                    key_val = current.imgbb_keys[int(eid)].key
                except (IndexError, TypeError, ValueError):
                    raise HTTPException(400, "That doesn't look like an ImgBB key")
            elif not KEY_RE.match(key_val):
                raise HTTPException(400, "That doesn't look like an ImgBB key")
            keys.append(ImgbbKey(label=label, key=key_val, enabled=enabled))
        strictness = body.get("strictness", current.strictness)
        if strictness not in ("strict", "balanced"):
            strictness = "balanced"
        settings = Settings(
            imgbb_keys=keys,
            strictness=strictness,
            live_search=bool(body.get("live_search", current.live_search)),
            live_budget_menus=max(0, min(2000, int(body.get("live_budget_menus", current.live_budget_menus)))),
            default_city=str(body.get("default_city", current.default_city)).strip().lower(),
        )
        save_settings(settings, config_path)
        return _settings_view(settings)

    @app.post("/api/settings/test-key")
    def post_test_key(body: dict):
        key = str(body.get("key") or "").strip()
        if not key and body.get("id") is not None:
            current = load_settings(config_path)
            try:
                key = current.imgbb_keys[int(body["id"])].key
            except (IndexError, TypeError, ValueError):
                key = ""
        if not key:
            return {"ok": False, "message": "Unknown key"}
        ok, message = test_key(key)
        return {"ok": ok, "message": message}

    @app.post("/api/menu/preview")
    async def menu_preview(file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File too large")
        upload_id = uuid.uuid4().hex
        ext = Path(file.filename or "").suffix.lower()
        uploads_dir.mkdir(parents=True, exist_ok=True)
        path = uploads_dir / f"{upload_id}{ext}"
        path.write_bytes(data)
        parsed = read_menu(path)
        rows = [
            {"row": r.row, "name": r.name, "category": r.category, "description": r.description,
             "price": r.price, "warnings": r.warnings}
            for r in parsed.rows
        ]
        categories: dict[str, int] = {}
        for r in parsed.rows:
            categories[r.category] = categories.get(r.category, 0) + 1
        return {
            "upload_id": upload_id, "file_name": file.filename, "sheet": parsed.sheet_name,
            "rows": rows, "categories": [{"name": k, "count": v} for k, v in categories.items()],
            "warnings": parsed.warnings, "errors": parsed.errors,
        }

    @app.post("/api/jobs")
    def post_job(body: dict):
        vendor = str(body.get("vendor") or "").strip()
        if not vendor:
            raise HTTPException(400, "Enter the restaurant name")
        upload_id = str(body.get("upload_id") or "")
        matches = list(uploads_dir.glob(f"{upload_id}.*")) if UPLOAD_ID_RE.match(upload_id) else []
        if not matches:
            raise HTTPException(400, "Upload the menu again")
        menu_path = matches[0]
        settings = load_settings(config_path)
        city = str(body.get("city") or settings.default_city or "").strip().lower()
        opts = JobOptions(
            vendor=vendor, city=city, zomato_url=_validate_zomato_url(str(body.get("zomato_url") or "")),
            sku_prefix=str(body.get("sku_prefix") or "").strip(),
            strictness=settings.strictness, live_search=settings.live_search,
            live_budget_menus=settings.live_budget_menus,
        )
        job_id = new_job_id(vendor)
        job_dir = output_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        _write_json(job_dir / "job.json", {
            "id": job_id, "vendor": vendor, "options": asdict(opts), "status": "queued",
            "stage": "", "created": _now(), "updated": _now(), "summary": None,
            "error": None, "menu_file": "",
        })
        worker.enqueue_run(job_id, menu_path, opts)
        return {"id": job_id}

    @app.get("/api/jobs")
    def get_jobs():
        out = []
        for j in list_jobs(output_dir):
            status = j.get("status")
            if status == "running" and not worker.is_active(j["id"]):
                status = "interrupted"
            out.append({"id": j["id"], "vendor": j.get("vendor", ""), "status": status,
                        "created": j.get("created", ""), "summary": j.get("summary")})
        return out

    @app.get("/api/jobs/{id}")
    def get_job_route(id: str):
        job_dir = _existing_job_dir(id)
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        if job.get("status") == "running" and not worker.is_active(id):
            job = dict(job, status="interrupted")
        results_file = job_dir / "results.json"
        results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else []
        return {"job": job, "results": results, "active": worker.is_active(id)}

    @app.get("/api/jobs/{id}/events")
    async def job_events(id: str, after: int = -1):
        _existing_job_dir(id)

        async def gen():
            last = after
            while True:
                items = worker.bus.after(id, last)
                for idx, ev in items:
                    last = idx
                    yield f"id: {idx}\ndata: {json.dumps(ev)}\n\n"
                    if ev.get("type") in ("done", "error"):
                        return
                if not items and not worker.is_active(id):
                    return
                got = await asyncio.to_thread(worker.bus.wait_for_more, id, last, 15.0)
                if not got:
                    yield ": keepalive\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/jobs/{id}/cancel")
    def cancel_job(id: str):
        _existing_job_dir(id)
        worker.cancel(id)
        return {"ok": True}

    @app.post("/api/jobs/{id}/resume")
    def resume_job(id: str):
        job_dir = _existing_job_dir(id)
        if worker.is_active(id):
            raise HTTPException(409, "Job is already active")
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        menu_file = job.get("menu_file") or ""
        menu_path = job_dir / menu_file if menu_file else None
        if menu_path is None or not menu_path.is_file():
            raise HTTPException(400, "Menu file missing; upload the menu again")
        fields = JobOptions.__dataclass_fields__
        opts = JobOptions(**{k: v for k, v in (job.get("options") or {}).items() if k in fields})
        worker.enqueue_run(id, menu_path, opts)
        return {"ok": True}

    @app.post("/api/jobs/{id}/dishes/{sku}/choose")
    def choose_dish(id: str, sku: str, body: dict):
        job_dir = _existing_job_dir(id)
        if not SKU_RE.match(sku):
            raise HTTPException(404)
        if worker.engine is None:
            raise HTTPException(503, "Engine not ready")
        if worker.is_active(id):
            raise HTTPException(409, "This job is still running — wait until it finishes, then change photos.")
        alt_index = body.get("alt_index")
        settings = load_settings(config_path)
        uploader = (
            Uploader(settings.imgbb_keys, store=worker.engine.store)
            if any(k.key for k in settings.imgbb_keys) else None
        )
        # Holding the job lock until the swap is counted stops an in-flight rebuild from
        # clearing sheets_stale between this swap's write and request_rebuild.
        with job_lock(job_dir):
            try:
                result = choose_alternate(worker.engine, job_dir, sku, alt_index, uploader, rebuild=False)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            worker.request_rebuild(id)
        return dish_result_to_dict(result)

    @app.post("/api/jobs/{id}/dishes/{sku}/search")
    def search_dish(id: str, sku: str, body: dict):
        job_dir = _existing_job_dir(id)
        if not SKU_RE.match(sku):
            raise HTTPException(404)
        if worker.engine is None:
            raise HTTPException(503, "Engine not ready")
        if worker.is_active(id):
            raise HTTPException(409, "This job is still running — wait until it finishes, then change photos.")
        query = str(body.get("query") or "").strip()
        if not query:
            raise HTTPException(400, "Type a dish name to search for")
        try:
            result = search_photos(worker.engine, job_dir, sku, query)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return dish_result_to_dict(result)

    @app.post("/api/jobs/{id}/approve")
    def approve_job_dishes(id: str, body: dict):
        job_dir = _existing_job_dir(id)
        if worker.engine is None:
            raise HTTPException(503, "Engine not ready")
        if worker.is_active(id):
            raise HTTPException(409, "This job is still running — wait until it finishes, then change photos.")
        if body.get("all"):
            data = json.loads((job_dir / "results.json").read_text(encoding="utf-8"))
            skus = [d["sku"] for d in data if d.get("status") == "review"]
        else:
            skus = body.get("skus")
            if not isinstance(skus, list) or not all(isinstance(s, str) and SKU_RE.match(s) for s in skus):
                raise HTTPException(400, "Invalid SKU list")
        settings = load_settings(config_path)
        uploader = (
            Uploader(settings.imgbb_keys, store=worker.engine.store)
            if any(k.key for k in settings.imgbb_keys) else None
        )
        with job_lock(job_dir):
            try:
                results = approve_dishes(worker.engine, job_dir, skus, uploader)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            worker.request_rebuild(id)
        return {"results": [dish_result_to_dict(r) for r in results]}

    @app.get("/api/jobs/{id}/files/{kind}")
    def get_job_file(id: str, kind: str):
        job_dir = _existing_job_dir(id)
        if kind not in FILE_KINDS:
            raise HTTPException(404)
        worker.wait_rebuild(id)
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        _require_fresh_sheets(job)
        name = ((job.get("summary") or {}).get("files") or {}).get(kind)
        if not name:
            raise HTTPException(404)
        path = job_dir / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename=name,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/api/jobs/{id}/images/{sku}.jpg")
    def get_job_image(id: str, sku: str):
        job_dir = _existing_job_dir(id)
        if not SKU_RE.match(sku):
            raise HTTPException(404)
        path = job_dir / "images" / f"{sku}.jpg"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/jobs/{id}/zip")
    def get_job_zip(id: str):
        job_dir = _existing_job_dir(id)
        worker.wait_rebuild(id)
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        _require_fresh_sheets(job)
        files = (job.get("summary") or {}).get("files") or {}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for kind in FILE_KINDS:
                name = files.get(kind)
                if name and (job_dir / name).is_file():
                    zf.write(job_dir / name, arcname=name)
            images_dir = job_dir / "images"
            if images_dir.is_dir():
                for img in sorted(images_dir.iterdir()):
                    zf.write(img, arcname=f"images/{img.name}")
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{id}.zip"'})

    @app.get("/")
    def index():
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        return Response(html, media_type="text/html", headers={"Cache-Control": "no-store"})

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    return app

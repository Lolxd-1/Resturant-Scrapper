"""Paths and persistent user settings."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

from studio.models import ImgbbKey, Settings

log = logging.getLogger("studio.config")

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config" / "settings.json"
OUTPUT_DIR = APP_DIR / "outputs"
TEMPLATE_PATH = DATA_DIR / "smartbiz_template.xlsx"
SEED_POOL_PATH = DATA_DIR / "seed_pool.jsonl.gz"


def home_dir() -> Path:
    """Runtime folder for the pool DB, models and caches (never inside the app folder)."""
    env = os.environ.get("MENUSTUDIO_HOME")
    if env:
        p = Path(env)
    elif os.environ.get("LOCALAPPDATA"):
        p = Path(os.environ["LOCALAPPDATA"]) / "MenuStudio"
    else:
        p = Path.home() / ".menustudio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pool_db_path() -> Path:
    return home_dir() / "pool.sqlite"


def models_dir() -> Path:
    p = home_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to path via a tmp file + os.replace, retrying ~2 s on PermissionError
    (OneDrive/antivirus can briefly lock a file right after it's written)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    deadline = time.monotonic() + 2.0
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_PATH
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        keys = [ImgbbKey(label=str(k.get("label", "")).strip() or f"Key {i + 1}",
                         key=str(k.get("key", "")).strip(),
                         enabled=bool(k.get("enabled", True)))
                for i, k in enumerate(raw.get("imgbb_keys", [])) if str(k.get("key", "")).strip()]
        strictness = raw.get("strictness", "balanced")
        return Settings(
            imgbb_keys=keys,
            strictness=strictness if strictness in ("strict", "balanced") else "balanced",
            live_search=bool(raw.get("live_search", True)),
            live_budget_menus=max(0, min(2000, int(raw.get("live_budget_menus", 250)))),
            default_city=str(raw.get("default_city", "")).strip().lower(),
        )
    except (ValueError, TypeError, AttributeError) as e:
        bad = path.with_suffix(".bad")
        log.warning("settings file unreadable (%s); moved to %s", e, bad.name)
        os.replace(path, bad)
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    atomic_write_text(path, json.dumps(asdict(settings), indent=2, ensure_ascii=False))

"""Tests for studio.config."""
from __future__ import annotations

import json

from studio.config import home_dir, load_settings, models_dir, save_settings
from studio.models import DishResult, ImgbbKey, Settings, dish_result_from_dict, dish_result_to_dict


def test_save_and_load_round_trip(tmp_path):
    """TC1: save then load returns an equal Settings."""
    p = tmp_path / "settings.json"
    settings = Settings(imgbb_keys=[ImgbbKey("Main", "abcd1234")], strictness="strict")
    save_settings(settings, p)
    assert load_settings(p) == settings


def test_missing_path_returns_defaults(tmp_path):
    """TC2: missing path returns defaults (no keys, strictness balanced)."""
    p = tmp_path / "missing.json"
    loaded = load_settings(p)
    assert loaded == Settings()
    assert loaded.imgbb_keys == []
    assert loaded.strictness == "balanced"


def test_corrupt_file_renamed_to_bad(tmp_path):
    """TC3: corrupt file returns defaults and gets renamed to *.bad."""
    p = tmp_path / "settings.json"
    p.write_text("{not json", encoding="utf-8")
    loaded = load_settings(p)
    assert loaded == Settings()
    assert not p.exists()
    assert p.with_suffix(".bad").exists()


def test_load_settings_sanitizes_values(tmp_path):
    """TC4: blank keys dropped, blank label defaulted, budget clamped, bad strictness defaulted."""
    p = tmp_path / "settings.json"
    p.write_text(
        json.dumps({
            "imgbb_keys": [
                {"label": "", "key": "realkey"},
                {"label": "Blank", "key": "  "},
            ],
            "strictness": "weird",
            "live_budget_menus": 99999,
        }),
        encoding="utf-8",
    )
    loaded = load_settings(p)
    assert len(loaded.imgbb_keys) == 1
    assert loaded.imgbb_keys[0].label == "Key 1"
    assert loaded.imgbb_keys[0].key == "realkey"
    assert loaded.live_budget_menus == 2000
    assert loaded.strictness == "balanced"


def test_home_dir_and_dish_result_round_trip(tmp_home):
    """TC5: home_dir/models_dir honor MENUSTUDIO_HOME; DishResult round-trips through dict."""
    assert home_dir() == tmp_home
    assert models_dir().exists()
    r = DishResult(
        row=1, sku="HFC-001", name="पनीर ₹", category="Starters", description="d",
        price=199.0, alternates=[{"item_name": "x"}],
    )
    assert dish_result_from_dict(dish_result_to_dict(r)) == r

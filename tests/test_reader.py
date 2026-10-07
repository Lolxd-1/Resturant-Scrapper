"""Tests for studio.reader: menu photo reading with a fake Gemini."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from studio.menu import read_menu
from studio.prompts import MENU_READER_SYSTEM
from studio.reader import MenuReadError, prepare_image, read_menu_images, write_extract


def _jpeg(size=(40, 30), orientation=None) -> bytes:
    out = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    Image.new("RGB", size, "white").save(out, "JPEG", exif=exif)
    return out.getvalue()


class FakeGemini:
    last_model = "fake"

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def generate_json(self, system, parts, schema, **kw):
        self.calls.append((system, parts, kw))
        return self.answer


ANSWER = {"restaurant_name": "Cafe", "items": [
    {"name": "Paneer Pizza", "variant": "Medium", "category": "Pizza", "price": 220,
     "description": "x", "diet": "veg", "photo_names": ["Paneer Pizza", "Veg Pizza"]},
    {"name": "Tea", "variant": "", "category": "Beverages", "price": "15",
     "description": "", "diet": "maybe", "photo_names": []},
]}


def test_tc1_read_menu_images_cleans_items():
    gem = FakeGemini(ANSWER)
    name, items = read_menu_images(gem, [_jpeg(), _jpeg()])

    assert name == "Cafe"
    assert [i["name"] for i in items] == ["Paneer Pizza (Medium)", "Tea"]
    assert [i["price"] for i in items] == [220.0, 15.0]
    assert items[1]["diet"] == ""
    assert items[0]["photo_names"] == ["Veg Pizza"]
    system, parts, kw = gem.calls[0]
    assert system == MENU_READER_SYSTEM and kw["high_res"] is True
    assert sum("inlineData" in p for p in parts) == 2


def test_tc2_prepare_image_rotates_and_scales():
    out = prepare_image(_jpeg((4000, 3000), orientation=6))
    assert Image.open(io.BytesIO(out)).size == (2304, 3072)


def test_tc3_errors():
    with pytest.raises(MenuReadError):
        read_menu_images(FakeGemini(ANSWER), [])
    with pytest.raises(MenuReadError):
        read_menu_images(FakeGemini(ANSWER), [_jpeg()] * 9)
    with pytest.raises(MenuReadError):
        read_menu_images(FakeGemini(ANSWER), [b"garbage"])
    with pytest.raises(MenuReadError):
        read_menu_images(FakeGemini({"restaurant_name": "", "items": []}), [_jpeg()])


def test_tc4_write_extract_round_trips_through_read_menu(tmp_path):
    _, items = read_menu_images(FakeGemini(ANSWER), [_jpeg()])
    path = write_extract(items, tmp_path / "menu_extract.xlsx")

    rows = read_menu(path).rows
    assert [r.diet for r in rows] == ["veg", ""]
    assert rows[0].photo_names == ["Veg Pizza"]
    assert rows[0].price == 220.0
    assert rows[0].category == "Pizza"

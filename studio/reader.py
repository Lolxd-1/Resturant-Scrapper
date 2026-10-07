"""Read menu photos with Gemini into clean dish items, and save them as an Excel the pipeline reads."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from PIL import Image, ImageOps

from studio.gemini import image_part, text_part
from studio.menu import parse_price
from studio.prompts import MENU_READER_SYSTEM, MENU_SCHEMA

log = logging.getLogger("studio.reader")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MAX_PHOTOS = 8
_MAX_SIDE = 3072
_MAX_DESCRIPTION = 300
_MAX_PHOTO_NAMES = 3
_MAX_PHOTO_NAME_LEN = 80
_DIETS = ("veg", "nonveg", "egg")
_DIET_LABELS = {"veg": "Veg", "nonveg": "Non-Veg", "egg": "Egg", "": ""}
_HEADERS = ("Item Name", "Category", "Description", "Price", "Diet", "Photo Names")
_WIDTHS = (36, 20, 50, 10, 10, 40)


class MenuReadError(Exception):
    """str(exc) is a plain-English message for the user."""


def prepare_image(data: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:
        raise MenuReadError("Could not open one of the photos. Use JPG or PNG.") from e
    img.thumbnail((_MAX_SIDE, _MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def _clean_item(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    seen = {name.lower()}
    variant = str(raw.get("variant") or "").strip()
    if variant and variant.lower() not in name.lower():
        name = f"{name} ({variant})"
    diet = raw.get("diet")
    photo_names: list[str] = []
    for p in raw.get("photo_names") or []:
        if not isinstance(p, str):
            continue
        p = p.strip()
        if not p or p.lower() in seen:
            continue
        seen.add(p.lower())
        photo_names.append(p[:_MAX_PHOTO_NAME_LEN])
    return {
        "name": name,
        "category": str(raw.get("category") or "").strip() or "Menu",
        "description": str(raw.get("description") or "").strip()[:_MAX_DESCRIPTION],
        "price": parse_price(raw.get("price")),
        "diet": diet if diet in _DIETS else "",
        "photo_names": photo_names[:_MAX_PHOTO_NAMES],
    }


def read_menu_images(gemini, images: list[bytes]) -> tuple[str, list[dict]]:
    if not images:
        raise MenuReadError("Add at least one menu photo.")
    if len(images) > MAX_PHOTOS:
        raise MenuReadError(f"Upload at most {MAX_PHOTOS} photos per menu.")
    parts = [text_part(f"{len(images)} menu photo(s). Read every dish on every photo.")]
    for i, data in enumerate(images, 1):
        parts.append(text_part(f"Photo {i}:"))
        parts.append(image_part(prepare_image(data)))
    answer = gemini.generate_json(MENU_READER_SYSTEM, parts, MENU_SCHEMA, high_res=True)

    items: list[dict] = []
    seen: set[tuple[str, float | None]] = set()
    for raw in answer.get("items") or []:
        item = _clean_item(raw)
        if item is None:
            continue
        key = (item["name"], item["price"])
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    if not items:
        raise MenuReadError("No dishes found on the photo(s). Try a sharper, straight photo of the menu.")
    log.info("Read %d dishes from menu photos (model %s)", len(items), gemini.last_model)
    return str(answer.get("restaurant_name") or "").strip(), items


def write_extract(items: list[dict], path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Menu"
    ws.append(list(_HEADERS))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col, width in zip("ABCDEF", _WIDTHS):
        ws.column_dimensions[col].width = width
    for it in items:
        price = it["price"]
        if price is not None and float(price).is_integer():
            price = int(price)
        ws.append([it["name"], it["category"], it["description"], price,
                   _DIET_LABELS[it["diet"]], "; ".join(it["photo_names"])])
    path = Path(path)
    wb.save(path)
    return path

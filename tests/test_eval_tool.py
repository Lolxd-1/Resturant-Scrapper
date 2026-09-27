"""Tests for tools.eval_menus (offline; no real network access)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from studio.models import DishResult
from tools.eval_menus import contact_sheets, html_report


def mk(row, sku, name, local_image="", reason="", tier="strong", confidence=0.8,
       source="pool", item_name="", restaurant="", status="ready") -> DishResult:
    return DishResult(
        row=row, sku=sku, name=name, category="Menu", description="", price=100.0,
        status=status, reason=reason, tier=tier, confidence=confidence, source=source,
        item_name=item_name, restaurant=restaurant, local_image=local_image,
    )


def _make_results(job_dir: Path, n: int, without_photo: int) -> list[DishResult]:
    (job_dir / "images").mkdir(parents=True, exist_ok=True)
    results = []
    for i in range(1, n + 1):
        has_photo = i > without_photo
        local_image = ""
        if has_photo:
            local_image = f"images/SKU-{i:03d}.jpg"
            Image.new("RGB", (400, 400), (100, 150, 200)).save(job_dir / local_image, "JPEG")
        results.append(mk(
            i, f"SKU-{i:03d}", f"Dish {i}", local_image=local_image,
            reason="" if has_photo else "Not found on Zomato",
            item_name=f"Zomato Dish {i}", restaurant=f"Restaurant {i}",
            status="ready" if has_photo else "needs_photo",
        ))
    return results


# ---- TC1: contact_sheets with 23 fake results (7 without photos) -> 2 files, first 1500x1560 px ----

def test_tc1_contact_sheets(tmp_path):
    job_dir = tmp_path / "job"
    results = _make_results(job_dir, n=23, without_photo=7)

    paths = contact_sheets(results, job_dir, job_dir / "contact_sheet")

    assert len(paths) == 2
    with Image.open(paths[0]) as img:
        assert img.size == (1500, 1560)
    for p in paths:
        assert p.exists()


# ---- TC2: html_report contains every SKU and escapes "<script>" in a dish name ----

def test_tc2_html_report(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir(parents=True)
    results = [
        mk(1, "SKU-001", "Dish1", local_image=""),
        mk(2, "SKU-002", "<script>alert(1)</script>"),
        mk(3, "SKU-003", "Dish3"),
    ]

    out_path = html_report(results, job_dir, job_dir / "review.html")
    text = out_path.read_text(encoding="utf-8")

    for r in results:
        assert r.sku in text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text

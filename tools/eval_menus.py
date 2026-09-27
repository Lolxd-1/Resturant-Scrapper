"""CLI tool: run real (network) dry-run jobs over a folder of menu files and produce
contact sheets + an HTML review page + a coverage summary, so a reviewer can audit
every chosen photo without touching ImgBB."""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont

from studio.config import load_settings
from studio.models import DishResult, dish_result_from_dict
from studio.pipeline import JobOptions, build_engine, run_job

TILE = 300
CAPTION_H = 90
COLS = 5
_MENU_EXTS = {".xlsx", ".xlsm", ".csv"}


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _tile_image(r: DishResult, job_dir: Path) -> Image.Image:
    if r.local_image:
        try:
            return Image.open(job_dir / r.local_image).convert("RGB").resize((TILE, TILE), Image.LANCZOS)
        except Exception:
            pass
    img = Image.new("RGB", (TILE, TILE), (200, 200, 200))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), f"NO PHOTO: {r.reason or 'no photo'}", fill=(60, 60, 60), font=_font(13))
    return img


def _draw_caption(draw: ImageDraw.ImageDraw, r: DishResult, x: int, y: int, font: ImageFont.ImageFont) -> None:
    line1 = _truncate(f"{r.sku}  {r.name}", 38)
    match = f"{r.item_name} @ {r.restaurant}" if r.item_name else ""
    line2 = _truncate(f"-> {match}", 44)
    line3 = f"{r.tier} {r.confidence:.2f} {r.source}".strip()
    for i, line in enumerate((line1, line2, line3)):
        draw.text((x + 4, y + 4 + i * 16), line, fill=(0, 0, 0), font=font)


def contact_sheets(results: list[DishResult], job_dir: Path, out_prefix: Path, per_sheet: int = 20) -> list[Path]:
    job_dir, out_prefix = Path(job_dir), Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    rows_per_sheet = -(-per_sheet // COLS)
    sheet_w, sheet_h = COLS * TILE, rows_per_sheet * (TILE + CAPTION_H)
    font = _font(13)
    paths = []
    for start in range(0, len(results), per_sheet):
        chunk = results[start:start + per_sheet]
        sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            col, row = i % COLS, i // COLS
            x, y = col * TILE, row * (TILE + CAPTION_H)
            sheet.paste(_tile_image(r, job_dir), (x, y))
            _draw_caption(draw, r, x, y + TILE, font)
        path = out_prefix.parent / f"{out_prefix.name}_{start // per_sheet + 1:02d}.jpg"
        sheet.save(path, "JPEG", quality=85)
        paths.append(path)
    return paths


def html_report(results: list[DishResult], job_dir: Path, out_path: Path) -> Path:
    job_dir, out_path = Path(job_dir), Path(out_path)
    rows = []
    for r in sorted(results, key=lambda r: r.row):
        if r.local_image:
            img = f'<img src="{html.escape(r.local_image)}" width="150">'
        else:
            img = f"NO PHOTO: {html.escape(r.reason or 'no photo')}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(r.sku)}</td>"
            f"<td>{img}</td>"
            f"<td>{html.escape(r.name)}</td>"
            f"<td>{html.escape(r.item_name)} @ {html.escape(r.restaurant)}</td>"
            f"<td>{html.escape(r.tier)} {r.confidence:.2f} {html.escape(r.source)}</td>"
            f"<td>{html.escape(r.status)}</td>"
            f"<td>{html.escape(r.reason)}</td>"
            "</tr>"
        )
    doc = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Photo review</title>"
        "<style>table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px;"
        "vertical-align:top;font-family:sans-serif;font-size:13px}</style></head><body>"
        "<table><tr><th>SKU</th><th>Photo</th><th>Dish</th><th>Match</th>"
        "<th>Tier/Conf/Source</th><th>Status</th><th>Reason</th></tr>"
        + "".join(rows) + "</table></body></html>"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def _menu_files(menus_dir: Path) -> list[Path]:
    return sorted(p for p in menus_dir.iterdir() if p.suffix.lower() in _MENU_EXTS)


def _sidecar_meta(menu_path: Path) -> dict:
    sidecar = menu_path.with_suffix(".json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _print_event(vendor: str, ev: dict) -> None:
    if ev["type"] == "stage" and ev.get("progress", 0.0) == 0.0:
        print(f"  [{vendor}] {ev['label']}")
    elif ev["type"] in ("log", "error"):
        print(f"  [{vendor}] {ev.get('message', '')}")


def _write_summary_csv(path: Path, rows: list[dict]) -> None:
    fields = ["menu", "total", "ready", "needs_photo", "needs_price", "errors", "coverage%"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run dry-run eval jobs over a folder of menus and produce review sheets.")
    parser.add_argument("--menus", required=True)
    parser.add_argument("--out", default="eval/out")
    parser.add_argument("--only")
    parser.add_argument("--city", default="")
    parser.add_argument("--budget", type=int, default=250)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    menus_dir = Path(args.menus)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = _menu_files(menus_dir)
    if args.only:
        files = [f for f in files if f.stem == args.only]

    engine = build_engine(load_settings())
    summary_rows = []
    for menu_path in files:
        stem = menu_path.stem
        meta = _sidecar_meta(menu_path)
        vendor = str(meta.get("vendor") or stem.replace("_", " "))
        city = str(meta.get("city") or args.city)
        zomato_url = str(meta.get("zomato_url", ""))
        job_dir = out_dir / stem
        opts = JobOptions(vendor=vendor, city=city, zomato_url=zomato_url, upload=False,
                           strictness="strict" if args.strict else "balanced",
                           live_budget_menus=args.budget)
        print(f"=== {vendor} ({menu_path.name}) ===")
        summary = run_job(engine, menu_path, job_dir, opts, uploader=None,
                           on_event=lambda ev, vendor=vendor: _print_event(vendor, ev))

        results_path = job_dir / "results.json"
        results = [dish_result_from_dict(d) for d in json.loads(results_path.read_text(encoding="utf-8"))] \
            if results_path.exists() else []
        contact_sheets(results, job_dir, job_dir / "contact_sheet")
        html_report(results, job_dir, job_dir / "review.html")

        total = summary.get("total", 0)
        row = {
            "menu": stem, "total": total, "ready": summary.get("ready", 0),
            "needs_photo": summary.get("needs_photo", 0), "needs_price": summary.get("needs_price", 0),
            "errors": summary.get("errors", 0), "coverage%": round(summary.get("coverage", 0.0) * 100, 1),
        }
        summary_rows.append(row)
        print(f"  {row}")

    _write_summary_csv(out_dir / "summary.csv", summary_rows)
    print(f"Summary written to {out_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()

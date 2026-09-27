"""Headless CLI for the Menu Studio pipeline (v1 file name kept as the entry point).

    python zomato_scrapper.py --menu-excel M.xlsx --vendor "Name" [--city pune]
        [--zomato-url URL] [--sku-prefix HFC] [--out DIR] [--no-upload] [--strict]
        [--no-live-search] [--budget 250]

Runs the whole pipeline (menu read -> match -> live search -> photos -> upload
-> sheets) and prints progress, then the three output sheet paths and the summary.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from studio import pipeline
from studio.config import OUTPUT_DIR, load_settings
from studio.hosting import Uploader
from studio.models import ImgbbKey
from studio.pipeline import JobOptions, load_job, new_job_id, run_job


def _uploader(settings, engine) -> Uploader | None:
    keys = settings.imgbb_keys
    if not keys:
        env_key = os.environ.get("IMGBB_API_KEY", "")
        keys = [ImgbbKey(label="env", key=env_key)] if env_key else []
    return Uploader(keys, store=engine.store) if keys else None


def _on_event(ev: dict) -> None:
    if ev["type"] == "stage":
        print(f"[{ev['stage']}] {ev['label']}")
    elif ev["type"] == "dish":
        r = ev["result"]
        print(f"{r['sku']}  {r['status']}  {r['name']} -> {r['item_name']} @ {r['restaurant']}")
    elif ev["type"] in ("log", "error"):
        print(ev["message"])


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Menu Studio pipeline (headless CLI)")
    ap.add_argument("--menu-excel", required=True, help="Excel with Item Name/Category/Description/Price")
    ap.add_argument("--vendor", required=True, help="Vendor / restaurant name")
    ap.add_argument("--city", default="", help="Zomato city slug, e.g. pune")
    ap.add_argument("--zomato-url", default="", help="Vendor's own Zomato restaurant URL, if known")
    ap.add_argument("--sku-prefix", default="", help="SKU prefix, e.g. HFC gives HFC-001")
    ap.add_argument("--out", default="", help="Output folder (default: outputs/<new job id>)")
    ap.add_argument("--no-upload", action="store_true", help="Skip ImgBB upload")
    ap.add_argument("--strict", action="store_true", help="Strict matching (default: balanced)")
    ap.add_argument("--no-live-search", action="store_true", help="Skip live Zomato search")
    ap.add_argument("--budget", type=int, default=250, help="Max restaurant menus fetched live")
    args = ap.parse_args(argv)

    settings = load_settings()
    engine = pipeline.build_engine(settings, on_status=print)
    uploader = None if args.no_upload else _uploader(settings, engine)

    opts = JobOptions(
        vendor=args.vendor, city=args.city, zomato_url=args.zomato_url, sku_prefix=args.sku_prefix,
        upload=not args.no_upload, strictness="strict" if args.strict else "balanced",
        live_search=not args.no_live_search, live_budget_menus=args.budget,
    )
    job_dir = Path(args.out) if args.out else OUTPUT_DIR / new_job_id(args.vendor)

    summary = run_job(engine, Path(args.menu_excel), job_dir, opts, uploader=uploader, on_event=_on_event)

    for fname in summary.get("files", {}).values():
        print(job_dir / fname)
    print(summary)

    return 0 if load_job(job_dir)["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())

"""Resturant-Scrapper PROD — Streamlit front-end (team use, $0 hosting).

Flow: upload menu Excel -> match Zomato photos (baked data/pairs.json) ->
download + ImageBB host -> build SmartBiz sheets -> download results.

Each run uses its own temp dir, so 1-2 teammates can use it simultaneously
without overwriting each other's files. Nothing is committed anywhere;
outputs live only as in-browser downloads.

Secrets: ImageBB key comes from the sidebar input, or (recommended on
Streamlit Community Cloud) Settings -> Secrets as IMGBB_API_KEY.
"""
import json
import re
import tempfile
import traceback
from pathlib import Path

import openpyxl
import streamlit as st

from zomato_scrapper import (
    build_sheet,
    match_dishes,
    run_download,
)

BASE = Path(__file__).resolve().parent
PAIRS_PATH = BASE / "data" / "pairs.json"
TEMPLATE_PATH = BASE / "data" / "smartbiz_template.xlsx"

st.set_page_config(page_title="Resturant-Scrapper PROD", layout="wide")
st.title("Resturant-Scrapper PROD v1.0")
st.caption("Menu Excel in → Amazon SmartBiz sheets out. Photos: Zomato, hosted free on ImageBB.")


def derive_prefix(name: str) -> str:
    # "H-Food Cafe" -> HFC, "Domino's" -> DOM (apostrophe kept together).
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", name or "")
    if not words:
        return "SKU"
    if len(words) == 1:
        return re.sub(r"[^A-Za-z]", "", words[0])[:3].upper()
    return "".join(w[0] for w in words[:3]).upper()


def validate_menu(path: Path):
    """Returns (dishes, error). dishes = list of (name, desc, price)."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        return None, f"Could not open Excel: {e}"
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return None, "Excel is empty."
    header = [(c or "") for c in rows[0][:4]]
    if "item" not in str(header[0]).lower() or "price" not in str(header[3]).lower():
        return None, (
            "Bad header. Row 1 must be: Item Name | Category | Description | Price "
            f"(found: {header})"
        )
    dishes = []
    for i, r in enumerate(rows[1:], start=2):
        if not r[0]:
            continue
        try:
            price = int(float(r[3] or 0))
        except (TypeError, ValueError):
            return None, f"Row {i}: Price must be a number (found {r[3]!r})."
        if price <= 0:
            return None, f"Row {i}: Price must be > 0 (found {r[3]!r})."
        dishes.append((str(r[0]).strip(), str(r[2] or "").strip(), price))
    if not dishes:
        return None, "No dishes found below the header row."
    return dishes, None


with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("ImageBB API key", type="password",
                            help="Free key from https://api.imgbb.com/. "
                                 "Or set IMGBB_API_KEY in app Secrets.")
    if not api_key:
        try:
            api_key = st.secrets["IMGBB_API_KEY"]
            st.success("Using key from app Secrets.")
        except Exception:
            pass
    st.divider()
    st.markdown(
        "**Menu format:** row 1 = `Item Name | Category | Description | Price`, "
        "one dish per row below. Prices must be numbers > 0."
    )

col1, col2 = st.columns(2)
with col1:
    vendor = st.text_input("Restaurant / vendor name", value="H-Food Cafe")
with col2:
    prefix = st.text_input("SKU prefix", value=derive_prefix(vendor),
                           help="SKUs look like PREFIX-001. 2-4 letters is ideal.")
prefix = re.sub(r"[^A-Za-z0-9]", "", prefix).upper()[:6] or "SKU"

menu_file = st.file_uploader("Menu Excel (.xlsx)", type=["xlsx"])
tpl_file = st.file_uploader(
    "SmartBiz template (.xlsx) — optional, bundled default is used if empty",
    type=["xlsx"],
)

run_btn = st.button("Run pipeline", type="primary", disabled=menu_file is None)
if not menu_file:
    st.info("Upload a menu Excel to begin.")
    st.stop()

if run_btn:
    for k in ("done", "ready_bytes", "pending_bytes", "novel_text",
              "summary", "table"):
        st.session_state.pop(k, None)

    workdir = Path(tempfile.mkdtemp(prefix="scrapper_"))
    menu_path = workdir / "menu.xlsx"
    menu_path.write_bytes(menu_file.getbuffer())
    if tpl_file:
        template_path = workdir / "template.xlsx"
        template_path.write_bytes(tpl_file.getbuffer())
    else:
        template_path = TEMPLATE_PATH

    if not PAIRS_PATH.exists():
        st.error("Photo pool data/pairs.json is missing from the repo. "
                 "Run harvest locally and commit it (see README).")
        st.stop()
    if not Path(template_path).exists():
        st.error("SmartBiz template not found (and none uploaded).")
        st.stop()

    dishes, err = validate_menu(menu_path)
    if err:
        st.error(err)
        st.stop()
    if not api_key:
        st.error("Enter your ImageBB API key in the sidebar first.")
        st.stop()

    dish_names = [d[0] for d in dishes]
    pairs = json.loads(PAIRS_PATH.read_text())
    st.write(f"Photo pool: **{len(pairs)}** Zomato dish photos. "
             f"Menu: **{len(dish_names)}** dishes.")

    try:
        with st.spinner("Matching dishes to photos..."):
            picks = match_dishes(dish_names, pairs)
        matched = sum(1 for v in picks.values() if v)
        st.write(f"Matched **{matched}/{len(picks)}** dishes.")

        bar = st.progress(0, text="Downloading + hosting photos...")
        log_box = st.empty()
        logs = []

        def progress(done, total, msg):
            bar.progress(done / max(total, 1), text=f"{done}/{total} {msg}")
            logs.append(msg)
            if len(logs) % 10 == 0:
                log_box.caption(" · ".join(logs[-3:]))

        with st.spinner("Downloading, hosting on ImageBB (about 5-10 s per photo)..."):
            results, picks = run_download(
                dish_names, picks, pairs, workdir, api_key, prefix,
                progress=progress)
        bar.progress(1.0, text="Photos done.")

        with st.spinner("Building SmartBiz sheets..."):
            ready_path, pending_path = build_sheet(
                menu_path, template_path, workdir, results, prefix)
            novel = sorted(v["name"] for v in results.values()
                           if not v.get("imgbb"))
            (workdir / "novel_list.txt").write_text("\n".join(novel))
            # Persisted for diagnosis: if a run ever yields an empty sheet,
            # these files say exactly which stage failed (match vs download).
            (workdir / "picks.json").write_text(json.dumps(picks, indent=1))
            (workdir / "results.json").write_text(json.dumps(results, indent=1))

        n_ok = sum(1 for v in results.values() if v.get("imgbb"))
        if n_ok == 0:
            # Never present empty sheets as success: every photo failed,
            # which means network/ImageBB trouble, not a bad menu.
            st.error(
                "ZERO photos downloaded — the READY sheet would be empty, so "
                "it was NOT offered. This means every download/upload failed "
                "(usually a network drop or a wrong ImageBB key), NOT that "
                "your dishes lack photos. Check your internet, verify the "
                "key at https://api.imgbb.com/, and press Run again — "
                "re-runs resume cheaply and never duplicate uploads.")
            failed = [d for d in dish_names if not results.get(
                f"{prefix}-{dish_names.index(d) + 1:03d}", {}).get("imgbb")]
            st.write("Failed dishes:", failed)
            st.stop()

        st.session_state["ready_bytes"] = Path(ready_path).read_bytes()
        st.session_state["pending_bytes"] = Path(pending_path).read_bytes()
        st.session_state["novel_text"] = "\n".join(novel)
        st.session_state["summary"] = (n_ok, len(picks), len(novel))
        st.session_state["table"] = [
            {"SKU": f"{prefix}-{i + 1:03d}", "Dish": d,
             "Photo": (picks[d]["item"] if picks.get(d) else "— no photo —"),
             "Score": (picks[d].get("score", "") if picks.get(d) else ""),
             "Link": (results.get(f"{prefix}-{i + 1:03d}", {}).get("imgbb", ""))}
            for i, d in enumerate(dish_names)
        ]
        st.session_state["done"] = True
    except Exception:
        st.error("Pipeline failed:")
        st.code(traceback.format_exc()[-3000:])
        st.stop()

if st.session_state.get("done"):
    matched, total, n_novel = st.session_state["summary"]
    st.success(f"Done: **{matched}/{total}** dishes with photos, "
               f"**{n_novel}** honestly imageless.")
    fname_base = re.sub(r"[^A-Za-z0-9]+", "_", vendor).strip("_") or "vendor"
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download UPLOAD-READY sheet",
                           st.session_state["ready_bytes"],
                           file_name=f"{fname_base}_smartbiz_UPLOAD_READY.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with c2:
        if n_novel:
            st.download_button("Download NOVEL-PENDING sheet",
                               st.session_state["pending_bytes"],
                               file_name=f"{fname_base}_smartbiz_NOVEL_PENDING.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No imageless dishes — nothing pending.")
    with c3:
        if n_novel:
            st.download_button("Download novel list (.txt)",
                               st.session_state["novel_text"],
                               file_name=f"{fname_base}_novel_list.txt")
    with st.expander("Per-dish match table"):
        st.dataframe(st.session_state["table"], use_container_width=True)
    st.warning("Spot-check the photos before uploading to Amazon — a wrong photo "
               "is worse than no photo. Imageless rows are in the PENDING file: "
               "shoot real kitchen photos for those.")
    with st.expander("Per-dish match table"):
        st.dataframe(st.session_state["table"], use_container_width=True)
    st.warning("Spot-check the photos before uploading to Amazon — a wrong photo "
               "is worse than no photo. Imageless rows are in the PENDING file: "
               "shoot real kitchen photos for those.")

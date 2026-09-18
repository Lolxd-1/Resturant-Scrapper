"""
Resturant-Scrapper — Zomato dish-photo harvester + SmartBiz sheet builder.
=========================================================================
What it does (in plain words):
  1. HARVEST : downloads Zomato restaurant menu pages and pulls out every
              (dish name, dish photo) pair from the data hidden inside them.
  2. MATCH   : matches YOUR dish names (from the Gevravi Excel sheet) to the
              harvested Zomato dishes using word-based fuzzy matching.
  3. DOWNLOAD: downloads the matched photos, checks size/quality, converts
              everything to clean JPGs.
  4. UPLOAD  : hosts the JPGs on ImageBB (free image hosting) to get links.
  5. BUILD   : fills the Amazon SmartBiz bulk-upload sheet with your dishes,
              prices and the hosted image links.

Usage:
  set IMGBB_API_KEY=<your free key from https://api.imgbb.com/>
  pip install -r requirements.txt
  python zomato_scrapper.py --menu-excel "Gevravi Sheets.xlsx" ^
      --template "smartbiz_bulk_upload_template_v5.xlsx" --out ./smartbiz_out --stage all

Stages can be run separately: --stage harvest | match | download | build
(Set --stage all to run the whole pipeline.)
"""

import argparse
import base64
import csv
import json
import re
import shutil
import time
from html import unescape
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
import openpyxl

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/83.0.4103.97 Safari/537.36")}
IMGBB_URL = "https://api.imgbb.com/1/upload"

# Cuisines + cities crawled for restaurant menus.
CUISINE_TARGETS = [
    ("pune", "maharashtrian"), ("pune", "north-indian"),
    ("pune", "chinese"), ("pune", "biryani"),
    ("pune", "street-food"), ("pune", "snacks"),
    ("pune", "gujarati"), ("pune", "rajasthani"), ("pune", "thali"),
    ("mumbai", "maharashtrian"), ("mumbai", "north-indian"),
    ("mumbai", "chinese"), ("mumbai", "biryani"),
    ("mumbai", "gujarati"), ("mumbai", "mughlai"),
]

# Extra hand-picked restaurants (chaap houses, thali houses, ...).
SEED_RESTAURANTS = [
    "https://www.zomato.com/pune/the-ultimate-chaap-house-ravet",
    "https://www.zomato.com/mumbai/jk-soya-chaap-titwala-thane",
    "https://www.zomato.com/pune/shraavan-restaurant-shivaji-nagar",
    "https://www.zomato.com/mumbai/vinay-health-home-charni-road",
    "https://www.zomato.com/pune/lad-restaurant-bhosari",
    "https://www.zomato.com/pune/sps-biryani-house-since-1994-sadashiv-peth",
    "https://www.zomato.com/ballia/mirchi-restaurant-ballia-locality",
    "https://www.zomato.com/sawaimadhopur/food-circle-sawaimadhopur-locality",
]

# Dishes with no true Zomato photo (novel/rare items). They are reported in
# novel_list.txt and left imageless instead of filling a WRONG photo.
NOVEL_DISHES = {
    "Tomato Chutney", "Veg Meat (Mock Meat Masala)",
    "Soyabean Kentucky", "Gobi Roast", "Gobi Kentucky",
    "Shevga Dry (Drumstick Dry)", "Nagali Papad (Ragi Papad)",
    "Shevga Bhaji (Kala Masala Special)",
    "Baingan Bhaji (Kala Masala Special)",
    "Soyabean Bhaji (Kala Masala Special)",
}

# Manual corrections: dish -> (exact Zomato item name, restaurant slug).
# Used when the automatic matcher cannot see the answer (e.g. "Vengaya"
# is Tamil for onion, "Zunka" is dry Pitla).
MANUAL_OVERRIDES = {
    "Bhendi Bhaji (Okra Curry)": ("Bhindi do pyaaza", "altitude-all-veg-all-vibe-kitchen-bar-lower-parel"),
    "Besan Tadka (Tempered Gram Flour)": ("Zunka", "assal-amravati-mh-27-2-wakad"),
    "Soyabean Dry": ("Tandoori Soya Chaap", "salt-indian-restaurant-kalyani-nagar"),
    "Kanda Pakoda (Onion Fritters)": ("Vengaya Pakoda", "banana-leaf-1-kandivali-east"),
    "Paneer Pakoda (Paneer Fritters)": ("Cheese Pakoda", "shraavan-restaurant-shivaji-nagar"),
    "Soyabean Roast": ("Tandoori Soya Chaap", "fc-road-social-shivaji-nagar"),
    "Soya Chilli": ("Surkh Soya Chaap (6 Pcs)", "pind-balluchi-restaurant-bar-chinchwad"),
    "Roast Papad": ("Roasted Papad", "hotel-martand-1-hadapsar"),
    "Plain Pulao": ("Peas Pulao", "punjab-grill-viman-nagar"),
    "Kaju Pulao (Cashew Pulao)": ("Kashmiri Pulao", "indie-fine-dine-by-karolbaug-1-aundh"),
    "Butter Chapati": ("Butter Roti", "pind-balluchi-restaurant-bar-chinchwad"),
    "Green Peas Masala": ("Methi Matar Malai", "pind-balluchi-restaurant-bar-chinchwad"),
}

# --------------------------------------------------------------------------
# Word normaliser: maps spelling variants to one canonical token so that
# "Paneer Pulao" matches "Paneer Pulav", "Flower" matches "Gobi", etc.
# --------------------------------------------------------------------------
CANON = {}


def _group(*words):
    for w in words:
        CANON[w] = words[0]


_group("GRAVY", "masala", "curry", "rassa", "gravy")
_group("BHAJI", "bhaji", "bhajji", "sabzi", "sabji")
_group("FRIES", "chips", "fries", "finger", "wedges")
_group("PAKODA", "pakoda", "pakora", "fritter", "fritters", "vada", "bhajiya")
_group("PARATHA", "paratha", "parantha", "parota", "parotta", "kulcha")
_group("ROTI", "roti", "chapati", "chapathi", "phulka", "bhakri", "bhakar")
_group("MATAR", "matar", "peas", "vatana")
_group("GOBI", "gobi", "cauliflower", "flower", "phool")
_group("BAINGAN", "baingan", "eggplant", "vangi", "bharwa", "brinjal", "vangyache")
_group("METHI", "methi", "fenugreek")
_group("GARLIC", "lasun", "lasoon", "garlic", "lehsun")
_group("SOYA", "soya", "soyabean", "chaap", "chap")
_group("MATKI", "matki", "moth")
_group("SHEVGA", "shevga", "drumstick", "moringa", "shevgyachya", "shevgya")
_group("SHEV", "shev", "sev")
_group("KAJU", "kaju", "cashew")
_group("PITLA", "pitla", "pithla", "pithal", "zunka", "jhunka", "besan")
_group("GRAIN", "bajra", "bajari", "jowar", "jwari", "pearl", "millet",
        "sorghum", "nachni", "ragi", "nagali")
_group("PAPAD", "papad", "papadum", "papadams")
_group("CHANA", "chana", "chole", "chickpea", "chickpeas", "kabuli")
_group("DAL", "dal", "lentil", "lentils", "amti", "varan")
_group("TADKA", "tadka", "tarka", "phodni")
_group("JEERA", "jeera", "cumin", "zeera")
_group("ALOO", "aloo", "potato", "batata", "batatyachi")
_group("KHICHDI", "khichdi", "khichadi")
_group("BIRYANI", "biryani", "biriyani", "dum")
_group("PULAO", "pulao", "pulav", "pulaav")
_group("RICE", "rice", "bhaat", "bhat", "chawal")
_group("MANCHURIAN", "manchurian", "manchuria")
_group("CHILLI", "chilli", "chili", "chilly")
_group("BURJI", "bhurji", "kheema", "keema", "qheema")
_group("KADAI", "kadai", "karahi", "kadhai")
_group("PAHADI", "pahadi", "hariyali")
_group("CRISPY", "crispy", "crunchy", "kurkure")
_group("TANDOOR", "tandoor", "tandoori")
_group("TAWA", "tawa", "tava")
_group("BUTTER", "butter", "makkhan", "makhan")
_group("PALAK", "palak", "spinach", "saag")
_group("MUSHROOM", "mushroom", "mushrooms", "alambi")
_group("PANEER", "paneer")
_group("ONION", "kanda", "onion", "pyaaz", "vengaya")
_group("TOMATO", "tomato", "tamatar")
_group("BHINDI", "bhindi", "bhendi", "okra")
_group("ROAST", "roast", "roasted", "rosted")
_group("THALI", "thali")

STOP = {"special", "course", "main", "red", "lal", "shree", "kala", "veg",
        "vegetarian", "jain", "bowl", "combo", "meal", "mini", "full",
        "half", "plate", "with", "and", "spl"}

# Bonus words: if the dish name has them, a Zomato item containing them
# ranks higher (e.g. "Butter Chapati" prefers an item with "butter").
PREF = {
    "Jain Dal Fry": {"jain"},
    "Butter Chapati": {"butter", "chapati", "phulka"},
    "Butter Tandoor Roti": {"butter", "tandoor"},
    "Tandoor Roti": {"tandoor"},
    "Tawa Paratha": {"tawa"},
    "Mushroom Palak": {"palak"},
    "Paneer Kadai (Shree Special)": {"kadai"},
    "Nagali Papad (Ragi Papad)": {"ragi", "nachni"},
    "Nagali Masala Papad": {"ragi", "nachni"},
    "Bajari Bhakar (Pearl Millet Bread)": {"bajra", "bajari"},
    "Jwari Bhakar (Sorghum Bread)": {"jowar", "jwari"},
    "Roast Papad": {"roast", "roasted"},
    "Fried Papad": {"fried"},
    "Flower Masala (Cauliflower Curry)": {"gobi", "cauliflower"},
    "Shev Bhaji (Kala Masala Special)": {"kala"},
    "Kaju Curry (Kala Masala Special)": {"kala"},
    "Besan Tadka (Tempered Gram Flour)": {"besan"},
    "Bhendi Bhaji (Okra Curry)": {"bhendi", "bhindi", "okra"},
    "Tomato Chutney": {"chutney"},
    "Kanda Pakoda (Onion Fritters)": {"kanda", "pakoda", "pakora"},
    "Paneer Pakoda (Paneer Fritters)": {"pakoda", "pakora", "paneer"},
    "Matar Paneer": {"matar", "paneer"},
    "Paneer Kheema": {"kheema", "keema", "bhurji"},
    "Chana Dry (Dry Chickpeas)": {"sukha", "dry"},
    "Shevga Dry (Drumstick Dry)": {"dry"},
    "Gobi Roast": {"roast"},
    "Plain Pulao": {"plain"},
    "Kaju Pulao (Cashew Pulao)": {"kaju", "pulao"},
    "Manchurian Rice": {"rice"},
    "Soyabean Dry": {"dry"},
    "Soyabean Roast": {"roast"},
    "Baingan Masala (Eggplant Masala)": {"bharwa", "baingan"},
    "Green Peas Masala": {"peas", "matar"},
    "Mix Veg Curry": {"mix"},
    "Potato Chilli": {"potato"},
    "Soya Chilli": {"soya"},
    "Paneer Pahadi": {"pahadi"},
    "Paneer Crunchy": {"crispy"},
}

# Any Zomato item containing these words is non-veg -> never picked.
NONVEG_WORDS = [
    "chicken", "mutton", "fish", "prawn", "crab", "egg", "pomfret",
    "surmai", "bombil", "omelette", "omlette", "anda", "kolmi",
    "non-veg", "nonveg", "meat", "chicken keema", "mutton keema",
    "kheema chicken", "chicken kheema", "fish fry",
]


def toks(name):
    """Dish name -> set of canonical tokens."""
    name = re.sub(r"\([^)]*\)", " ", name.lower())
    return {CANON.get(w, w) for w in re.findall(r"[a-z]+", name)} - STOP


def is_nonveg(item_name):
    low = item_name.lower()
    return any(w in low for w in NONVEG_WORDS)


def log(*a):
    print(" ".join(str(x) for x in a), flush=True)


# --------------------------------------------------------------------------
# Stage 1 - HARVEST
# --------------------------------------------------------------------------
def fetch_text(url, cache_dir, delay=0.8):
    fn = cache_dir / (re.sub(r"[^a-z0-9]+", "_", url.lower()).strip("_")[:120] + ".html")
    if fn.exists():
        return fn.read_text(encoding="utf-8")
    r = requests.get(url, headers=UA, timeout=25)
    fn.write_text(r.text, encoding="utf-8")
    time.sleep(delay)
    return r.text


def fetch_state(url, cache_dir):
    try:
        m = re.search(r"__PRELOADED_STATE__ = JSON\.parse\((.+?)\);",
                      fetch_text(url, cache_dir))
        if not m:
            return None
        return json.loads(json.loads(unescape(m.group(1))))
    except Exception:
        return None


def order_items(page_url, cache_dir):
    """All (item name, photo url) pairs of one restaurant's order page."""
    items = []
    state = fetch_state(page_url + "/order", cache_dir)
    if not state:
        return items
    pages = state.get("pages", {})
    res_id = str(pages.get("current", {}).get("resId"))
    menus = (pages.get("restaurant", {}).get(res_id, {})
             .get("order", {}).get("menuList", {}).get("menus", []))
    for menu in menus:
        for cat in menu.get("menu", {}).get("categories", []):
            for it in cat.get("category", {}).get("items", []):
                item = it.get("item", {})
                img = item.get("item_image_url")
                if img and isinstance(img, str) and img.startswith("http"):
                    items.append({"name": item.get("name", ""),
                                  "img": img.split("?")[0]})
    time.sleep(0.8)
    return items


def harvest(out_dir, cache_dir):
    """Crawl cuisine pages -> restaurants -> menus. Saves pairs.json."""
    restaurants = []
    for city, cui in CUISINE_TARGETS:
        text = fetch_text(f"https://www.zomato.com/{city}/restaurants/{cui}",
                          cache_dir)
        for slug in dict.fromkeys(re.findall(rf"/{city}/([a-z0-9\-]{{5,}})/info", text)):
            url = f"https://www.zomato.com/{city}/{slug}"
            if url not in restaurants:
                restaurants.append(url)
    restaurants += [u for u in SEED_RESTAURANTS if u not in restaurants]
    log(f"restaurants: {len(restaurants)}")

    pairs = []
    for url in restaurants:
        slug = url.split("/")[-1]
        n = 0
        for it in order_items(url, cache_dir):
            pairs.append({"name": it["name"], "img": it["img"], "rest": slug})
            n += 1
        log(f"  {slug[:50]}: {n} imaged items")
    (out_dir / "pairs.json").write_text(json.dumps(pairs, indent=1))
    log(f"TOTAL imaged pairs: {len(pairs)}")
    return pairs


# --------------------------------------------------------------------------
# Stage 2 - MATCH
# --------------------------------------------------------------------------
def match_dishes(dishes, pairs):
    """Match your dish names to Zomato items. Returns {dish: pick|None}."""
    veg = [p for p in pairs if not is_nonveg(p["name"])]
    log(f"veg pairs: {len(veg)}/{len(pairs)}")
    picks, used = {}, {}
    for dish in dishes:
        if dish in NOVEL_DISHES:
            picks[dish] = None
            continue
        dt = toks(dish)
        need_papad = "PAPAD" in toks(dish)
        cands = []
        for p in veg:
            pt = toks(p["name"])
            if not dt or not pt:
                continue
            if need_papad and "PAPAD" not in pt:
                continue
            cov = len(dt & pt) / max(len(dt), 1)   # how much of YOUR name is covered
            if cov < 0.66:
                continue
            score = cov - 0.08 * len(pt - dt)      # penalise extra words
            for w in PREF.get(dish, set()):
                if w in p["name"].lower():
                    score += 0.3
            cands.append((score, p))
        cands.sort(key=lambda x: -x[0])
        choice = next((c for c in cands[:8] if c[1]["img"] not in used), None)
        if choice is None and cands:
            choice = cands[0]
        if choice and choice[0] >= 0.4:
            used[choice[1]["img"]] = dish
            picks[dish] = {"item": choice[1]["name"], "img": choice[1]["img"],
                           "rest": choice[1]["rest"], "score": round(choice[0], 2)}
        else:
            picks[dish] = None
    # Manual corrections win over automation.
    by_name = {}
    for p in veg:
        by_name.setdefault((p["name"], p["rest"]), p)
    for dish, (iname, rest) in MANUAL_OVERRIDES.items():
        hit = by_name.get((iname, rest))
        if hit:
            picks[dish] = {"item": hit["name"], "img": hit["img"],
                           "rest": hit["rest"], "score": 1.0, "manual": True}
    return picks


# --------------------------------------------------------------------------
# Stage 3 - DOWNLOAD + Stage 4 - UPLOAD
# --------------------------------------------------------------------------
def download_image(url, min_side=450, max_side=1600):
    r = requests.get(url, headers=UA, timeout=25)
    if r.status_code != 200 or len(r.content) < 25000:
        return None
    img = Image.open(BytesIO(r.content))
    img.load()
    if min(img.size) < 400:
        return None
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue(), img.size


def upload_imgbb(jpeg_bytes, name, api_key):
    r = requests.post(IMGBB_URL, data={"key": api_key, "name": name},
                      files={"image": ("img.jpg", jpeg_bytes, "image/jpeg")},
                      timeout=60)
    j = r.json()
    if not j.get("success"):
        raise RuntimeError(str(j)[:200])
    return j["data"].get("display_url") or j["data"].get("url")


# --------------------------------------------------------------------------
# Stage 5 - BUILD SmartBiz sheet
# --------------------------------------------------------------------------
def build_sheet(menu_excel, template, out_dir, results):
    menu_wb = openpyxl.load_workbook(menu_excel, data_only=True)
    rows = list(menu_wb.active.iter_rows(values_only=True))
    items = [{"name": str(r[0]).strip(), "desc": str(r[2] or "").strip(),
              "price": int(float(r[3] or 0))}
             for r in rows[1:] if r[0]]

    out_xlsx = out_dir / "smartbiz_UPLOAD_READY.xlsx"
    shutil.copy(template, out_xlsx)
    wb = openpyxl.load_workbook(out_xlsx)
    ws = wb["bulk_upload_template"]
    for i, it in enumerate(items, start=1):
        sku = f"GEV-{i:03d}"
        link = results.get(sku, {}).get("imgbb", "")
        if not link:                      # novel items stay out of the clean file
            continue
        r = i + 1
        ws.cell(row=r, column=3, value=sku)
        ws.cell(row=r, column=4, value=it["name"][:200])
        ws.cell(row=r, column=5, value=it["price"])
        ws.cell(row=r, column=6, value=it["price"])
        ws.cell(row=r, column=7, value="FOOD_AND_GROCERY")
        ws.cell(row=r, column=8, value="Other Food and Grocery")
        ws.cell(row=r, column=9, value=it["desc"][:2000])
        ws.cell(row=r, column=16, value=link)
    # Drop imageless rows so the file is 100% upload-ready.
    for row in range(ws.max_row, 1, -1):
        if ws.cell(row=row, column=4).value and not ws.cell(row=row, column=16).value:
            ws.delete_rows(row)
    wb.save(out_xlsx)

    pending = out_dir / "smartbiz_NOVEL_PENDING.xlsx"
    shutil.copy(template, pending)
    wb2 = openpyxl.load_workbook(pending)
    ws2 = wb2["bulk_upload_template"]
    for row in range(ws2.max_row, 1, -1):
        ws2.delete_rows(row)
    for i, it in enumerate(items, start=1):
        sku = f"GEV-{i:03d}"
        if results.get(sku, {}).get("imgbb"):
            continue
        ws2.append([None, None, sku, it["name"][:200], it["price"], it["price"],
                    "FOOD_AND_GROCERY", "Other Food and Grocery",
                    it["desc"][:2000]] + [None] * 11)
    wb2.save(pending)
    return out_xlsx, pending


def main():
    ap = argparse.ArgumentParser(description="Zomato dish-photo scrapper -> SmartBiz sheet")
    ap.add_argument("--menu-excel", required=True, help="Excel with Item Name/Category/Description/Price")
    ap.add_argument("--template", required=True, help="Amazon SmartBiz bulk upload template .xlsx")
    ap.add_argument("--out", default="./smartbiz_out", help="Output folder")
    ap.add_argument("--stage", default="all", choices=["all", "harvest", "match", "download", "build"])
    args = ap.parse_args()

    api_key = __import__("os").environ.get("IMGBB_API_KEY", "")
    if not api_key and args.stage in ("all", "download"):
        raise SystemExit("Set IMGBB_API_KEY first (free key from https://api.imgbb.com/).")

    out_dir = Path(args.out)
    (out_dir / "zimages").mkdir(parents=True, exist_ok=True)
    cache_dir = Path("./zcache")
    cache_dir.mkdir(exist_ok=True)

    menu_wb = openpyxl.load_workbook(args.menu_excel, data_only=True)
    dishes = [str(r[0]).strip()
              for r in list(menu_wb.active.iter_rows(values_only=True))[1:] if r[0]]

    if args.stage in ("all", "harvest"):
        harvest(out_dir, cache_dir)
    pairs = json.loads((out_dir / "pairs.json").read_text())

    if args.stage in ("all", "match"):
        picks = match_dishes(dishes, pairs)
        (out_dir / "picks.json").write_text(json.dumps(picks, indent=1))
        log(f"matched {sum(1 for v in picks.values() if v)}/{len(picks)}")
    picks = json.loads((out_dir / "picks.json").read_text())

    if args.stage in ("all", "download"):
        results, idx_of = {}, {d: i + 1 for i, d in enumerate(dishes)}
        for dish, pick in picks.items():
            sku = f"GEV-{idx_of[dish]:03d}"
            if not pick:
                results[sku] = {"name": dish, "imgbb": ""}
                continue
            try:
                got = download_image(pick["img"])
                if not got:
                    results[sku] = {"name": dish, **pick, "imgbb": ""}
                    continue
                jpeg, size = got
                (out_dir / "zimages" / f"{sku}.jpg").write_bytes(jpeg)
                slug = re.sub(r"[^a-z0-9]+", "-", dish.lower()).strip("-")[:45]
                link = upload_imgbb(jpeg, f"{sku}-{slug}", api_key)
                results[sku] = {"name": dish, **pick,
                                "size": f"{size[0]}x{size[1]}", "imgbb": link}
                log(sku, "OK", link)
            except Exception as e:  # noqa: BLE001 - keep going, log the miss
                log(sku, "FAIL", str(e)[:100])
                results[sku] = {"name": dish, **pick, "imgbb": ""}
            time.sleep(0.5)
        (out_dir / "results.json").write_text(json.dumps(results, indent=1))
    results = json.loads((out_dir / "results.json").read_text())

    if args.stage in ("all", "build"):
        ready, pending = build_sheet(args.menu_excel, args.template, out_dir, results)
        novel = [v["name"] for v in results.values() if not v.get("imgbb")]
        (out_dir / "novel_list.txt").write_text("\n".join(sorted(novel)))
        log(f"READY: {ready} | PENDING: {pending} | NOVEL: {len(novel)}")


if __name__ == "__main__":
    main()

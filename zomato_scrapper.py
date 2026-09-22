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
# Default covers cafe/fast-food vendors (pizza, burger, sandwich, momos,
# pasta, shakes, ...). For a VERY different vendor (e.g. Maharashtrian
# thali-only), extend this list with that cuisine and re-run harvest —
# the cuisine page slug is whatever appears in zomato.com/{city}/restaurants/{slug}.
CUISINE_TARGETS = [
    ("pune", "pizza"), ("pune", "cafe"),
    ("pune", "fast-food"), ("pune", "burger"),
    ("pune", "sandwich"), ("pune", "beverages"),
    ("pune", "desserts"), ("pune", "bakery"),
    ("pune", "chinese"), ("pune", "momos"),
    ("pune", "pasta"), ("pune", "italian"),
    ("pune", "coffee"), ("pune", "juices"),
    ("pune", "ice-cream"), ("pune", "north-indian"),
    ("pune", "street-food"), ("pune", "snacks"),
    ("mumbai", "pizza"), ("mumbai", "cafe"),
    ("mumbai", "fast-food"), ("mumbai", "burger"),
    ("mumbai", "sandwich"), ("mumbai", "beverages"),
    ("mumbai", "italian"), ("mumbai", "chinese"),
    ("mumbai", "desserts"), ("mumbai", "bakery"),
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

# Delivery-chain outlets — REQUIRED, not optional.
# Why: Zomato's dine-in listing pages (/{city}/restaurants/{cuisine}) never
# list delivery chains (Domino's, La Pino'z, Wow Momo, ...), yet chain-style
# dishes (Paneer N Corn Pizza, Cheese Momos) live almost exclusively there.
# This exact gap silently lost 20/101 H-FOOD dishes before these seeds existed.
# Their /order pages expose the same __PRELOADED_STATE__ menu JSON with
# 90%+ photo coverage. Every URL below was verified working (HTTP 200 +
# parseable menu + imaged items); do not add guessed slugs — a wrong slug
# just logs "0 imaged items", but verify anyway. Re-verify if Zomato
# restructures URLs.
CHAIN_SEEDS = [
    "https://www.zomato.com/pune/la-pinoz-pizza-kothrud",
    "https://www.zomato.com/pune/la-pinoz-pizza-baner",
    "https://www.zomato.com/pune/la-pinoz-pizza-wakad",
    "https://www.zomato.com/pune/dominos-pizza-baner",
    "https://www.zomato.com/pune/dominos-pizza-kothrud",
    "https://www.zomato.com/mumbai/dominos-pizza-andheri-west",
    "https://www.zomato.com/pune/pizza-hut-hinjawadi",
    "https://www.zomato.com/pune/pizza-hut-baner",
    "https://www.zomato.com/pune/oven-story-pizza-wakad",
    "https://www.zomato.com/pune/mojo-pizza-baner",
    "https://www.zomato.com/pune/wow-momo-kothrud",
    "https://www.zomato.com/pune/mcdonalds-baner",
    "https://www.zomato.com/pune/kfc-baner",
]

# Dishes with no true Zomato photo (novel/rare items). They are reported in
# novel_list.txt and left imageless instead of filling a WRONG photo.
# Starts EMPTY for every new vendor: the matcher reports true misses
# automatically, and diagnose_misses() tells you whether each miss is a
# pool gap (add CHAIN_SEEDS) or a matcher gap (fix toks/STOP/CANON).
# Only add a dish here AFTER eye-check proves its auto-pick is
# category-wrong and no better candidate exists in the pool. Past examples
# (H-FOOD CAFE run, do NOT copy blindly): "Makhani Cheese Momos" (pool only
# had makhani steak), "Fresh Garlic Dough Balls" (only veg balls in garlic),
# "Ceet-M Mastani" (signature item; auto-pick was a McD shake+fries combo
# matched via its "(M)" size tag — this case also motivated dropping
# 1-letter tokens in toks()).
NOVEL_DISHES = set()

# Manual corrections: dish -> (exact Zomato item name, restaurant slug).
# Starts EMPTY for every new vendor. Add entries ONLY after eye-check catches
# a flavor-wrong pick the scorer cannot distinguish (same tokens, wrong item).
# You MUST verify the target exists in pairs.json with a big file first —
# check with: python -c "import json; p=json.load(open('pairs.json')); ..."
# Past examples (H-FOOD CAFE run, do NOT copy blindly):
#   "Virgin Mojito": ("Virgin Mojito", "hotel-rajbhog-pure-veg-wanowrie"),
#   "Veg Burger": ("Classic Veg Burger", "chai-cult-cafe-hinjawadi"),
MANUAL_OVERRIDES = {}

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
# H-FOOD CAFE cooking/texture variants.
_group("STEAM", "steam", "steamed")
_group("FRY", "fried", "fry")
_group("GRILL", "grilled", "grill")
_group("SHAKE", "shake", "shakes", "thickshake",
        # Mastani is Pune's thick-shake-plus-ice-cream served in the same tall
        # glass — visually a shake. Lets "Strawberry Mastani" match a real
        # strawberry shake instead of going imageless. Signature mastanis
        # with no flavour twin (Ceet-B/Ceet-M) still fall out as novel.
        "mastani")
_group("CHAI", "chai", "tea", "chay")
_group("MOMOS", "momos", "momo")
_group("COFFEE", "coffee", "coldbrew")
_group("NOODLES", "noodles", "hakka")

STOP = {"special", "course", "main", "red", "lal", "shree", "kala", "veg",
        "vegetarian", "jain", "bowl", "combo", "meal", "mini", "full",
        "half", "plate", "with", "and", "spl",
        # H-FOOD CAFE sizes — "Cheese Pizza - Small/Medium/Large" must all
        # match the same "Cheese Pizza" photo.
        "small", "medium", "large", "regular", "personal", "family",
        "classic", "combos", "style", "fresh",
        # H-FOOD flavour/origin fillers — chai is chai, brownie is brownie.
        "sizzling", "irani", "indori", "tulsi", "adrak",
        # peri-peri is a flavour dust; momos/pizza photo stays correct without it.
        "peri",
        # "N" means "and" in dish names ("Paneer N Corn", "Fish N Chips").
        # As a token it silently vetoed true matches (coverage 3/4 -> fail).
        "n"}

# Bonus words: if the dish name has them, a Zomato item containing them
# ranks higher (e.g. "Butter Chapati" prefers an item with "butter").
# H-FOOD: Schezwan pizzas must prefer PIZZA photos over Schezwan Dry.
PREF = {
    "Paneer Schezwan Pizza - Medium": {"pizza"},
    "Paneer Schezwan Pizza - Large": {"pizza"},
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


def _singular(w):
    """Strip a trailing plural 's' (corns->corn, jalapenos->jalapeno).

    Generic so future menus never need a new CANON group per word.
    Runs AFTER canon lookup (so grouped words like chips/fries/momos are
    already canonical and untouched) and only on lowercase tokens, so
    canonical UPPERCASE tokens are never mangled. 'ss' endings
    (glass, class) are left alone.
    """
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and w.islower():
        return w[:-1]
    return w


def toks(name):
    """Dish name -> set of canonical tokens."""
    # Keep parenthetical words: "Irani Maska (Bun Maska)" needs bun+maska.
    name = re.sub(r"[()]", " ", name.lower())
    out = {_singular(CANON.get(w, w)) for w in re.findall(r"[a-z]+", name)}
    # Drop 1-letter tokens: they are size codes ("M", "L"), initials, or
    # split junk — never real dish words. Without this, "Ceet-M" matched a
    # McDonald's combo via its "(M)" size tag.
    out = {t for t in out if len(t) > 1}
    return out - STOP


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
    restaurants += [u for u in CHAIN_SEEDS if u not in restaurants]
    log(f"restaurants: {len(restaurants)}")

    pairs = []
    zero_menu = []
    for url in restaurants:
        slug = url.split("/")[-1]
        n = 0
        for it in order_items(url, cache_dir):
            pairs.append({"name": it["name"], "img": it["img"], "rest": slug})
            n += 1
        log(f"  {slug[:50]}: {n} imaged items")
        if n == 0:
            # 0 can mean closed outlet, bot-wall, or an unparseable page
            # (e.g. review text breaking the JSON extractor). Not fatal while
            # the pool is big, but chain seeds must never all read 0 —
            # if they do, the pool silently loses whole dish families.
            zero_menu.append(slug)
    (out_dir / "pairs.json").write_text(json.dumps(pairs, indent=1))
    log(f"TOTAL imaged pairs: {len(pairs)}")
    if zero_menu:
        log(f"WARN {len(zero_menu)} restaurants gave 0 items: {zero_menu[:12]}")
    return pairs


# --------------------------------------------------------------------------
# Stage 2 - MATCH
# --------------------------------------------------------------------------
def rank_candidates(dish, veg):
    """All (score, pair) for one dish, best first. Shared by match + download.

    Centralising the ranking here (instead of a copy in the downloader) is
    what makes download-fallback safe: the fallback tries the SAME ordering
    the matcher used, so it can never surface a photo the matcher rejected.
    """
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
    return cands


def base_of(d):
    # "Cheese Pizza - Small" -> "cheese pizza" so size variants share one photo.
    return re.sub(r"\s*-\s*(small|medium|large)\s*$", "",
                  d, flags=re.I).strip().lower()


def match_dishes(dishes, pairs):
    """Match your dish names to Zomato items. Returns {dish: pick|None}."""
    veg = [p for p in pairs if not is_nonveg(p["name"])]
    log(f"veg pairs: {len(veg)}/{len(pairs)}")

    picks, used = {}, {}
    for dish in dishes:
        if dish in NOVEL_DISHES:
            picks[dish] = None
            continue
        cands = rank_candidates(dish, veg)
        base = base_of(dish)
        # Size variants (Small/Medium/Large) may share one photo; different
        # dishes never share.
        choice = next((c for c in cands[:8]
                       if c[1]["img"] not in used or used.get(c[1]["img"]) == base), None)
        if choice is None and cands:
            choice = cands[0]
        if choice and choice[0] >= 0.4:
            used[choice[1]["img"]] = base
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
def build_sheet(menu_excel, template, out_dir, results, sku_prefix="SKU"):
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
        sku = f"{sku_prefix}-{i:03d}"
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
    # Only scan the filled block (rows 2..1+len(items)) — never ws.max_row
    # (49000 validation rows; deleting those takes forever).
    for row in range(len(items) + 1, 1, -1):
        if ws.cell(row=row, column=4).value and not ws.cell(row=row, column=16).value:
            ws.delete_rows(row)
    wb.save(out_xlsx)

    pending = out_dir / "smartbiz_NOVEL_PENDING.xlsx"
    shutil.copy(template, pending)
    wb2 = openpyxl.load_workbook(pending)
    ws2 = wb2["bulk_upload_template"]
    # Write novel rows directly at the top (rows 2..); leftover template
    # validation rows stay empty and are ignored by Amazon. No mass deletes.
    pr = 2
    for i, it in enumerate(items, start=1):
        sku = f"{sku_prefix}-{i:03d}"
        if results.get(sku, {}).get("imgbb"):
            continue
        ws2.cell(row=pr, column=3, value=sku)
        ws2.cell(row=pr, column=4, value=it["name"][:200])
        ws2.cell(row=pr, column=5, value=it["price"])
        ws2.cell(row=pr, column=6, value=it["price"])
        ws2.cell(row=pr, column=7, value="FOOD_AND_GROCERY")
        ws2.cell(row=pr, column=8, value="Other Food and Grocery")
        ws2.cell(row=pr, column=9, value=it["desc"][:2000])
        pr += 1
    wb2.save(pending)
    return out_xlsx, pending


def diagnose_misses(dishes, pairs, picks):
    """Future-proof diagnostic: for every unmatched dish, report near-misses.

    The Paneer-N-Corn outage was silent — match just said "78/101" with no
    hint whether the pool lacked the dish or the matcher rejected it.
    - Zero near-misses (pool items covering >=50% of the dish name):
      the POOL lacks the dish family -> add CHAIN_SEEDS for that cuisine.
    - Near-misses exist but score < 0.4 / coverage < 0.66:
      the MATCHER rejects true photos -> fix toks/STOP/CANON (plurals,
      "N"=and, origin words) instead of adding restaurants.
    """
    veg = [p for p in pairs if not is_nonveg(p["name"])]
    for dish in dishes:
        if picks.get(dish):
            continue
        if dish in NOVEL_DISHES:
            log(f"  NOVEL-banned: {dish}")
            continue
        dt = toks(dish)
        near = []
        for p in veg:
            pt = toks(p["name"])
            if not dt or not pt:
                continue
            cov = len(dt & pt) / max(len(dt), 1)
            if cov >= 0.5:
                score = cov - 0.08 * len(pt - dt)
                near.append((score, p))
        near.sort(key=lambda x: -x[0])
        if not near:
            log(f"  POOL-GAP (no pool item covers half the name): {dish} toks={sorted(dt)}")
        else:
            top = "; ".join(f"{s:.2f} {q['name'][:45]}" for s, q in near[:3])
            log(f"  MATCHER-GAP (pool has candidates, all rejected): {dish} toks={sorted(dt)} :: {top}")


def main():
    ap = argparse.ArgumentParser(description="Zomato dish-photo scrapper -> SmartBiz sheet")
    ap.add_argument("--menu-excel", required=True, help="Excel with Item Name/Category/Description/Price")
    ap.add_argument("--template", required=True, help="Amazon SmartBiz bulk upload template .xlsx")
    ap.add_argument("--out", default="./smartbiz_out", help="Output folder")
    ap.add_argument("--stage", default="all", choices=["all", "harvest", "match", "download", "build"])
    ap.add_argument("--sku-prefix", default="SKU",
                    help="SKU prefix per vendor, e.g. HFC gives HFC-001. "
                         "Use 2-4 uppercase letters of the vendor name.")
    args = ap.parse_args()

    sku_prefix = re.sub(r"[^A-Za-z0-9]", "", args.sku_prefix).upper()[:6] or "SKU"

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
    if args.stage == "harvest":
        log("HARVEST done.")
        return
    pairs = json.loads((out_dir / "pairs.json").read_text())

    if args.stage in ("all", "match"):
        picks = match_dishes(dishes, pairs)
        (out_dir / "picks.json").write_text(json.dumps(picks, indent=1))
        log(f"matched {sum(1 for v in picks.values() if v)}/{len(picks)}")
        diagnose_misses(dishes, pairs, picks)
    if args.stage == "match":
        log("MATCH done.")
        return
    picks = json.loads((out_dir / "picks.json").read_text())

    if args.stage in ("all", "download"):
        prev = {}
        _rf = out_dir / "results.json"
        if _rf.exists():
            try:
                prev = json.loads(_rf.read_text())
            except Exception:
                prev = {}
        results, picks = run_download(dishes, picks, pairs, out_dir, api_key,
                                      sku_prefix, prev)
        (out_dir / "results.json").write_text(json.dumps(results, indent=1))
        (out_dir / "picks.json").write_text(json.dumps(picks, indent=1))
def run_download(dishes, picks, pairs, out_dir, api_key, sku_prefix="SKU",
                 prev=None, progress=None):
    """Download + ImageBB-upload every matched pick. Shared by CLI and app.

    - Idempotent: previous uploads whose pick didn't change are KEPT.
    - Fallback: a top pick that fails the quality gate is retried with the
      next matcher-approved candidates (same ranking as match).
    - progress(done, total, msg): optional callback for UIs (Streamlit).
      Returns (results, picks); picks may be updated by fallback/applied
      manual overrides, so callers must persist both.
    """
    out_dir = Path(out_dir)
    (out_dir / "zimages").mkdir(parents=True, exist_ok=True)
    results, idx_of = {}, {d: i + 1 for i, d in enumerate(dishes)}
    prev = prev or {}
    imgbb_cache = {}  # zomato img url -> (imgbb link, "WxH")
    veg = [p for p in pairs if not is_nonveg(p["name"])]
    dl_failed = set()  # zomato imgs that failed the quality gate this run
    total = len(picks)
    for n, (dish, pick) in enumerate(picks.items(), start=1):
        sku = f"{sku_prefix}-{idx_of[dish]:03d}"
        if not pick:
            results[sku] = {"name": dish, "imgbb": ""}
            if progress:
                progress(n, total, f"{sku} novel — no photo")
            continue
        old = prev.get(sku, {})
        if old.get("imgbb") and old.get("img") == pick["img"]:
            results[sku] = old
            if old.get("size"):
                imgbb_cache.setdefault(pick["img"], (old["imgbb"], old["size"]))
            log(sku, "KEEP", old["imgbb"])
            if progress:
                progress(n, total, f"{sku} kept")
            continue
        # Skip re-downloading a pick that already failed this run or in a
        # previous run (recorded as dl_fail) — go straight to fallback.
        tried = {pick["img"]} if old.get("dl_fail") and old.get("img") == pick["img"] else set()
        tried |= {i for i in dl_failed}
        done = False
        try:
            cands = [(pick["score"] if pick.get("score") else 1.0,
                      {"name": pick["item"], "img": pick["img"],
                       "rest": pick["rest"]})]
            # Fallback: SAME ranking the matcher used, so we only ever
            # try photos the matcher approved (score >= 0.4).
            for score, p in rank_candidates(dish, veg)[:12]:
                if score < 0.4:
                    break
                entry = (score, {"name": p["name"], "img": p["img"],
                                 "rest": p["rest"]})
                if entry not in cands:
                    cands.append(entry)
            for score, cand in cands:
                if cand["img"] in tried or cand["img"] in dl_failed:
                    continue
                if cand["img"] in imgbb_cache:
                    link, sizestr = imgbb_cache[cand["img"]]
                    results[sku] = {"name": dish, "item": cand["name"],
                                    "img": cand["img"], "rest": cand["rest"],
                                    "score": round(score, 2),
                                    "size": sizestr, "imgbb": link,
                                    "shared": True}
                    picks[dish] = {"item": cand["name"], "img": cand["img"],
                                   "rest": cand["rest"],
                                   "score": round(score, 2)}
                    log(sku, "OK-shared", link)
                    done = True
                    break
                got = download_image(cand["img"])
                if not got:
                    tried.add(cand["img"])
                    dl_failed.add(cand["img"])
                    log(sku, "reject-small", cand["name"][:40], f"{score:.2f}")
                    continue
                jpeg, size = got
                (out_dir / "zimages" / f"{sku}.jpg").write_bytes(jpeg)
                slug = re.sub(r"[^a-z0-9]+", "-", dish.lower()).strip("-")[:45]
                link = upload_imgbb(jpeg, f"{sku}-{slug}", api_key)
                sizestr = f"{size[0]}x{size[1]}"
                imgbb_cache[cand["img"]] = (link, sizestr)
                results[sku] = {"name": dish, "item": cand["name"],
                                "img": cand["img"], "rest": cand["rest"],
                                "score": round(score, 2),
                                "size": sizestr, "imgbb": link}
                picks[dish] = {"item": cand["name"], "img": cand["img"],
                               "rest": cand["rest"], "score": round(score, 2)}
                log(sku, "OK" if cand["img"] == pick["img"] else "OK-fallback",
                    link)
                done = True
                break
            if not done:
                results[sku] = {"name": dish, **pick, "imgbb": "",
                                "dl_fail": True}
                log(sku, "FAIL-all-candidates", dish)
        except Exception as e:  # noqa: BLE001 - keep going, log the miss
            log(sku, "FAIL", str(e)[:100])
            results[sku] = {"name": dish, **pick, "imgbb": ""}
        if progress:
            progress(n, total, f"{sku} {'done' if done else 'no photo'}")
        time.sleep(0.5)
    return results, picks


    if args.stage == "download":
        log("DOWNLOAD done.")
        return
    results = json.loads((out_dir / "results.json").read_text())

    if args.stage in ("all", "build"):
        ready, pending = build_sheet(args.menu_excel, args.template, out_dir,
                                     results, sku_prefix)
        novel = [v["name"] for v in results.values() if not v.get("imgbb")]
        (out_dir / "novel_list.txt").write_text("\n".join(sorted(novel)))
        log(f"READY: {ready} | PENDING: {pending} | NOVEL: {len(novel)}")


if __name__ == "__main__":
    main()

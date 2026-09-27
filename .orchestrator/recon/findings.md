# Recon findings (orchestrator, verified by running code / live probes on 2026-09-27)

## Existing code (prodv1.0 + local edits, commit 040e68b)
- `zomato_scrapper.py` (799 lines): harvest -> match -> download -> upload -> build. `app.py` (Streamlit UI). `RUN_ME.bat` (needs Python preinstalled).
- Pool: `data/pairs.json` = 12,317 {name,img,rest} from 143 restaurants, Pune/Mumbai only. No category, no diet, no description kept.
- Matching = bag-of-words with coverage >= 0.66 and score >= 0.4; STOP words drop discriminative words (peri, tulsi, adrak, dum, indori, irani, classic...). Coverage 0.66 lets the distinguishing word drop.

## Root causes of wrong photos (seen in smartbiz_out_hfood / smartbiz_out_shiraj_biryani_house)
1. Zomato menu CATEGORY discarded: "Dum Murgh (Dum Chicken)" -> item "Peri Peri Chicken" which is a PIZZA (category Pizzas @ toss-pizzeria). Image verified: a pizza.
2. Distinguishing flavour word allowed to drop: "Pineapple Thick Shake" -> "Vanilla Thick Shake" (white shake); "Strawberry Virgin Mojito" -> "Virgin Mojito"; "Paneer Schezwan Pizza" -> "Paneer pizza"; "Makhani Cheese Maggi" -> "Vegetable Cheese Maggi".
3. Branded chain photos reused for other vendors: "Cheese Momos" -> Wow!Momo box with logo (and not cheese momos).
4. Wrong item semantics: "Boiled Egg Fry" -> "Fried Eggs" (sunny side up); "Roast Murgh" -> "Roasted Harissa Chicken".
5. Diet by word list (NONVEG_WORDS) although every Zomato item has `dietary_slugs` in {veg, non-veg, egg} (verified on 20,459 items: veg 13,837 / non-veg 6,232 / egg 390).
6. CANON groups too loose: bharwa->BAINGAN (breaks "Bharwa Bhindi"), besan->PITLA (breaks "Besan Ladoo"), kulcha->PARATHA, bhakri->ROTI, vada->PAKODA, chaap->SOYA chunks.

## "It breaks sometimes" causes (verified)
- `novel_list.txt` written with default encoding (cp1252 on these PCs) -> UnicodeEncodeError for ₹/Devanagari/emoji at the END of a run, after all uploads (app.py line 177, zomato_scrapper.py line 689). Verified: `Path.write_text('₹')` fails with locale cp1252.
- `__PRELOADED_STATE__` regex `(.+?)\);` is non-greedy to the first `);` -> silently fails on some pages (Burger King Hadapsar: old 184/185, robust string-literal regex 185/185).
- app.py `validate_menu` rejects the whole menu when any price is blank (Ganesh menu has blank prices for Shrikhand/Lassi/Aamras) and requires exact column positions.
- `build_sheet` `int(float(r[3]))` crashes on "₹120", "120/-".
- picks/results keyed by dish NAME: duplicate dish names collide (second row overwritten; `dish_names.index(d)` wrong SKU).
- Streamlit runs the 10-30 min pipeline inside the page script: a browser refresh or sleep kills the run; no resume.
- RUN_ME.bat requires the user to install Python manually; Microsoft Store python stub not handled.
- Category bug: `build_sheet` hardcodes column H = "Other Food and Grocery" -> SmartBiz app shows one category. Template column H "Product Category" is FREE TEXT, max 100 chars, mandatory (instructions sheet). Column G Business Category dropdown = FOOD_AND_GROCERY.

## SmartBiz template facts (data/smartbiz_template.xlsx)
- Sheets: important_instructions (visible), bulk_upload_template (48,999 rows of validation), DataSheet (hidden). Do not add/move sheets or edit headers.
- Columns (1-based): C=3 Custom SKU (<=40), D=4 Product Name (<=200), E=5 MRP (number >0), F=6 Selling Price (<= MRP), G=7 Business Category, H=8 Product Category (free text <=100), I=9 Description (<=2000), J=10 Variant Relationship, K=11 Size, N=14 Best Seller, P=16 Product Image1 ... U=21 Image6.
- Allowed image hosts include imgbb.com, ibb.co, iili.io (freeimage.host), imgur.com, postimg.cc.

## Zomato live facts (probed 2026-09-27 from this PC, plain requests + desktop Chrome UA: all 200)
- Restaurant menu: `https://www.zomato.com/<city>/<slug>/order` HTML (~1.2 MB) with `window.__PRELOADED_STATE__ = JSON.parse("<js string literal>")`.
  Robust extraction: regex `__PRELOADED_STATE__\s*=\s*JSON\.parse\(("(?:[^"\\]|\\.)*")\)` (re.S), then `json.loads(json.loads(group1))`.
  Path: state.pages.current.resId -> state.pages.restaurant[resId] -> .order.menuList.menus[].menu{name, categories[].category{name, items[].item{id,name,desc,dietary_slugs,item_image_url,media}}}.
  Restaurant info: state.pages.restaurant[resId].sections.SECTION_BASIC_INFO{name, cuisine_string, is_perm_closed, resUrl}.
  item_image_url has no query string = original upload. CDN resize params work: `?fit=around%7C300%3A300&crop=300%3A300%3B%2A%2C%2A`.
- Cuisine listing: `https://www.zomato.com/<city>/restaurants/<cuisine-slug>` -> ~9 restaurants (links `/<city>/<slug>/info`), no SSR pagination (`?page=2` returns the same 9).
- autoSuggest JSON: `GET https://www.zomato.com/webroutes/search/autoSuggest?addressId=0&entityId=<cityId>&entityType=city&q=<text>&context=delivery`
  -> {"results":[{entityType:"restaurant", info:{name}, actionInfo:{clickUrl:"/pune/la-pinoz-pizza-fc-road"}}, {entityType:"chain_outlets", actionInfo:{clickUrl:"/index.php?entity_type=city&entity_id=5&city=5&chain=10506"}}, {entityType:"universal_dish", entityId:"67961", ...}]}.
  Mostly returns restaurants whose NAME contains the query (specialists: "Thick Shake Town", "Misal House", "Khichdi Bar"); universal_dish is rare.
- Chain listing: the chain clickUrl redirects to `/<city>/restaurants/<chain-slug>` whose SECTION_SEARCH_RESULT cards have cardAction.clickUrl `/<city>/<outlet-slug>/info`.
  Path: state.pages.search[<any key>].sections.SECTION_SEARCH_RESULT[] -> {info:{resId,name}, cardAction:{clickUrl}} (some entries lack `info`: skip them).
- Dish page (only when a universal_dish id is known): `/<city>/delivery?dishv2_id=<id>&category=1` -> SECTION_SEARCH_RESULT restaurants with `/order` clickUrls.
- `?q=` on /delivery or /restaurants is ignored server-side (generic results) -> do NOT use.
- City slug -> autoSuggest cityId table: .orchestrator/recon/cities.json (Delhi NCR slug is "ncr"; thiruvananthapuram 404; kolhapur has 0 listing restaurants).

## Vision (fastembed, ONNX, no torch) measured on the 92 sample photos
- Qdrant/clip-ViT-B-32 (vision 336 MB + text 245 MB), 50-60 ms/img CPU.
- Fine-grained name zero-shot: top1 0.27 / top3 0.55 over 86 menu names -> NOT usable as a fine verifier.
- Coarse dish-type zero-shot (31 types): top1 0.72; misses mostly inside look-alike groups (shake/cold coffee/ice cream; sandwich/garlic bread; tea/coffee). It did flag the real disaster (Dum Murgh image -> "pizza").
- => Use vision only as: (a) margin-based veto across dish GROUPS, (b) non-food/logo/text rejection, (c) image-image consensus among same-dish candidates, (d) tie-break. Never as the primary matcher.
- fastembed default cache is %TEMP% (can be wiped) -> must pass cache_dir to a persistent runtime folder.

## Past vendor runs (This/Resturant-Scrapper/New Ganesh*, H FOOD CAfe/out) needed hand-written scripts for:
Taak/Mattha -> Buttermilk/Chaas, Shira -> Sheera, Aamras -> mango pulp, Sabudana Khichdi, blank prices, reuse across vendors.

## Tooling on this PC
Python 3.12.6 (system, many extra packages: do not rely on them), node, git 2.47, gh (logged in as Lolxd-1), Edge for headless screenshots.
Remote: https://github.com/Lolxd-1/Resturant-Scrapper (default main; branches main, prodv1.0). Working branch: prodv2.0.

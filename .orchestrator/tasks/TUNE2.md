# TUNE2: Chain/own-menu coverage (all outlets, exact product names, dish type from the vendor's category)
Wave: 14 · Deps: TUNE1 · Risk: high · Model: opus

## Goal
When a vendor is a chain (or its own Zomato page is known), every product that exists on ANY of that brand's outlets gets that brand's own photo, including products whose name has no dish word ("Garden Special", "Hawaiian Special") and product names that look like combos ("Non Veg Pack Of 4").

## Context (live eval 2026-09-27, La Pino'z menu of 35 real La Pino'z products: only 26 found)
- Detection worked ("Vendor found on Zomato as chain: La Pino'z Pizza (4 outlets)"), but only the 4 fetched outlets were used; the pool already holds more La Pino'z outlets (Baner, Kothrud, ...) whose menus contain the missing products.
- "Garden Special", "Cheesy Margherita(personal Giant Slice)", "Hawaiian Special Personal Giant Slice", "Onion Twist Personal Giant Slice" sit in categories like "Pizzas"/"Personal Giant Slices" but have no head word; the item side derives PIZZA from its category, the dish side does not -> head gate rejects.
- "Non Veg Pack Of 4", "Chicken 65 & Sweet Corn Taco's" are single products whose names trip the combo rules.

## Read first
- `studio/pipeline.py` (source stage: suggest/chain_outlets/own; `same_dish_menu_match` usage; vendor_key)
- `studio/matcher.py` (same_dish_menu_match, score head gate), `studio/text.py` (parse_dish head, item_head, CATEGORY_HEAD_HINTS usage)
- `tests/test_pipeline.py`, `tests/test_matcher.py`, `tests/test_text.py`

## Write-set
- modify: studio/pipeline.py
- modify: studio/matcher.py
- modify: studio/text.py
- test: tests/test_pipeline.py
- test: tests/test_matcher.py
- test: tests/test_text.py

## Steps
1. text.py `parse_dish(name, category, description)`: when the name yields no head, set head from the dish's own category using the SAME category->head logic as `item_head` (item_head(name="", category=category)). Name head always wins. Add test_text cases: parse_dish("Garden Special", "Pizzas").head == "PIZZA"; parse_dish("Garlic Bread", "Pizza").head == "GARLICBREAD"; parse_dish("Farmhouse", "Beverages").head is None.
2. matcher.py `same_dish_menu_match(q, items, idf)`: FIRST check exact product-name equality: `_name_key(s)` = normalize(s) with size/portion suffixes removed (reuse size_base_key) and whitespace collapsed; an item whose _name_key equals the dish's _name_key -> return Candidate(tier "exact", text 1.0, source set by caller) regardless of combo/head gates, BUT still enforce the diet gate (veg dish never takes a non-veg item). Then the existing exact/strong logic, then the fuzzy >= 92 fallback.
3. pipeline.py source stage: after detection, the chain source items = fetched outlet menus UNION all pool items whose chain_key equals the detected chain's chain_key (use the store/index; cap at 25 outlets, most items first). Apply the same union for "own" when the vendor url's restaurant chain_key has other outlets in the pool (a single-outlet vendor stays single). Log "Using <n> outlets of <brand>".
4. Keep every existing test passing.

## Test cases
- TC1 (pipeline): pool holds a chain outlet A (in store) whose menu contains "Garden Special" under category "Pizzas"; suggest returns the chain with outlets B, C (fetched, without that product) -> the dish "Garden Special" (menu category "Pizzas") gets source "chain" and A's image.
- TC2 (matcher): same_dish_menu_match("Non Veg Pack Of 4", items=[PoolItem "Non Veg Pack Of 4", diet nonveg]) -> exact; and a veg dish named "Veg Pack Of 4" never matches a nonveg item of the same name.
- TC3 (matcher): "Cheesy Margherita(personal Giant Slice)" matches the item "Cheesy Margherita (Personal Giant Slice)" exactly.
- TC4 (text): the three parse_dish cases in step 1.
- TC5 (regression): all golden cases in tests/test_matcher.py still pass (general pool matching unchanged except via the dish-category head).

## Verify
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_text.py tests/test_matcher.py tests/test_pipeline.py tests/test_pipeline_cli.py
.venv/Scripts/python -m compileall -q studio
```

## Done when
- [ ] every test case above passes via Verify

## Out of scope
- `_combine_scores` and its TODO(human) (user-owned); vision; OCR.

## Notes

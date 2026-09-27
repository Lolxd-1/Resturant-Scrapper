# TUNE2 report

## Implemented
- text.py `parse_dish`: `head=item_head(name, category)`, so the name head wins and the dish's own category is the fallback (the same logic items use).
- matcher.py `same_dish_menu_match`: an exact product-name check comes first (`size_base_key(item.name) == q.base_key`, where base_key is already size_base_key of the dish name, i.e. normalized, sizes stripped, whitespace collapsed). It returns Candidate tier "exact", text 1.0, reason "same product name", skipping the combo/head gates but keeping `_diet_ok`. It is skipped when base_key is empty. I also added `_diet_ok` to the existing fuzzy >= 92 fallback, which ignored diet before (TC2 needs it: "Veg Pack Of 4" veg dish vs nonveg item otherwise matched via fuzzy).
- pipeline.py `source()`: after detection, items = fetched/own items UNION every pool item whose chain_key is in {chain_key(n) for n in outlet names}, grouped per outlet, deduped by item_id, sorted by item count descending, capped at MAX_SOURCE_OUTLETS=25. Logs "Using <n> outlets of <brand>". This covers chain (suggest or pool-derived) and own. A single-outlet own vendor stays single because no other pool outlet has its chain_key.

## Files
studio/text.py, studio/matcher.py, studio/pipeline.py, tests/test_text.py, tests/test_matcher.py, tests/test_pipeline.py

## Tests
- test_pipeline::test_tune2_tc1_chain_uses_pool_outlets_of_same_brand: a pool outlet A (PizzaCo) has "Garden Special" in "Pizzas", and suggest-fetched B and C lack it. The result has source chain with A's image, plus the log "Using 3 outlets of PizzaCo".
- test_matcher::test_tune2_tc2_...: "Non Veg Pack Of 4" matches exact with text 1.0, and a veg "Veg Pack Of 4" returns None against a nonveg item of the same name.
- test_matcher::test_tune2_tc3_...: "Cheesy Margherita(personal Giant Slice)" matches "Cheesy Margherita (Personal Giant Slice)" exact.
- test_text::test_tune2_tc4_dish_head_from_own_category: the three parse_dish cases.

## Verify
orch.sh verify TUNE2 exits 0 (141 passed; compileall clean). The first run failed only on TC2's veg case because of the fuzzy fallback's missing diet gate. After that fix it passed.

## Concerns
- Exact-name matching goes through size_base_key, so "Cheese Pizza - Small" exactly matches an item "Cheese Pizza - Large" (same product, different size). This is intended by the brief's "size/portion suffixes removed".
- parse_dish's head now comes from the category for every caller, including general pool scoring. The golden tests all pass, but live behaviour for headless names in categorized menus changes.
- Brand key set = chain keys of all detected outlet names. If a suggest-fetched outlet has an odd name, its key also pulls in same-named pool outlets.

## Discoveries
- DishQuery.base_key == size_base_key(name) is already the normalized, size-stripped name key; there was no need for a separate _name_key helper.

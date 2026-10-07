# PLAN: Menu photo -> SmartBiz sheet with 95% photo coverage
run: photo-to-sheet · branch: orch/photo-to-sheet · base: 34439a20083ef3a368a36ade389a5f6682c0907a · created: 2026-10-07T12:25:05Z

## Requirement (verbatim)
> the first problem, if we put in a sheet it won't find the products. that I have put int, in this there are many products. that are like common but not getting filled. you get it? it should be properly done and try to find the best images for it. [...] Make it to a level where, if I Have one Image it is giving me the final excel sheet. where at least 95% are getting generated extremely accurately.

User rulings (2026-10-07, AskUserQuestion):
- AI = Google Gemini API **free tier** (no Claude API). Also deliver a copy-paste prompt for the Gemini website (Pro) whose Excel output the app accepts. ("Both")
- Look-alike photos are NOT auto-published: they wait in a **Review** list in the web app where the user approves the suggested name/photo, or edits the search name, searches again and picks a photo.
- Same app (RUN_ME.bat + web page).

## Goal
One or more menu photos (or a menu Excel) produce SmartBiz sheets in which >= 95% of dishes have a correct photo, either automatically (exact dish) or after one-click approval of a look-alike.

## Non-goals
- AI image generation (not on the Gemini free tier).
- Rotating several Gemini keys/projects to dodge free-tier quotas (ToS risk). One key, several free models.
- Changing the SmartBiz template or ImgBB hosting.

## Acceptance criteria
- AC1 (rules): "Tandoori Chicken" in category "Tandoori Kebabs" matches pool item "Tandoori Chicken" whose category is "Chicken Kebab"; "Mango Mocktail" (category "Menu Item") matches "Mango Mocktail" (menu "Mocktails").
- AC2 (Excel columns): a menu Excel with optional "Diet" and "Photo Names" columns is read into MenuRow.diet / MenuRow.photo_names; files without them behave exactly as before.
- AC3 (Swiggy): for dishes not confidently found in the pool, the job searches Swiggy dish search and can pick a Swiggy photo (source "swiggy"); thumbnails and full photos download from media-assets.swiggy.com.
- AC4 (look-alikes): a dish with no exact photo gets a photo for its first look-alike name that matches (from "Photo Names", Gemini, or the built-in ladder), status "review", local photo saved, NOT uploaded, NOT in UPLOAD_READY until approved.
- AC5 (review UI): the job page has a Review filter; a dish sheet offers Approve, a search box (prefilled) that returns up to 8 candidate photos from pool + Swiggy, and "Use this photo"; "Approve all look-alikes" approves every review dish; sheets rebuild afterwards.
- AC6 (Gemini client): with a saved Gemini key the app calls generateContent (REST, header x-goog-api-key), falls back across free models on quota errors, caches responses on disk, never logs the key; without a key every AI step is skipped and the app works as in AC1-AC5.
- AC7 (photo reader): uploading 1-6 menu photos in the web app (or `--menu-image` on the CLI) produces a preview table and a downloadable menu_extract.xlsx with Item Name, Category, Description, Price, Diet, Photo Names; size/price variants become separate rows "Name (Half)".
- AC8 (manual prompt): the New-job page shows a copyable Gemini-website prompt whose output columns are accepted by AC2.
- AC9 (enrich): for an Excel without Diet/Photo Names, one Gemini call per <= 120 rows fills diet, photo names and missing descriptions.
- AC10 (AI judge): candidate photos are checked by Gemini in batches (<= 25 dishes per call); "same" + clean -> ready, "similar" -> review, "different" or text/logo/watermark -> rejected.
- AC11 (outcome): on the eval set (Vithai photo, Food Junction, pending menus of Hotel Shubham/Shreee/City Hotel/Pizza by Ghiza/Shetkari Raja), >= 95% of dishes end ready-or-correct-review, and <= 2% of READY photos are wrong (orchestrator visual audit).

## Assumptions
- A1: Gemini free tier, 3.8 Flash ~20 req/day; other Flash models have their own quotas · default: model chain gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash, gemini-3.5-flash, gemini-2.5-flash · asked user: yes (free tier)
- A2: Swiggy dish search (`/dapi/restaurants/search/v3`, selectedPLTab=DISH) stays reachable without login · probed 2026-10-07 OK · asked: no
- A3: Swiggy isVeg==1 means veg; absent means non-veg · from probes · asked: no

## Context map
- `studio/pipeline.py` — job engine; stages read/source/match/search/verify/photos/upload/build; `_Group`, `_settle`, `_confident`, `choose_alternate`.
- `studio/matcher.py` — PoolIndex retrieval + precision-first `score()`/`rank()`.
- `studio/text.py` — `parse_dish`, tokens, roles, heads, diet.  `studio/lexicon.py` — vocabulary data.
- `studio/menu.py` — Excel/CSV reader (`read_menu`, header role detection).
- `studio/models.py` — shared dataclasses (contracts).  `studio/store.py` — SQLite pool.
- `studio/imaging.py` — thumb/full download + validation (Zomato-only URLs today).
- `studio/zomato.py` — Http (throttle/retry) + Zomato client.  `studio/sheets.py` — SmartBiz + report output.
- `studio/server.py` + `studio/web/app.js` — FastAPI + vanilla JS UI.  `zomato_scrapper.py` — CLI.
Flow: read_menu -> parse_dish per row -> groups -> source (vendor own menu) -> match (pool rank) -> search (Zomato live) -> verify (CLIP + gates, pick) -> photos (download + OCR brand guard) -> upload (ImgBB) -> settle -> sheets.
Reuse: `Http.get_ex` (zomato.py:142) for all HTTP; `PoolStore.upsert_menu` pattern; `imaging.fetch_thumb_ex/fetch_full_ex`; `rank()`; `choose_alternate()`; tests' `Env`/`FakeSession`/`make_xlsx`.

## Decisions
- D1: Gemini via REST with `requests` (no new dependency; requirements.txt is a locked installer list). — rejected: google-genai SDK (new heavy dep, API churn: interactions vs generateContent).
- D2: Look-alike ladder = rung 0 dish name, then "Photo Names" (Excel/Gemini), else built-in `lookalike_names()`. Rung-0 behaviour is unchanged (precision kept); rungs >= 1 only produce "review" dishes.
- D3: New status "review" + DishResult.lookalike/approved flags; review dishes go to the PENDING sheet until approved; a user's explicit pick ("Use this photo") counts as approval.
- D4: Swiggy before Zomato live crawl (1 request returns 60-200 dishes with photos).
- D5: Gemini judge (milestone B) only reorders/vetoes candidates the deterministic matcher already found; it never invents matches.

## Global constraints
- Conventions: match existing style (dataclasses, `log = logging.getLogger("studio.<mod>")`, plain functions, no new abstractions); user-facing messages in plain English.
- Forbidden: new dependencies; edits outside write-sets; weakening tests; logging API keys.
- Platform: Windows, Python 3.12, pytest 8. Tests must stay offline (FakeSession).

## Verify (global)
```bash
MENUSTUDIO_HOME=.testhome C:/Users/omkar/Downloads/Resturant-Scrapper-prodv2.111/Resturant-Scrapper-prodv2.1/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests
C:/Users/omkar/Downloads/Resturant-Scrapper-prodv2.111/Resturant-Scrapper-prodv2.1/.venv/Scripts/python.exe -m compileall -q studio app.py zomato_scrapper.py tools
```

## Contracts
```text
studio/models.py (A2):
  MenuRow: + diet: str = ""                       # "veg" | "nonveg" | "egg" | ""  (after `warnings`)
           + photo_names: list[str] = field(default_factory=list)
studio/models.py (A4):
  STATUSES = ("ready", "review", "needs_photo", "needs_price", "error")
  SOURCES  = ("own", "chain", "pool", "live", "swiggy", "")
  Candidate: + rung: int = 0                      # 0 = dish name; >= 1 = look-alike name index
  DishResult: + diet: str = ""; + photo_names: list[str] = field(default_factory=list)
              + search_name: str = ""             # name whose photo was used / last searched
              + lookalike: bool = False; + approved: bool = False
studio/menu.py (A2): parse_diet(value: object) -> str ; parse_photo_names(value: object) -> list[str]
studio/text.py (A4): lookalike_names(name: str) -> list[str]
studio/swiggy.py (A3):
  SWIGGY_CITIES: dict[str, tuple[str, str]]       # city slug -> (lat, lng)
  IMG_BASE = "https://media-assets.swiggy.com/swiggy/image/upload/"
  parse_dish_search(data: dict, city: str) -> list[RestaurantMenu]
  class SwiggyBlocked(Exception)
  class SwiggyClient: __init__(self, http: Http) ; search_dishes(self, query: str, city: str) -> list[RestaurantMenu]
studio/store.py (A3): PoolStore.add_items(self, menu: RestaurantMenu) -> int   # merge-insert, never deletes
studio/imaging.py (A3): thumb_url(url: str) -> str ; full_url(url: str) -> str
studio/pipeline.py (A5): Engine(store, vision, http, swiggy: SwiggyClient | None = None)
                         search_photos(engine, job_dir, sku, query) -> DishResult
                         approve_dishes(engine, job_dir, skus, uploader) -> list[DishResult]
studio/server.py (A6): POST /api/jobs/{id}/dishes/{sku}/search {"query"} ; POST /api/jobs/{id}/approve {"skus": [...]}
milestone B contracts are added to this file before B tasks are briefed.
```

## Risks
| R | Scenario | Mitigation | Covering test (task) |
|---|---|---|---|
| R1 | Look-alike photo auto-published as if exact | rung >= 1 -> lookalike=True -> status review, upload skipped | test_lookalike_goes_to_review_not_uploaded (A5) |
| R2 | Rule fix lets a wrong dish through (category head) | allow only when item head == query head | test_category_head_compat_* (A1) |
| R3 | Swiggy blocks / changes JSON | SwiggyBlocked -> skip Swiggy for the job + warning; parser tolerant (KeyError -> skip card) | test_swiggy_blocked_* , test_parse_skips_bad_cards (A3, A5) |
| R4 | Swiggy URLs get Zomato thumb suffix | host-aware thumb_url/full_url used everywhere | test_thumb_url_* (A3), test_swiggy_photo_downloaded (A5) |
| R5 | merge-insert duplicates Swiggy items forever | add_items skips (res_url, img_url) already present | test_add_items_dedup (A3) |
| R6 | Old results.json / sheets break with new fields | dish_result_from_dict ignores unknown, defaults fill new | test_old_results_load (A4) |
| R7 | Diet column typo silently mis-filters | parse_diet returns "" for unknown values (no override) | test_parse_diet_* (A2) |
| R8 | Approve while job running | 409 like choose | test_approve_conflict_when_active (A6) |
| R9 | Gemini key leaks into logs/URLs | header auth only; tests assert key absent from logged text | (B1) |

## Test matrix
| AC or R | Test (file :: name) | Task |
|---|---|---|
| AC1 | tests/test_matcher.py :: test_category_head_compat_tandoori_chicken, test_mocktail_is_mojito_head | A1 |
| AC2 | tests/test_menu.py :: test_diet_and_photo_names_columns, test_parse_diet_values, test_parse_photo_names_split | A2 |
| AC3 | tests/test_swiggy.py :: test_parse_dish_search_fixture, test_search_dishes_request; tests/test_pipeline.py :: test_swiggy_photo_used_when_pool_misses | A3, A5 |
| AC4 | tests/test_text.py :: test_lookalike_names_*; tests/test_pipeline.py :: test_lookalike_goes_to_review_not_uploaded | A4, A5 |
| AC5 | tests/test_pipeline.py :: test_approve_dishes_*, test_search_photos_*; tests/test_server.py :: test_approve_endpoint, test_search_endpoint | A5, A6 |
| R6 | tests/test_sheets.py :: test_review_rows_go_to_pending | A4 |

## Task DAG (milestone A — no AI)
| ID | Title | Deps | Wave | Write-set | Risk | Model |
|---|---|---|---|---|---|---|
| A1 | Matcher rule fixes | - | 1 | studio/matcher.py, studio/lexicon.py, tests/test_matcher.py | med | sonnet |
| A2 | Diet + Photo Names menu columns | - | 1 | studio/models.py, studio/menu.py, tests/test_menu.py | low | sonnet |
| A3 | Swiggy client + merge-insert + host-aware image URLs | - | 1 | studio/swiggy.py, studio/store.py, studio/imaging.py, tests/test_swiggy.py, tests/test_store.py, tests/test_imaging.py | med | sonnet |
| A4 | Look-alike names + review status in models/sheets | A2 | 2 | studio/models.py, studio/text.py, studio/sheets.py, tests/test_text.py, tests/test_sheets.py | med | sonnet |
| A5 | Pipeline: rungs, Swiggy search, review settle, search/approve helpers | A1 A3 A4 | 3 | studio/pipeline.py, studio/server.py(Engine wiring only), zomato_scrapper.py, tools/eval_menus.py, tests/test_pipeline.py | high | opus |
| A6 | Review UI + endpoints | A5 | 4 | studio/server.py, studio/web/app.js, studio/web/app.css, tests/test_server.py | med | sonnet |

## Rollback
`git revert` the task commits on orch/photo-to-sheet; main is untouched.

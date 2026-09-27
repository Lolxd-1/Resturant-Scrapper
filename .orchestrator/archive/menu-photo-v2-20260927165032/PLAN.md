# PLAN: Menu Studio v2 — accurate Zomato dish photos -> upload-ready SmartBiz sheets
run: menu-photo-v2 · branch: prodv2.0 · base: 040e68b3b25564e4dd754713de6810fe6b770bed · created: 2026-09-27T06:49:44Z

## Requirement (verbatim, condensed quotes of the user's message)
> the main issue with this scrapper of zomato is, it has many incorrect images. it has many false positives as well. and ... images that are like super common, won't be listed there.
> make sure that every single Excel sheet gets the stuff Done. Like with extremely rare names that aren't there. and with accuracy. extremely rare names that are like Local Based. that we can tell the restaurant owner to get photos of it.
> make a proper plan, that will make sure that 95-98% or more than that products are being fetched with almost 95% accuracy ... it works sometimes, it breaks sometimes, there are not edge case scenarios ... "This is the final product I have confidence, no matter what category of a shop that i am putting in, it just works. and gives me the final uploadable excel sheet that has no human intervention."
> also, the UI is shit ... Make the UI better. Like Legit Really good. Apple Design.
> 2. the final excel sheet doesn't have any category except one category named "Other" ... refer to the input excel ... it has all the proper categories. so the final excel sheet should be like that.
> 3. it breaks many times as well.
> 4. famous Food chains ... search if it's a famous chain or not. if it is then see their outlets on zomato. and get me the exact ... images for that specific products ... if not then it should be searching the Images from the restaurants.
> 5. Do not limit yourself in terms of what region ... Complete Zomato's database (relevant one ...) so it doesn't fail on basic images.
> Make this production grade and then push this to the github.
> ... some team member downloads it and then runs this run.me .bat ... even on the pc for the first time, that doesn't have python, node or whatever ... it should install them properly first. and then simply run this.
> in the settings you have to put in IMAGEBB API KEY ... saved there. in that folder ... 3-4 diff [keys] ... fallback mechanisms ... once saved it shouldn't be asking for another.
> Try it Test it see all the possible ways it can fail ... design tests for it.

## Goal
A Windows one-click local app that turns any vendor's menu Excel into an upload-ready SmartBiz sheet with a correct Zomato photo for every dish that exists on Zomato (chain/own-restaurant photos first, then the best consensus photo from any Indian city), the menu's own categories, and an owner-photo list for truly local dishes — with no crashes and no manual steps.

## Who uses it
Non-technical team members onboarding restaurants onto a SmartBiz storefront. They double-click RUN_ME.bat, upload the vendor's menu Excel, wait, download the sheet, upload it to SmartBiz. They never edit code. A wrong photo on a live storefront is worse than no photo.

## Non-goals
- Streamlit Community Cloud hosting (the app is local-PC only now; Streamlit is removed).
- SmartBiz Parent/Child size variants (size variants stay separate rows sharing one photo).
- Paid vision/LLM APIs; non-Zomato image sources (Swiggy, Google).
- macOS/Linux one-click launchers (the Python app itself stays portable; `python app.py` works anywhere).
- Editing/cropping photos (watermark removal etc.).
- freeimage.host fallback (its public key returns "Internal upload error" code 111 on every upload method, verified 2026-09-27).

## Acceptance criteria
- AC1 Categories: every UPLOAD_READY row has column H (Product Category) = that row's menu Category, cleaned (trimmed, whitespace collapsed, ALL-CAPS/all-lower -> Title Case, max 100 chars). A blank Category inherits the nearest non-blank Category above it; a menu with no category column gets a category inferred from the dish type (e.g. "Pizza", "Beverages", "Main Course") and "Menu" only when nothing is inferable. "Other Food and Grocery" never appears in column H.
- AC2 Menu reading: header row found anywhere in the first 15 rows; columns matched by name in any order (name/item/dish/product; category/section/type; description/desc/details; price/rate/mrp/amount/cost); prices like `120`, `120.0`, `"₹120"`, `"Rs. 120/-"`, `"120.50"`, `"100/180"` (first number) parse; blank/zero/unparseable price -> row kept with status `needs_price` (never blocks the run); blank rows skipped; category-header rows (name filled, price and description blank, and next rows have prices) become the current category; duplicate dish names get distinct SKUs; `.xlsx`/`.xlsm`/`.csv` accepted; `.xls` gives the error "Please save the file as .xlsx (Excel Workbook) and upload again."
- AC3 Unicode: dish names/categories/descriptions with ₹, Devanagari, accents and emoji flow through every output file and results.json without error; every text file is written UTF-8.
- AC4 Precision: the matcher rejects every NEGATIVE pair and accepts every POSITIVE pair in tests/test_matcher.py::GOLDEN (at least 30 of each, including all failures listed in .orchestrator/recon/findings.md "Root causes").
- AC5 Chain / own restaurant: when the vendor name resolves on Zomato to a chain (chain_outlets entity or >= 2 outlets with the same normalized name) or to its own restaurant (user-supplied Zomato URL, or a single same-name restaurant in the chosen city), dishes found on that menu use that menu's own photo with source "chain"/"own"; other dishes fall through to the general search.
- AC6 Whole-Zomato search: dishes without a confident pool match trigger live discovery across multiple cities (vendor city first, then DEFAULT_SEARCH_CITIES), via cuisine listings and autoSuggest specialists, within `live_budget_menus`; every fetched menu is stored in the pool and reused by later jobs.
- AC7 Resilience: HTTP 429/5xx/timeouts retried with backoff; a blocked/unparseable page is skipped with a log line; one dish's failure never aborts a job; a job interrupted mid-run resumes from its job dir without re-uploading finished dishes; the server never runs the pipeline inside a request.
- AC8 ImgBB keys: Settings stores any number of labelled keys in `config/settings.json` (app folder, git-ignored) and never asks again once saved; uploads rotate keys; "Invalid API v1 key" disables that key for the rest of the job; rate-limit/5xx cools that key down and moves to the next; identical image bytes are never uploaded twice (sha256 cache in the pool DB); "Test key" in Settings verifies a key with a real 60-second-expiry upload.
- AC9 Sheets: UPLOAD_READY contains exactly the rows with status `ready` (photo hosted AND price > 0), written contiguously from row 2 with C=SKU, D=name[:200], E=price, F=price, G=FOOD_AND_GROCERY, H=category[:100], I=description[:2000], P=photo URL; all template sheets, headers and validations are otherwise untouched. PENDING (same template) holds every other row (needs_photo / needs_price / error) with whatever is known (photo URL for needs_price rows). REPORT.xlsx has sheets "Summary", "Dishes" (one line per menu row with status, reason, confidence, tier, source, Zomato item, restaurant, photo link) and "Owner photo checklist".
- AC10 Vision: the CLIP model loads from `<home>/models`; if it cannot load (offline first run, disk error) the job still runs text-only with only exact/strong tiers accepted, and the UI and REPORT show "Visual check unavailable".
- AC11 UI: a single-page app at http://127.0.0.1:<port>/ with New Job (drop zone, vendor, city, optional Zomato link, menu preview grouped by category with warnings), live progress over SSE (stages, per-dish results streaming in, counts, cancel), Results (summary, downloads, category-grouped photo grid with confidence/source, swap to an alternate photo or mark "needs owner photo", rebuilds sheets), Settings (keys add/test/remove/enable, strictness, live search, budget, city), History (past jobs, reopen, resume). Visual quality: Apple-style (system font stack, large titles, frosted panels, 12–20 px radii, soft shadows, light+dark mode, smooth transitions); verified by headless-Edge screenshots at 1440x900 and 390x844.
- AC12 Launcher: on a PC without Python, double-clicking RUN_ME.bat installs a private Python 3.12 + venv via uv into `%LOCALAPPDATA%\MenuStudio` (no admin), installs locked deps only when requirements.txt changed, starts the app on a free port and opens the browser; double-clicking again while it runs just opens the browser; errors print a plain-English fix and pause. Batch files are CRLF in git (.gitattributes).
- AC13 Accuracy (live, orchestrator-audited): on the eval menus (H-Food 101, Gevravi 81, Ganesh 65, Shivraj 18, plus one chain menu), photo precision >= 95% by visual audit and coverage >= 90% overall; every uncovered dish appears in the owner checklist with a reason.
- AC14 CLI: `python zomato_scrapper.py --menu-excel M.xlsx --vendor "Name" [--city pune] [--zomato-url URL] [--out DIR] [--no-upload]` runs the same pipeline headless and prints the output paths.
- AC15 README explains the 3-step team flow, Settings, outputs, troubleshooting.

## Assumptions (rulings, not asked: user said "Get it done")
- A1: Streamlit is replaced by FastAPI + a hand-written SPA · default: yes (Apple-grade UI needs full control; also fixes refresh-kills-run).
- A2: The vision model (~580 MB, one-time) is acceptable · default: CLIP ViT-B/32 via fastembed, downloaded on first run to `<home>/models`.
- A3: Push target: new branch `prodv2.0` on origin (repo convention: one branch per prod version); PR to main is the user's call.
- A4: Runtime files (Python, venv, models, pool DB) live in `%LOCALAPPDATA%\MenuStudio`; settings and job outputs live in the app folder (`config/`, `outputs/`) as the user asked.
- A5: Coverage target is reported honestly: dishes that do not exist on Zomato (e.g. "Ceet-B Mastani") go to the owner checklist; they are not force-matched.

## Context map
- `zomato_scrapper.py` — v1 pipeline (to be replaced by a CLI shim over `studio/`).
- `app.py` — v1 Streamlit UI (to be replaced by the server entry point).
- `RUN_ME.bat` — v1 launcher (rewritten).
- `data/smartbiz_template.xlsx` — SmartBiz template (keep). `data/pairs.json` — v1 pool (input to the seed builder; removed from runtime).
- `zcache/*.html` — 213 cached Zomato pages (git-ignored; seed builder input).
Flow v2: menu.read_menu -> text.parse_dish -> pipeline(source detection: own/chain) -> matcher.PoolIndex.rank -> live discovery (zomato.ZomatoClient) -> vision verification -> imaging.fetch_full -> hosting.Uploader -> sheets.build_outputs -> server/UI events.
Reuse: robust state regex and item path (findings.md); city table .orchestrator/recon/cities.json; template column map (findings.md).
Recon notes: .orchestrator/recon/findings.md

## Decisions
- D1: Package `studio/` (config, models, menu, lexicon, text, zomato, store, matcher, imaging, vision, hosting, sheets, pipeline, server, web/) — why: testable units with frozen contracts — rejected: patching the 800-line script (untestable, keyed by names).
- D2: Precision-first tiers (exact/strong/close/reject) with hard gates (diet from Zomato `dietary_slugs`, protein, dish head incl. the item's menu category, combo, key-token) — why: every observed wrong photo breaks one of these gates — rejected: coverage threshold tuning.
- D3: Vision is a verifier, never the matcher (margin-based group veto, non-food/logo check, image-image consensus, tie-break) — why: measured CLIP fine-grained top1 0.27, coarse 0.72.
- D4: SQLite pool at `<home>/pool.sqlite`, seeded from shipped `data/seed_pool.jsonl.gz` (built by tools/build_seed_pool.py across ~20 cities x ~45 cuisines), grows with every live fetch; menus older than 30 days may be re-fetched.
- D5: Source order per dish: own/chain menu -> pool -> live discovery (budgeted) -> owner checklist.
- D6: FastAPI + uvicorn + vanilla JS/CSS SPA (no build step, no CDN, works offline), SSE for progress, one background job worker.
- D7: Launcher = RUN_ME.bat -> scripts/setup.ps1 using uv (downloaded from GitHub releases) to get Python 3.12 without admin; fallback to an existing Python 3.10-3.13 (ignoring the WindowsApps store stub).
- D8: Sequential execution only (no parallel worktree waves) — why: Windows symlinked .venv in worktrees is unreliable; tasks share hot files (studio/models.py) — cost if wrong: longer wall clock only.

## Global constraints
- Conventions: Python 3.10+ syntax, type hints on public functions, `from __future__ import annotations` at the top of every studio module, dataclasses from `studio/models.py` only (never redefine), `logging.getLogger("studio.<module>")` for logs (no print in library code), every file write `encoding="utf-8"`, paths via `pathlib.Path`, no global mutable state except module-level constants and caches guarded by locks.
- Network code accepts an injectable `Http` (studio/zomato.py) or `http_post` callable so tests never touch the network.
- Tests: pytest, offline, deterministic, no sleeps (inject `sleep`), files under `tests/`, fixtures generated in code or stored under `tests/fixtures/`.
- Forbidden: new dependencies beyond requirements.txt / requirements-dev.txt from T01; edits outside write-sets; printing or logging API keys (log only the key label and last 4 chars).
- Platform: Windows 10/11 primary, Python 3.12 runtime (3.10-3.13 supported), paths may contain spaces and live in OneDrive.

## Verify (global)
```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider tests
.venv/Scripts/python -m compileall -q studio app.py zomato_scrapper.py tools
```

## Contracts
```text
# ---- studio/models.py (T01; verbatim code is in .orchestrator/tasks/T01.md) ----
ImgbbKey(label: str, key: str, enabled: bool = True)
Settings(imgbb_keys: list[ImgbbKey] = [], strictness: str = "balanced", live_search: bool = True,
         live_budget_menus: int = 250, default_city: str = "")
MenuRow(row: int, excel_row: int, name: str, category: str, description: str, price: float | None, warnings: list[str])
MenuParseResult(rows: list[MenuRow], sheet_name: str, header_row: int, columns: dict[str, int], warnings: list[str], errors: list[str])
DishQuery(raw: str, display: str, base_key: str, variants: tuple[frozenset[str], ...], head: str | None,
          diet: str, proteins: frozenset[str], is_combo: bool, category: str = "", description: str = "")
PoolItem(item_id: int, name: str, category: str, menu_name: str, description: str, diet: str, img_url: str,
         res_id: str, res_name: str, res_url: str, city: str, chain_key: str)
RestaurantMenu(res_id: str, name: str, url: str, city: str, cuisines: str, items: list[PoolItem])
MatchScore(tier: str, text: float, reasons: tuple[str, ...])          # tier in TIERS
Candidate(item: PoolItem, score: MatchScore, vision: float | None = None, consensus: float | None = None,
          type_ok: bool | None = None, food_ok: bool | None = None, final: float = 0.0, source: str = "pool")
DishResult(row, sku, name, category, description, price, status, reason, tier, confidence, source, item_name,
           restaurant, restaurant_url, zomato_img, local_image, image_size, hosted_url, alternates)   # see T01
TIERS = ("exact", "strong", "close", "reject")
DIETS = ("veg", "egg", "nonveg", "unknown")
STATUSES = ("ready", "needs_photo", "needs_price", "error")
SOURCES = ("own", "chain", "pool", "live", "")
dish_result_to_dict(r: DishResult) -> dict ; dish_result_from_dict(d: dict) -> DishResult

# ---- studio/config.py (T01) ----
APP_DIR: Path   (repo root) ; DATA_DIR = APP_DIR/"data" ; CONFIG_PATH = APP_DIR/"config"/"settings.json"
OUTPUT_DIR = APP_DIR/"outputs" ; TEMPLATE_PATH = DATA_DIR/"smartbiz_template.xlsx" ; SEED_POOL_PATH = DATA_DIR/"seed_pool.jsonl.gz"
home_dir() -> Path          # $MENUSTUDIO_HOME, else %LOCALAPPDATA%\MenuStudio, else ~/.menustudio ; created
pool_db_path() -> Path      # home_dir()/"pool.sqlite"
models_dir() -> Path        # home_dir()/"models" ; created
load_settings(path: Path | None = None) -> Settings     # missing/corrupt file -> Settings() (corrupt file renamed *.bad)
save_settings(settings: Settings, path: Path | None = None) -> None   # atomic (tmp + os.replace), utf-8, indent 2

# ---- studio/menu.py (T02) ----
read_menu(path: Path) -> MenuParseResult
parse_price(value: object) -> float | None
clean_category(text: str) -> str
derive_sku_prefix(vendor: str) -> str      # "H-Food Cafe"->"HFC", "Domino's"->"DOM", ""->"SKU", max 6 chars A-Z0-9

# ---- studio/lexicon.py + studio/text.py (T03) ----
normalize(text: str) -> str                 # ascii-folded lowercase, '&'->' and ', punctuation->space, single spaces
tokens(text: str) -> list[str]              # canonical tokens, order kept, deduped
parse_dish(name: str, category: str = "", description: str = "") -> DishQuery
item_head(name: str, category: str = "", menu_name: str = "") -> str | None
item_proteins(name: str) -> frozenset[str]
size_base_key(name: str) -> str
is_combo_name(name: str) -> bool
HEAD_GROUP: dict[str, str] ; HEAD_PROMPT: dict[str, str] ; HEAD_CUISINES: dict[str, tuple[str, ...]]
NON_VISUAL: frozenset[str] ; NOISE: frozenset[str]

# ---- studio/zomato.py (T04) ----
CITIES: dict[str, int] ; DEFAULT_SEARCH_CITIES: tuple[str, ...] ; CUISINE_SLUGS: tuple[str, ...]
class ZomatoBlocked(Exception)
class Http: __init__(self, session=None, min_interval: float = 0.6, max_retries: int = 4, timeout: float = 25.0, sleep=time.sleep)
           get(self, url: str, params: dict | None = None) -> requests.Response | None     # None on 404 / exhausted retries
class ZomatoClient: __init__(self, http: Http)
    fetch_menu(self, res_url: str) -> RestaurantMenu | None
    suggest(self, query: str, city: str) -> SuggestResult
    listing(self, city: str, cuisine: str) -> list[str]
    chain_outlets(self, chain_url: str) -> list[str]
SuggestResult(restaurants: list[tuple[str, str]], chains: list[str], dishes: list[tuple[str, str]])   # (name, res_url) ; chain urls ; (dish_id, name)
parse_state(html: str) -> dict | None ; parse_menu(state: dict, fallback_url: str = "") -> RestaurantMenu | None
canonical_res_url(url: str) -> str ; city_of(res_url: str) -> str ; chain_key(name: str) -> str

# ---- studio/store.py (T05) ----
class PoolStore: __init__(self, path: Path)
    ensure_seeded(self, seed_path: Path) -> int ; upsert_menu(self, menu: RestaurantMenu) -> int
    menu_fetched_at(self, res_url: str) -> float | None ; all_items(self) -> list[PoolItem]
    items_for_restaurant(self, res_url: str) -> list[PoolItem] ; count_items(self) -> int ; count_restaurants(self) -> int
    get_upload(self, sha256: str) -> str | None ; put_upload(self, sha256: str, url: str, host: str) -> None
    get_embedding(self, key: str) -> numpy.ndarray | None ; put_embedding(self, key: str, vec: numpy.ndarray) -> None
    mark_bad_image(self, img_url: str, reason: str) -> None ; is_bad_image(self, img_url: str) -> bool
seed line (JSONL, gzip): {"r": res_url, "rn": res_name, "c": city, "n": name, "cat": category, "m": menu_name, "d": description[:300], "dt": diet, "i": img_url}

# ---- studio/matcher.py (T06) ----
class PoolIndex: __init__(self, items: Iterable[PoolItem] = ()) ; add(self, items) -> None ; idf(self, token: str) -> float
                 retrieve(self, q: DishQuery, limit: int = 600) -> list[PoolItem] ; __len__
score(q: DishQuery, item: PoolItem, idf: Callable[[str], float]) -> MatchScore
rank(q: DishQuery, items: Iterable[PoolItem], idf: Callable[[str], float]) -> list[Candidate]   # tier != reject, best first
same_dish_menu_match(q: DishQuery, items: Iterable[PoolItem], idf) -> Candidate | None          # strict (exact/strong) for own/chain menus

# ---- studio/imaging.py + studio/vision.py (T07) ----
THUMB_SUFFIX = "?fit=around%7C300%3A300&crop=300%3A300%3B%2A%2C%2A"
fetch_thumb(url: str, http: Http) -> bytes | None
fetch_full(url: str, http: Http, min_side: int = 400, max_side: int = 1600) -> tuple[bytes, tuple[int, int]] | None
MODEL_IMAGE = "Qdrant/clip-ViT-B-32-vision" ; MODEL_TEXT = "Qdrant/clip-ViT-B-32-text"
class Vision(Protocol): available: bool ; reason: str ; embed_images(self, images: list[bytes]) -> np.ndarray ; embed_texts(self, texts: list[str]) -> np.ndarray
class ClipVision ; class NullVision ; load_vision(cache_dir: Path, allow_download: bool = True) -> Vision
food_ok(vision: Vision, img_vecs: np.ndarray) -> np.ndarray[bool]
head_ok(vision: Vision, img_vecs: np.ndarray, head: str | None) -> np.ndarray[bool]
consensus(img_vecs: np.ndarray, weights: np.ndarray) -> np.ndarray[float]
text_sim(vision: Vision, img_vecs: np.ndarray, text: str) -> np.ndarray[float]

# ---- studio/hosting.py (T08) ----
class UploadError(Exception)
class Uploader: __init__(self, keys: list[ImgbbKey], *, http_post=requests.post, store: PoolStore | None = None, sleep=time.sleep)
    upload(self, jpeg: bytes, name: str) -> str ; key_states(self) -> list[dict]   # {"label","tail","state":"ok"|"cooldown"|"disabled","last_error"}
test_key(key: str, *, http_post=requests.post) -> tuple[bool, str]
IMGBB_URL = "https://api.imgbb.com/1/upload"

# ---- studio/sheets.py (T09) ----
build_outputs(results: list[DishResult], template: Path, out_dir: Path, vendor: str, *, vision_on: bool = True) -> dict[str, Path]  # keys "ready","pending","report"
safe_vendor(vendor: str) -> str
file names: f"{safe_vendor}_SmartBiz_UPLOAD_READY.xlsx", f"{safe_vendor}_SmartBiz_PENDING.xlsx", f"{safe_vendor}_Photo_Report.xlsx"

# ---- studio/pipeline.py (T10) ----
JobOptions(vendor: str, city: str = "", zomato_url: str = "", sku_prefix: str = "", upload: bool = True,
           strictness: str = "balanced", live_search: bool = True, live_budget_menus: int = 250)
class Engine: __init__(self, store: PoolStore, vision: Vision, http: Http) ; index: PoolIndex ; client: ZomatoClient
run_job(engine: Engine, menu_path: Path, job_dir: Path, opts: JobOptions, *, uploader: Uploader | None,
        on_event: Callable[[dict], None] | None = None, cancel: threading.Event | None = None) -> dict   # summary
choose_alternate(engine: Engine, job_dir: Path, sku: str, alt_index: int | None, uploader: Uploader | None) -> DishResult
job dir: job.json, menu.<ext>, results.json, log.txt, images/<SKU>.jpg, 3 output xlsx
events: {"type":"stage","stage":id,"label":str,"progress":float} | {"type":"dish","result":dict} | {"type":"log","message":str}
        | {"type":"done","summary":dict} | {"type":"error","message":str}
stage ids: read, source, match, search, verify, photos, upload, build
summary: {"total","ready","needs_photo","needs_price","errors","coverage","vision","duration_s","files":{"ready","pending","report"},"warnings":[]}

# ---- studio/server.py (T11) ----
create_app(engine_factory=None, output_dir: Path = OUTPUT_DIR, config_path: Path = CONFIG_PATH) -> FastAPI
GET /api/system ; GET/PUT /api/settings ; POST /api/settings/test-key {"key"} ; POST /api/menu/preview (multipart "file")
POST /api/jobs {"upload_id","vendor","city","zomato_url","sku_prefix"} ; GET /api/jobs ; GET /api/jobs/{id}
GET /api/jobs/{id}/events (SSE) ; POST /api/jobs/{id}/cancel ; POST /api/jobs/{id}/resume
POST /api/jobs/{id}/dishes/{sku}/choose {"alt_index": int|null} ; GET /api/jobs/{id}/files/{kind} ; GET /api/jobs/{id}/images/{sku}.jpg ; GET /api/jobs/{id}/zip
app.py: python app.py [--port N] [--no-browser] [--host 127.0.0.1]
```

## Risks
| R | Scenario | Mitigation | Covering test (task) |
|---|---|---|---|
| R1 | Flavour word dropped -> wrong photo (Pineapple->Vanilla shake) | key visual tokens must all match for exact/strong; close only for SOFT tokens | test_matcher::GOLDEN negatives (T06) |
| R2 | Item's real type hidden in its menu category (Peri Peri Chicken under Pizzas) | item_head uses category/menu name; head gate both ways | test_text::test_item_head_from_category (T03), GOLDEN (T06) |
| R3 | Veg dish gets non-veg photo / chicken vs mutton | diet from dietary_slugs; protein-set gate | GOLDEN (T06), test_zomato::test_parse_menu_diet (T04) |
| R4 | Regional names miss (Taak, Shira, Aamras, Bhakri) | exact-synonym lexicon; parenthetical alias variants | test_text::test_synonyms (T03), GOLDEN positives (T06) |
| R5 | Zomato rate limits / bot-wall during a job | Http throttle + backoff + Retry-After; ZomatoBlocked -> stop live search, continue with pool | test_zomato::test_retry_* (T04), test_pipeline::test_blocked_continues (T10) |
| R6 | Page format change breaks parsing silently | robust literal regex; parse returns None and logs; count of parsed items surfaced in job log | test_zomato::test_parse_* (T04) |
| R7 | ImgBB key invalid / rate-limited | key rotation, disable/cooldown, sha cache | test_hosting (T08) |
| R8 | Crash at the end (encoding) wastes a 20-min run | utf-8 everywhere; outputs built from results.json; per-dish checkpoints | test_sheets::test_unicode (T09), test_pipeline::test_resume (T10) |
| R9 | Menu format variance blocks the run | flexible header/price/category parsing; warnings not errors | test_menu (T02) |
| R10 | Same photo for different dishes | per-job used-image set; size variants share by base_key | test_pipeline::test_distinct_images (T10) |
| R11 | Branded chain photo (logo box) used for a non-chain vendor | vision non-food/logo prompts; small penalty for big-chain sources when vendor is not that chain | test_vision::test_food_ok_logic (T07), test_pipeline (T10) |
| R12 | Fresh PC: no Python / store stub / no admin / path with spaces | uv private Python; quoted paths; stub detection; plain-English errors | manual run of RUN_ME with MENUSTUDIO_HOME temp (T13) |
| R13 | Model download fails offline | NullVision fallback, strict tiers, warning | test_vision::test_null_vision (T07), test_pipeline::test_text_only_mode (T10) |
| R14 | Browser refresh or closed tab loses the run | background worker thread; SSE replay from job.json/results.json | test_server::test_events_replay (T11) |
| R15 | API key leak into logs/git | settings.json git-ignored; logs show label+last4 | test_hosting::test_no_key_in_errors (T08), .gitignore (T01) |
| R16 | 49k-row template makes writes slow | write rows 2..n only; never delete rows; never iterate max_row | test_sheets::test_speed_and_contiguity (T09) |

## Test matrix
| AC or R | Test (file :: name) | Task |
|---|---|---|
| AC1 | tests/test_sheets.py :: test_category_column_uses_menu_category ; tests/test_menu.py :: test_category_inherit_and_header_rows | T09, T02 |
| AC2 | tests/test_menu.py :: (all) | T02 |
| AC3 | tests/test_sheets.py :: test_unicode_roundtrip ; tests/test_pipeline.py :: test_unicode_menu_end_to_end | T09, T10 |
| AC4, R1-R4 | tests/test_matcher.py :: test_golden_negatives, test_golden_positives | T06 |
| AC5 | tests/test_pipeline.py :: test_chain_mode_uses_chain_photos, test_own_restaurant_url | T10 |
| AC6 | tests/test_pipeline.py :: test_live_search_multi_city_and_persist | T10 |
| AC7, R5, R8 | tests/test_zomato.py :: test_retry_*, tests/test_pipeline.py :: test_blocked_continues, test_resume_skips_uploaded | T04, T10 |
| AC8, R7, R15 | tests/test_hosting.py :: (all) ; tests/test_config.py :: test_settings_roundtrip | T08, T01 |
| AC9, R16 | tests/test_sheets.py :: (all) | T09 |
| AC10, R13 | tests/test_vision.py :: test_null_vision ; tests/test_pipeline.py :: test_text_only_mode | T07, T10 |
| AC11, R14 | tests/test_server.py :: (all) + orchestrator screenshots | T11, T12 |
| AC12, R12 | orchestrator manual run of RUN_ME.bat with MENUSTUDIO_HOME=<temp> | T13 |
| AC13 | tools/eval_menus.py contact sheets + orchestrator audit | T15 |
| AC14 | tests/test_pipeline.py :: test_cli_no_upload | T10 |

## Task DAG
Execution order (sequential, D8): T01, T04, T05, T14, [DATA1 orchestrator: start seed crawl in background], T02, T03, T06, T07, T08, T09, T10, T10B, T11, T12, T13, T15, [EVAL orchestrator], FIX/TUNE, final review.
| ID | Title | Deps | Order | Write-set | Risk | Model |
|---|---|---|---|---|---|---|
| T01 | Scaffold, contracts, config, deps, dev venv | - | 1 | studio/__init__.py, studio/models.py, studio/config.py, requirements*.txt, .gitignore, .gitattributes, tests/__init__.py, tests/conftest.py, tests/test_config.py | med | sonnet |
| T04 | Zomato client + parsers | T01 | 2 | studio/zomato.py, tests/test_zomato.py, tests/fixtures/ | med | sonnet |
| T05 | Pool store (SQLite) | T01,T04 | 3 | studio/store.py, tests/test_store.py | med | sonnet |
| T14 | Seed pool builder tool | T04,T05 | 4 | tools/__init__.py, tools/build_seed_pool.py, tests/test_seed_tool.py | med | sonnet |
| DATA1 | Orchestrator runs the crawl, commits data/seed_pool.jsonl.gz, removes data/pairs.json | T14 | bg | data/ | med | (orchestrator) |
| T02 | Menu reader | T01 | 5 | studio/menu.py, tests/test_menu.py | med | sonnet |
| T03 | Lexicon + dish text understanding | T01 | 6 | studio/lexicon.py, studio/text.py, tests/test_text.py | high | opus |
| T06 | Matcher (index, scoring, tiers, golden set) | T03,T05 | 7 | studio/matcher.py, tests/test_matcher.py (+ lexicon/text refinements) | high | opus |
| T07 | Imaging + vision verifier | T03,T04,T05 | 8 | studio/imaging.py, studio/vision.py, tests/test_imaging.py, tests/test_vision.py | med | sonnet |
| T08 | ImgBB multi-key uploader | T05 | 9 | studio/hosting.py, tests/test_hosting.py | high | sonnet |
| T09 | SmartBiz output builder | T01 | 10 | studio/sheets.py, tests/test_sheets.py | med | sonnet |
| T10 | Pipeline engine + offline e2e tests | T02-T09 | 11 | studio/pipeline.py, tests/test_pipeline.py | high | opus |
| T10B | Photo swap + CLI | T10 | 12 | studio/pipeline.py, zomato_scrapper.py, tests/test_pipeline_cli.py | med | sonnet |
| T11 | FastAPI server + app.py | T10B | 13 | studio/server.py, app.py, studio/web/index.html, tests/test_server.py | med | sonnet |
| T12 | Apple-grade web UI | T11 | 14 | studio/web/ | med | opus |
| T13 | Windows launcher + README | T11 | 15 | RUN_ME.bat, scripts/setup.ps1, README.md, .streamlit/secrets.toml.example (delete), .devcontainer/devcontainer.json | high | sonnet |
| T15 | Live eval tool | T10B | 16 | tools/eval_menus.py, tests/test_eval_tool.py, .gitignore | low | sonnet |

## Rollback
Everything lives on branch prodv2.0; prodv1.0 and main are untouched. Rollback = keep using prodv1.0 (or `git revert` the offending commits on prodv2.0). User data (config/, outputs/) is git-ignored and never deleted by the app.

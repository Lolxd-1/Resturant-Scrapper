"""Shared data contracts. Every module imports these; never redefine them elsewhere."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

TIERS = ("exact", "strong", "close", "reject")
DIETS = ("veg", "egg", "nonveg", "unknown")
STATUSES = ("ready", "review", "needs_photo", "needs_price", "error")
SOURCES = ("own", "chain", "pool", "live", "swiggy", "")


@dataclass
class ImgbbKey:
    label: str
    key: str
    enabled: bool = True


@dataclass
class Settings:
    imgbb_keys: list[ImgbbKey] = field(default_factory=list)
    strictness: str = "balanced"          # "strict" | "balanced"
    live_search: bool = True
    live_budget_menus: int = 250          # max restaurant menus fetched live per job
    default_city: str = ""                # zomato city slug, "" = auto
    gemini_key: str = ""


@dataclass
class MenuRow:
    row: int                  # 1-based dish index (SKU number), in sheet order
    excel_row: int            # physical 1-based row in the sheet, for messages
    name: str
    category: str
    description: str
    price: float | None       # None = missing/unparseable/<=0
    warnings: list[str] = field(default_factory=list)
    diet: str = ""            # "veg" | "nonveg" | "egg" | "" = unknown/absent
    photo_names: list[str] = field(default_factory=list)  # look-alike dish names for photo search


@dataclass
class MenuParseResult:
    rows: list[MenuRow]
    sheet_name: str
    header_row: int                       # 1-based, 0 when no header was found
    columns: dict[str, int]               # {"name": 0, "category": 1, ...} 0-based column indexes
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)   # non-empty = cannot run


@dataclass(frozen=True)
class DishQuery:
    raw: str
    display: str                          # cleaned name for sheets/UI
    base_key: str                         # size-stripped key; size variants share a photo
    variants: tuple[frozenset[str], ...]  # canonical token sets, one per alias of the name
    head: str | None                      # canonical dish type, e.g. "PIZZA"
    diet: str                             # one of DIETS
    proteins: frozenset[str]              # e.g. frozenset({"CHICKEN"})
    is_combo: bool
    category: str = ""
    description: str = ""


@dataclass
class PoolItem:
    item_id: int
    name: str
    category: str
    menu_name: str
    description: str
    diet: str                 # one of DIETS
    img_url: str              # CDN url without query string
    res_id: str
    res_name: str
    res_url: str              # https://www.zomato.com/<city>/<slug>
    city: str
    chain_key: str            # normalized restaurant name, groups chain outlets


@dataclass
class RestaurantMenu:
    res_id: str
    name: str
    url: str
    city: str
    cuisines: str
    items: list[PoolItem] = field(default_factory=list)


@dataclass(frozen=True)
class MatchScore:
    tier: str                 # one of TIERS
    text: float               # 0..1
    reasons: tuple[str, ...] = ()


@dataclass
class Candidate:
    item: PoolItem
    score: MatchScore
    vision: float | None = None       # text-image similarity mapped to 0..1
    consensus: float | None = None    # image agreement with other candidates, 0..1
    type_ok: bool | None = None
    food_ok: bool | None = None
    final: float = 0.0
    source: str = "pool"              # one of SOURCES
    rung: int = 0                     # look-alike ladder step that found it, 0 = exact name


@dataclass
class DishResult:
    row: int
    sku: str
    name: str
    category: str
    description: str
    price: float | None
    status: str = "needs_photo"       # one of STATUSES
    reason: str = ""
    tier: str = ""
    confidence: float = 0.0
    source: str = ""
    item_name: str = ""
    restaurant: str = ""
    restaurant_url: str = ""
    zomato_img: str = ""
    local_image: str = ""             # relative to the job dir, e.g. "images/HFC-001.jpg"
    image_size: str = ""              # "WxH"
    hosted_url: str = ""
    alternates: list[dict] = field(default_factory=list)   # {"item_name","restaurant","restaurant_url","zomato_img","tier","confidence","source"}
    diet: str = ""                    # "veg" | "nonveg" | "egg" | ""
    photo_names: list[str] = field(default_factory=list)   # look-alike names tried, most specific first
    search_name: str = ""             # look-alike name whose photo is used / last searched
    lookalike: bool = False           # photo shows a look-alike, not the exact dish
    approved: bool = False            # user approved the look-alike photo


def dish_result_to_dict(r: DishResult) -> dict:
    return asdict(r)


def dish_result_from_dict(d: dict) -> DishResult:
    known = {f.name for f in fields(DishResult)}
    return DishResult(**{k: v for k, v in d.items() if k in known})

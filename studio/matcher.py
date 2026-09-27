"""Menu dish <-> Zomato item matching: pool index, precision-first scoring, tiers, ranking.

A candidate item must show the SAME dish. Every hard gate (diet, protein, head, combo,
distinguishing tokens) rejects; soft differences only lower the tier.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from functools import lru_cache
from typing import Callable, Iterable

from rapidfuzz import fuzz

from studio.lexicon import HEADS
from studio.models import Candidate, DishQuery, MatchScore, PoolItem
from studio.text import is_combo_name, item_head, item_proteins, normalize, token_role, tokens

_TIER_ORDER = {"exact": 0, "strong": 1, "close": 2}
_TIER_RANGE = {"exact": (0.90, 1.0), "strong": (0.75, 0.8999), "close": (0.55, 0.7499)}
_TIER_BONUS = {"exact": 0.10, "strong": 0.10, "close": 0.14}
_COMMON_DF_SHARE = 0.25     # tokens in more items than this share are too common to retrieve on
_SAME_NAME_RATIO = 92


def _reject(reason: str) -> MatchScore:
    return MatchScore("reject", 0.0, (reason,))


def _diet_ok(q_diet: str, item_diet: str) -> bool:
    if q_diet == "veg":
        return item_diet == "veg"
    if q_diet == "unknown":
        return item_diet in ("veg", "unknown")
    if q_diet == "egg":
        return item_diet in ("egg", "nonveg")
    return item_diet in ("nonveg", "egg", "unknown")


@lru_cache(maxsize=65536)
def _item_facts(name: str, category: str, menu_name: str):
    toks = frozenset(tokens(name))
    head = item_head(name, category, menu_name)
    if head and not any(t in HEADS for t in toks):
        toks |= {head}  # dish type named only by the menu category ("Peppy Paneer" in "Veg Pizza")
    proteins = item_proteins(name) or item_proteins(category)
    return toks, head, proteins, is_combo_name(name)


class PoolIndex:
    def __init__(self, items: Iterable[PoolItem] = ()):
        self._items: list[PoolItem] = []
        self._tokens: list[frozenset[str]] = []
        self._pos: dict[int, int] = {}
        self._postings: dict[str, list[int]] = defaultdict(list)
        self._median_idf: float | None = None
        self.add(items)

    def add(self, items: Iterable[PoolItem]) -> None:
        for item in items:
            pos = len(self._items)
            toks = frozenset(tokens(item.name))
            self._items.append(item)
            self._tokens.append(toks)
            self._pos[id(item)] = pos
            for t in toks:
                self._postings[t].append(pos)
        self._median_idf = None

    def __len__(self) -> int:
        return len(self._items)

    def item_tokens(self, item: PoolItem) -> frozenset[str]:
        pos = self._pos.get(id(item))
        if pos is not None and self._items[pos] is item:
            return self._tokens[pos]
        return frozenset(tokens(item.name))

    def _idf_of_df(self, df: int) -> float:
        return math.log((len(self._items) + 1) / (df + 1)) + 1

    def idf(self, token: str) -> float:
        return self._idf_of_df(len(self._postings.get(token, ())))

    def median_idf(self) -> float:
        """idf of the median token occurrence: half of all item tokens are at least this common."""
        if self._median_idf is None:
            dfs = sorted(len(p) for p in self._postings.values())
            total, acc, median_df = sum(dfs), 0, 0
            for df in reversed(dfs):
                acc += df
                median_df = df
                if 2 * acc >= total:
                    break
            self._median_idf = self._idf_of_df(median_df)
        return self._median_idf

    def retrieve(self, q: DishQuery, limit: int = 600) -> list[PoolItem]:
        n = len(self._items)
        if not n:
            return []
        max_df = n * _COMMON_DF_SHARE
        weights: dict[int, float] = defaultdict(float)
        query_toks = frozenset().union(*q.variants)
        for t in sorted((t for t in query_toks if t in self._postings), key=lambda t: len(self._postings[t])):
            posting = self._postings[t]
            if len(posting) > max_df:
                break
            w = self.idf(t)
            for p in posting:
                weights[p] += w
        head_posting = self._postings.get(q.head, ()) if q.head else ()
        if head_posting and not (q.head in query_toks and len(head_posting) <= max_df):
            w = self.idf(q.head)
            cap, added = limit * 3, 0
            for p in head_posting:
                if p in weights:
                    weights[p] += w
                elif added < cap:
                    weights[p] = w
                    added += 1
        items = self._items
        kept = [(w, p) for p, w in weights.items() if _diet_ok(q.diet, items[p].diet)]
        top = heapq.nlargest(limit, kept, key=lambda wp: (wp[0], -wp[1]))
        return [items[p] for _, p in top]


def _score_variant(q: DishQuery, v: frozenset[str], facts, ratio: float, idf, median) -> MatchScore:
    item_toks, i_head, _, i_combo = facts
    if not v:
        return _reject("empty")
    v_heads = {HEADS[t] for t in v if t in HEADS}
    v_head = q.head if q.head in v_heads else None
    if v_head and i_head and v_head != i_head:
        return _reject("head")
    if i_head and not v_head and i_head not in v_heads:
        return _reject(f"item is a {i_head}")
    if v_head and not i_head and v_head not in item_toks:
        return _reject("head missing")

    q_vis = {t for t in v if token_role(t) != "nonvisual"}
    i_vis = {t for t in item_toks if token_role(t) != "nonvisual"}
    missing = sorted(q_vis - i_vis)
    extra = sorted(i_vis - q_vis)
    tier, reasons = "exact", []
    for t in missing:
        if token_role(t) != "soft":
            return _reject(f"missing {t}")
    if missing:
        tier = "close"
        reasons += [f"missing {t}" for t in missing]
    for t in extra:
        if token_role(t) in ("base", "protein", "head"):
            return _reject(f"extra {t}")
    extra_visual = [t for t in extra if token_role(t) == "visual"]
    if len(extra_visual) == 1 and median is not None and idf(extra_visual[0]) < median:
        tier = "close"
        reasons.append(f"extra common {extra_visual[0]}")
    elif extra_visual:
        return _reject(f"extra {extra_visual[0]}")
    extra_soft = [t for t in extra if token_role(t) == "soft"]
    if extra_soft:
        if tier == "exact":
            tier = "strong"
        reasons += [f"extra {t}" for t in extra_soft]
    if q.is_combo and not i_combo:
        tier = "close"
        reasons.append("item is not a combo")

    lo, hi = _TIER_RANGE[tier]
    penalty = 0.01 * sum(1 for t in item_toks - v if token_role(t) in ("nonvisual", "soft"))
    text = min(hi, max(lo, lo + _TIER_BONUS[tier] * ratio - penalty))
    return MatchScore(tier, round(text, 4), tuple(reasons))


def _order(s: MatchScore) -> tuple[int, float]:
    return _TIER_ORDER[s.tier], -s.text


def score(q: DishQuery, item: PoolItem, idf: Callable[[str], float]) -> MatchScore:
    facts = _item_facts(item.name, item.category, item.menu_name)
    item_toks, _, i_proteins, i_combo = facts
    if not item_toks or not any(q.variants):
        return _reject("empty")
    if not _diet_ok(q.diet, item.diet):
        return _reject("diet")
    if q.proteins != i_proteins:
        return _reject("protein")
    if i_combo and not q.is_combo:
        return _reject("combo")
    owner = getattr(idf, "__self__", None)
    median = owner.median_idf() if isinstance(owner, PoolIndex) else None
    ratio = fuzz.token_set_ratio(normalize(q.display), normalize(item.name)) / 100
    results = [_score_variant(q, v, facts, ratio, idf, median) for v in q.variants]
    passed = [s for s in results if s.tier != "reject"]
    return min(passed, key=_order) if passed else results[0]


def rank(q: DishQuery, items: Iterable[PoolItem], idf: Callable[[str], float]) -> list[Candidate]:
    candidates = []
    for item in items:
        s = score(q, item, idf)
        if s.tier != "reject":
            candidates.append(Candidate(item, s))
    candidates.sort(key=lambda c: _order(c.score))
    seen: set[str] = set()
    unique = []
    for c in candidates:
        if c.item.img_url not in seen:
            seen.add(c.item.img_url)
            unique.append(c)
    return unique


def same_dish_menu_match(q: DishQuery, items: Iterable[PoolItem],
                         idf: Callable[[str], float]) -> Candidate | None:
    items = list(items)
    ranked = rank(q, items, idf)
    if ranked and ranked[0].score.tier in ("exact", "strong"):
        return ranked[0]
    name = normalize(q.display)
    best, best_ratio = None, 0.0
    for item in items:
        ratio = fuzz.token_sort_ratio(name, normalize(item.name))
        if ratio >= _SAME_NAME_RATIO and ratio > best_ratio \
                and _item_facts(item.name, item.category, item.menu_name)[1] == q.head:
            best, best_ratio = item, ratio
    if best is None:
        return None
    return Candidate(best, MatchScore("strong", round(0.75 + 0.10 * best_ratio / 100, 4), ("same name",)))

"""Dish-name understanding: normalize, canonical tokens, head (dish type), diet, combos."""
from __future__ import annotations

import re
import unicodedata

from studio.lexicon import (
    CATEGORY_HEAD_HINTS,
    COMBO_WORDS,
    DIET_HINTS_NONVEG,
    DIET_HINTS_VEG,
    HEADS,
    NOISE,
    NON_VISUAL,
    PHRASES,
    PROTEINS,
    SOFT,
    SYNONYMS,
)
from studio.models import DishQuery
from studio.spelling import fold_homoglyphs, transliterate

_BASES = frozenset({
    "PANEER", "SOYA", "CHAAP", "MUSHROOM", "ALOO", "GOBI", "CORN", "MATAR", "PALAK", "BHINDI",
    "BAINGAN", "METHI", "CHANA", "DAL", "RAJMA", "KAJU", "SEV", "SHEVGA", "RAGI", "BAJRA",
    "JOWAR", "BESAN", "PITLA", "MATKI",
})


def _alternation(keys) -> str:
    return "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))


_PHRASE_RE = re.compile(rf"(?<![a-z0-9])({_alternation(PHRASES)})(?![a-z0-9])")
_CATEGORY_RE = re.compile(rf"(?<![a-z0-9])({_alternation(CATEGORY_HEAD_HINTS)})(?:e?s)?(?![a-z0-9])")
_PAREN_RE = re.compile(r"\(([^()]*)\)?")
_COMBO_SPLIT_RE = re.compile(r"\b(?:and|plus)\b")
_COMBO_HEAD_SPLIT_RE = re.compile(r"\b(?:and|plus|with)\b")  # "Burger with Fries" -> BURGER
_NONVEG_WORDS_RE = re.compile(r"\bnon (?:veg|vegetarian)\b")
_SIZE_TAIL_RE = re.compile(
    r"\s*\b(?:small|medium|large|regular|half|full|quarter|mini|jumbo|single|double)$"
    r"|\s*\b\d+\s*(?:ml|l|ltr|litre|liter|gm|gms|g|gram|grams|kg|pcs|pc|piece|pieces|nos|no|inch|inches)$"
)
_UNIT_WORDS_RE_PART = r"ml|l|ltr|litre|liter|gm|gms|g|gram|grams|kg|pcs|pc|piece|pieces|nos|no|inch|inches"
# a 2- or 3-digit number outside parentheses and not followed by a unit word is part of the dish
# name ("Chicken 65"); inside parentheses or before a unit it is a quantity, so stays noise.
_KEEP_NUM_RE = re.compile(rf"\b(\d{{2,3}})\b(?!\s*(?:{_UNIT_WORDS_RE_PART})\b)", re.IGNORECASE)
# a veg signal (word in the name, or in the category with no non-veg hint) alongside a non-veg
# protein token means the dish is a veg-style imitation, not the real meat/egg dish.
_VEG_CONFLICT_WORDS: frozenset[str] = frozenset({"veg", "vegetarian", "jain", "shakahari", "shaakahari"})


def _kept_numbers(text: str) -> frozenset[str]:
    outside = _PAREN_RE.sub(" ", text or "")
    return frozenset(m.group(1) for m in _KEEP_NUM_RE.finditer(outside))


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", transliterate(fold_homoglyphs(text or "")))
    s = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ").replace("+", " plus ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _canon(word: str) -> str:
    if word.isupper():  # already canonical (phrase output)
        return word
    if word in SYNONYMS:
        return SYNONYMS[word]
    single = _singular(word)
    return SYNONYMS.get(single, single)


def _is_noise(word: str, keep_numbers: frozenset[str] = frozenset()) -> bool:
    if word.isupper():
        return False
    if word.isdigit():
        return word not in keep_numbers
    return len(word) == 1 or word in NOISE or _singular(word) in NOISE


def _tokens(text: str, fallback: bool) -> list[str]:
    keep_numbers = _kept_numbers(text)
    words = _PHRASE_RE.sub(lambda m: PHRASES[m.group(1)], normalize(text)).split()
    kept = [_canon(w) for w in words if not _is_noise(w, keep_numbers)]
    if not kept and fallback:
        kept = [_canon(w) for w in words]
    return list(dict.fromkeys(kept))


def tokens(text: str) -> list[str]:
    return _tokens(text, fallback=True)


def token_role(token: str) -> str:
    if token in HEADS:
        return "head"
    if token in PROTEINS:
        return "protein"
    if token in NON_VISUAL:
        return "nonvisual"
    if token in SOFT:
        return "soft"
    if token in _BASES:
        return "base"
    return "visual"


def _proteins(toks) -> frozenset[str]:
    found = {PROTEINS[t] for t in toks if t in PROTEINS}
    # "Paneer Kheema" / "Soya Keema": keema is the mince style, not meat.
    if "KEEMA" in found and any(t in _BASES for t in toks):
        found.discard("KEEMA")
    return frozenset(found)


def item_proteins(name: str) -> frozenset[str]:
    return _proteins(tokens(name))


def _last_head(toks: list[str]) -> str | None:
    for t in reversed(toks):
        if t in HEADS:
            return HEADS[t]
    return None


def _split_parens(name: str) -> tuple[str, list[str]]:
    return _PAREN_RE.sub(" ", name), _PAREN_RE.findall(name)


def is_combo_name(name: str) -> bool:
    padded = f" {normalize(name)} "
    if any(f" {w} " in padded for w in COMBO_WORDS):
        return True
    segments = _COMBO_SPLIT_RE.split(padded)
    return sum(1 for seg in segments if _last_head(_tokens(seg, False))) >= 2


def _name_head(name: str) -> str | None:
    main, parens = _split_parens(name)
    if is_combo_name(name):
        for seg in _COMBO_HEAD_SPLIT_RE.split(normalize(main)):
            head = _last_head(_tokens(seg, False))
            if head:
                return head
    for text in (main, *parens):
        head = _last_head(_tokens(text, False))
        if head:
            return head
    return None


def _category_head(text: str) -> str | None:
    found = {CATEGORY_HEAD_HINTS[m.group(1)] for m in _CATEGORY_RE.finditer(normalize(text))}
    if len(found) == 1 and "" not in found:
        return found.pop()
    return None


def item_head(name: str, category: str = "", menu_name: str = "") -> str | None:
    head = _name_head(name)
    if head:
        return head
    for text in (category, menu_name):
        head = _category_head(text)
        if head:
            return head
    return None


def size_base_key(name: str) -> str:
    key = normalize(name)
    while True:
        stripped = _SIZE_TAIL_RE.sub("", key).strip()
        if stripped == key or not stripped:
            return key
        key = stripped


def _is_alias(toks: list[str]) -> bool:
    roles = [token_role(t) for t in toks]
    if "head" in roles or "protein" in roles or sum(r in ("visual", "base") for r in roles) >= 2:
        return True
    # "(Drumstick Curry)" restates the dish; CURRY is soft, so the rules above miss it
    return "CURRY" in toks and len(toks) >= 2


def _has_hint(padded: str, hints: frozenset[str]) -> bool:
    return any(f" {h} " in padded for h in hints)


def _veg_conflict(proteins: frozenset[str], name: str, category: str) -> bool:
    if not proteins:
        return False
    if _has_hint(f" {normalize(name)} ", _VEG_CONFLICT_WORDS):
        return True
    cat_padded = f" {normalize(category)} "
    if _has_hint(cat_padded, DIET_HINTS_NONVEG):
        return False
    return _has_hint(cat_padded, _VEG_CONFLICT_WORDS)


def _diet(proteins: frozenset[str], toks: list[str], name: str, category: str) -> str:
    # The dish name decides first; the category only breaks ties.
    if proteins - {"EGG"}:
        return "nonveg"
    if "EGG" in proteins:
        return "egg"
    padded_name = f" {normalize(name)} "
    if _has_hint(padded_name, DIET_HINTS_NONVEG):
        return "nonveg"
    if _has_hint(padded_name, DIET_HINTS_VEG):
        return "veg"
    cat = normalize(category)
    cat_nonveg = _has_hint(f" {cat} ", DIET_HINTS_NONVEG)
    # "non veg" contains "veg": drop it before looking for a veg hint ("Veg & Non Veg" is mixed)
    cat_veg = _has_hint(f" {_NONVEG_WORDS_RE.sub(' ', cat)} ", DIET_HINTS_VEG)
    if cat_nonveg and not cat_veg and not any(t in _BASES for t in toks):
        return "nonveg"
    if cat_veg and not cat_nonveg:
        return "veg"
    return "unknown"


def parse_dish(name: str, category: str = "", description: str = "", *, display: str | None = None) -> DishQuery:
    main_text, parens = _split_parens(name)
    main = _tokens(main_text, fallback=True)
    aliases: list[list[str]] = []
    options: list[list[str]] = []
    for content in parens:
        if "/" in content:
            # "(Veg/Paneer)": each option is an alternative form of the main dish
            options.extend(t for t in (_tokens(o, False) for o in content.split("/")) if t)
            continue
        toks = _tokens(content, False)
        if not toks:
            continue
        if _is_alias(toks):
            aliases.append(toks)
        else:
            main = list(dict.fromkeys(main + toks))
    variants = [frozenset(main)]
    variants += [frozenset(a) for a in aliases]
    variants += [frozenset(main + o) for o in options]
    name_toks = main + [t for a in aliases for t in a]
    proteins = _proteins(name_toks)
    diet = _diet(proteins, name_toks, name, category)
    if _veg_conflict(proteins, name, category):
        diet, proteins = "veg", frozenset()
    return DishQuery(
        raw=name,
        display=" ".join((name if display is None else display).split()),
        base_key=size_base_key(name),
        variants=tuple(dict.fromkeys(variants)),
        head=item_head(name, category),
        diet=diet,
        proteins=proteins,
        is_combo=is_combo_name(name),
        category=category,
        description=description,
    )

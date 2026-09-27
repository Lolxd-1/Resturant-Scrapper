"""Brand guard: local OCR catches Zomato/Swiggy props and other chains' branding in photos."""
from __future__ import annotations

import importlib
import logging
import re
import threading
from typing import Callable, Iterable

log = logging.getLogger("studio.brand")

ALWAYS_BLOCKED = frozenset({"zomato", "swiggy", "zomato.com"})

GENERIC = {
    "pizza", "pizzas", "cafe", "restaurant", "burger", "burgers", "biryani", "house", "kitchen",
    "foods", "food", "point", "corner", "express", "bakery", "sweets", "family", "dhaba", "hotel",
    "veg", "pure", "the", "and", "momos", "chinese", "tea", "coffee", "juice", "shakes", "center",
    "centre", "grill", "bar", "lounge", "world", "hub", "junction", "factory", "company", "station",
    "plaza", "palace", "king", "queen", "royal", "spice", "taste",
}

_MIN_SCORE = 0.6
_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize_words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("'", ""))


def brand_words_from_pool(chain_counts: dict[str, int], min_outlets: int = 5) -> set[str]:
    words: set[str] = set()
    for chain, count in chain_counts.items():
        if count < min_outlets:
            continue
        for token in _normalize_words(chain):
            if len(token) >= 4 and token not in GENERIC:
                words.add(token)
    return words


def _rapidocr_words(engine, jpeg: bytes) -> list[str]:
    result = engine(jpeg)
    txts = getattr(result, "txts", None) or []
    scores = getattr(result, "scores", None) or []
    return [t for t, s in zip(txts, scores) if s >= _MIN_SCORE]


class BrandGuard:
    """OCR-based check for branded photos. `ocr`, if given, is a callable(jpeg) -> list[str]
    of recognized text (already score-filtered); tests use this to script OCR output.
    Without it, a real RapidOCR engine is built lazily on first use.
    """

    def __init__(self, brand_words: Iterable[str], ocr: Callable[[bytes], list[str]] | None = None):
        self.brand_words = frozenset(brand_words)
        self._ocr = ocr
        self._engine = None
        self._lock = threading.Lock()
        self._logged_disabled = False
        self.available, self.reason = True, ""
        if ocr is None:
            # RapidOCR loads onnxruntime (and its VC++ runtime DLLs) only on first use, so probe both now.
            try:
                for module in ("rapidocr", "onnxruntime"):
                    importlib.import_module(module)
            except Exception as exc:
                self.available, self.reason = False, str(exc) or type(exc).__name__

    def _disable(self, reason: str) -> None:
        self.available, self.reason = False, reason
        if not self._logged_disabled:
            log.warning("brand guard disabled: %s", reason)
            self._logged_disabled = True

    def _call_ocr(self, jpeg: bytes) -> list[str]:
        if self._ocr is not None:
            return self._ocr(jpeg)
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    try:
                        from rapidocr import RapidOCR
                        self._engine = RapidOCR()
                    except Exception as exc:
                        self._disable(str(exc))
                        self._engine = False
        if self._engine is False:
            return []
        try:
            return _rapidocr_words(self._engine, jpeg)
        except Exception as exc:
            self._disable(str(exc))
            return []

    def text_in(self, jpeg: bytes) -> list[str]:
        words: list[str] = []
        for text in self._call_ocr(jpeg):
            words += _normalize_words(text)
        return words

    def brands_in(self, jpeg: bytes) -> set[str]:
        words = set(self.text_in(jpeg))
        return (words & ALWAYS_BLOCKED) | (words & self.brand_words)

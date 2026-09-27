from __future__ import annotations

from studio.brand import ALWAYS_BLOCKED, BrandGuard, brand_words_from_pool


def test_tc1_brands_in_matches_blocked_and_brand_words_only():
    assert BrandGuard([], ocr=lambda jpeg: ["zomato"]).brands_in(b"x") == {"zomato"}
    assert BrandGuard(["pinoz"], ocr=lambda jpeg: ["Pino'z", "Pizza"]).brands_in(b"x") == {"pinoz"}
    assert BrandGuard([], ocr=lambda jpeg: ["R", "2", "Ketchup"]).brands_in(b"x") == set()


def test_tc2_brand_words_from_pool_keeps_distinctive_tokens_of_big_chains():
    counts = {"la pinoz pizza": 12, "dominos pizza": 30, "shivraj biryani house": 1}
    assert brand_words_from_pool(counts) == {"pinoz", "dominos"}


def test_always_blocked_contains_zomato_and_swiggy():
    assert {"zomato", "swiggy", "zomato.com"} == set(ALWAYS_BLOCKED)


def test_ocr_unavailable_returns_empty():
    guard = BrandGuard([], ocr=None)
    guard._engine = False  # simulate import failure without touching the real engine
    assert guard.text_in(b"x") == []
    assert guard.brands_in(b"x") == set()

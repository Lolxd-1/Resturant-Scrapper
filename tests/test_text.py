"""Tests for studio.text: dish-name tokens, heads, diet, combos, size keys, token roles."""
from __future__ import annotations

from studio.lexicon import HEAD_CUISINES, HEAD_GROUP, HEAD_PROMPT, HEADS
from studio.text import (
    item_head,
    item_proteins,
    normalize,
    parse_dish,
    size_base_key,
    token_role,
    tokens,
)


def test_tc1_regional_synonyms():
    assert tokens("Paneer Pulav") == tokens("paneer pulao")
    assert "GOBI" in tokens("Flower Masala")
    assert tokens("Taak") == ["BUTTERMILK"]
    assert tokens("Mattha") == ["BUTTERMILK"]
    chaas = tokens("Masala Chaas")
    assert "BUTTERMILK" in chaas and "masala" in chaas


def test_tc2_size_variant_pizza():
    q = parse_dish("Peri Peri Paneer Pizza - Medium")
    assert q.head == "PIZZA"
    assert q.variants[0] == frozenset({"PERIPERI", "PANEER", "PIZZA"})
    assert q.base_key == parse_dish("Peri Peri Paneer Pizza - Large").base_key
    assert q.diet == "veg"


def test_tc3_dum_murgh_alias():
    q = parse_dish("Dum Murgh (Dum Chicken)")
    assert q.proteins == frozenset({"CHICKEN"})
    assert q.diet == "nonveg"
    assert "dum" in q.variants[0]


def test_tc4_item_head_uses_category():
    assert item_head("Peri Peri Chicken", "Pizzas") == "PIZZA"
    assert item_head("Peri Peri Chicken", "Chicken Starters") is None
    assert item_head("Paneer Tikka Pizza") == "PIZZA"
    assert item_head("Pizza Style Sandwich") == "SANDWICH"


def test_tc5_flavour_word_kept():
    q = parse_dish("Pineapple Thick Shake")
    assert q.variants[0] == frozenset({"pineapple", "SHAKE"})
    assert q.head == "SHAKE"


def test_tc6_v1_mistakes_not_repeated():
    bharwa = tokens("Bharwa Bhindi")
    assert "BHINDI" in bharwa and "BAINGAN" not in bharwa
    ladoo = tokens("Besan Ladoo")
    assert "BESAN" in ladoo and "PITLA" not in ladoo
    assert "CHAAP" in tokens("Soya Chaap")
    kulcha = tokens("Butter Kulcha")
    assert "KULCHA" in kulcha and "PARATHA" not in kulcha
    assert tokens("Bajri Bhakri") == ["BAJRA", "BHAKRI"]


def test_tc7_combo_detection():
    assert parse_dish("Cheese Pizza (Half) & Veg Cheese Corn Pizza (Half)").is_combo is True
    assert parse_dish("Paneer & Corn Cheese Burger").is_combo is False
    assert parse_dish("Burger Combo").is_combo is True


def test_tc8_parenthetical_alias():
    q = parse_dish("Nagali Papad (Ragi Papad)")
    assert q.head == "PAPAD"
    assert all("RAGI" in v for v in q.variants)


def test_tc9_proteins_and_diet():
    assert parse_dish("Chicken Biryani").proteins == frozenset({"CHICKEN"})
    assert parse_dish("Mutton Biryani").proteins == frozenset({"MUTTON"})
    assert parse_dish("Egg Biryani").diet == "egg"
    assert parse_dish("Veg Biryani").diet == "veg"
    assert parse_dish("Dal Fry").diet == "unknown"


def test_tc10_non_latin_and_accents():
    q = parse_dish("पनीर टिक्का")
    assert q.display == "पनीर टिक्का"
    assert q.variants == (frozenset(),)
    assert normalize("Crème Brûlée") == "creme brulee"


def test_tc11_size_base_key():
    assert size_base_key("Mutton Handi (Full)") == size_base_key("Mutton Handi (Half)")
    assert size_base_key("Lassi (250 ml)") == size_base_key("Lassi")


def test_tc12_and_spellings():
    expected = {"cheese", "CORN", "PIZZA"}
    assert set(tokens("Cheese N Corn Pizza")) == expected
    assert set(tokens("Cheese & Corn Pizza")) == expected
    assert set(tokens("Cheese and Corn Pizza")) == expected


def test_tc13_token_roles():
    assert token_role("adrak") == "nonvisual"
    assert token_role("PERIPERI") == "soft"
    assert token_role("pineapple") == "visual"
    assert token_role("PIZZA") == "head"
    assert token_role("CHICKEN") == "protein"
    assert token_role("PANEER") == "base"


def test_tc14_every_head_has_group_prompt_cuisines():
    for head in HEADS.values():
        assert head in HEAD_GROUP, head
        assert head in HEAD_PROMPT, head
        assert head in HEAD_CUISINES, head


def test_parenthetical_options_and_modifiers():
    momos = parse_dish("Steam Momos (Veg/Paneer)")
    assert momos.variants[0] == frozenset({"STEAM", "MOMOS"})
    assert frozenset({"STEAM", "MOMOS", "PANEER"}) in momos.variants
    bhaji = parse_dish("Baingan Bhaji (Kala Masala Special)")
    assert bhaji.variants[0] == frozenset({"BAINGAN", "BHAJI", "kala", "masala"})
    shevga = parse_dish("Shevga Masala Lal (Drumstick Curry)")
    assert frozenset({"SHEVGA", "CURRY"}) in shevga.variants
    assert shevga.head is None  # CURRY is a soft token, not a head


def test_noise_only_name_keeps_tokens():
    assert tokens("Plate") == ["plate"]
    assert tokens("Classic Pizzas") == ["PIZZA"]


def test_item_proteins_and_keema():
    assert item_proteins("Surmai Fry") == frozenset({"FISH"})
    assert item_proteins("Paneer Tikka") == frozenset()
    assert item_proteins("Chicken Keema") == frozenset({"CHICKEN", "KEEMA"})
    assert parse_dish("Paneer Kheema").diet == "veg"
    assert parse_dish("Boiled Egg Fry").variants[0] == frozenset({"BOILEDEGG", "FRY"})


def test_diet_name_decides_before_category():
    assert parse_dish("Paneer Tikka", "Veg & Non Veg Starters").diet == "veg"
    assert parse_dish("Chicken 65", "Veg & Non Veg Starters").diet == "nonveg"
    assert parse_dish("Tangdi Kabab", "Non Veg Starters").diet == "nonveg"
    assert parse_dish("Egg Biryani", "Non Veg Biryani").diet == "egg"
    assert parse_dish("Dal Fry", "Non Veg").diet == "unknown"
    assert parse_dish("Dal Fry", "Veg Main Course").diet == "veg"


def test_curry_family_and_spellings():
    assert tokens("Shevga Rassa") == tokens("Shevga Curry") == tokens("Shevga Gravy")
    assert token_role("CURRY") == "soft"
    assert token_role("kala") == "soft"
    assert tokens("Lasan Methi") == tokens("Lasun Methi")
    assert tokens("Sadha Rice (Full)") == tokens("Plain Rice") == tokens("Sada Rice")
    assert tokens("Shevbhaji") == tokens("Shev Bhaji")
    assert tokens("Combo Meal") == ["combo", "meal"] and token_role("combo") == "nonvisual"


def test_category_hints_are_unambiguous():
    assert item_head("Chocolate", "Thick Shakes") == "SHAKE"
    assert item_head("Aloo", "Indian Breads") is None
    assert item_head("Poha", "Tea & Snacks") is None
    assert item_head("Masala", "", "Fried Rice") == "FRIEDRICE"
    assert item_head("Burger with Fries") == "BURGER"


def test_tune2_tc4_dish_head_from_own_category():
    assert parse_dish("Garden Special", "Pizzas").head == "PIZZA"
    assert parse_dish("Garlic Bread", "Pizza").head == "GARLICBREAD"
    assert parse_dish("Farmhouse", "Beverages").head is None

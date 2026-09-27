"""Tests for studio.matcher: golden same-dish set, ranking, same-menu match, retrieval, speed."""
from __future__ import annotations

import random
import statistics
import time

import pytest

from studio.matcher import PoolIndex, rank, same_dish_menu_match, score
from studio.models import MatchScore, PoolItem
from studio.text import parse_dish

# (dish_name, dish_category, item_name, item_category, item_diet, expected)
GOLDEN = [
    ("Pineapple Thick Shake", "Shakes", "Vanilla Thick Shake", "Shakes", "veg", "reject"),
    ("Dum Murgh (Dum Chicken)", "Non Veg", "Peri Peri Chicken", "Pizzas", "nonveg", "reject"),
    ("Boiled Egg Fry", "Egg", "Fried Eggs", "Breakfast", "egg", "reject"),
    ("Cheese Momos", "Momos", "Veg Darjeeling Steam Momo", "Momos", "veg", "reject"),
    ("Strawberry Virgin Mojito", "Mocktails", "Virgin Mojito", "Mocktails", "veg", "reject"),
    ("Paneer Schezwan Pizza - Medium", "Pizza", "Paneer pizza", "Pizza", "veg", "reject"),
    ("Makhani Cheese Maggi", "Maggi", "Vegetable Cheese Maggi", "Maggi", "veg", "reject"),
    ("Chicken Biryani", "Biryani", "Mutton Biryani", "Biryani", "nonveg", "reject"),
    ("Veg Biryani", "Biryani", "Chicken Biryani", "Biryani", "nonveg", "reject"),
    ("Veg Burger", "Burgers", "Chicken Burger", "Burgers", "nonveg", "reject"),
    ("Besan Ladoo", "Sweets", "Pithla Bhakri", "Maharashtrian", "veg", "reject"),
    ("Bharwa Bhindi", "Main Course", "Bharwa Baingan", "Main Course", "veg", "reject"),
    ("Cheese Momos", "Momos", "Cheese Momos Combo Meal", "Combos", "veg", "reject"),
    ("Veg Burger", "Burgers", "Veg Burger Combo", "Combos", "veg", "reject"),
    ("Egg Curry", "Egg", "Chicken Curry", "Main Course", "nonveg", "reject"),
    ("Mango Thick Shake", "Shakes", "Mango Lassi", "Beverages", "veg", "reject"),
    ("Cold Coffee", "Beverages", "Hot Coffee", "Beverages", "veg", "reject"),
    ("Masala Dosa", "South Indian", "Masala Papad", "Starters", "veg", "reject"),
    ("Paneer Tikka Masala", "Main Course", "Paneer Tikka Pizza", "Pizza", "veg", "reject"),
    ("Garlic Bread", "Sides", "Garlic Naan", "Breads", "veg", "reject"),
    ("Chocolate Pizza - Medium", "Pizza", "Chocolate Shake", "Shakes", "veg", "reject"),
    ("Kaju Curry", "Main Course", "Kaju Katli", "Mithai", "veg", "reject"),
    ("Tandoori Paneer Pizza - Large", "Pizza", "Paneer Pizza", "Pizza", "veg", "reject"),
    ("Gobi Manchurian", "Chinese", "Veg Manchurian", "Chinese", "veg", "reject"),
    ("Aloo Paratha", "Breads", "Paneer Paratha", "Breads", "veg", "reject"),
    ("Chicken Tikka", "Starters", "Paneer Tikka", "Starters", "veg", "reject"),
    ("Sabudana Khichdi", "Fasting", "Dal Khichdi", "Rice", "veg", "reject"),
    ("Plain Papad", "Papad", "Masala Papad", "Starters", "veg", "reject"),
    ("Jeera Rice", "Rice", "Jeera Aloo", "Main Course", "veg", "reject"),
    ("Lassi", "Cold Drinks", "Mango Lassi", "Beverages", "veg", "reject"),
    ("Peri Peri Chicken Burger", "Burgers", "Veg Burger", "Burgers", "veg", "reject"),
    ("Paneer Butter Masala", "Main Course", "Butter Chicken", "Main Course", "nonveg", "reject"),
    ("Veg Cheese Sandwich", "Sandwiches", "Veg Cheese Pizza", "Pizza", "veg", "reject"),
    ("Shevga Dry (Drumstick Dry)", "Main Course", "Veg Drumsticks", "Starters", "veg", "reject"),
    ("Soyabean Dry", "Main Course", "Soyabean Chilli", "Chinese", "veg", "reject"),
    ("Taak", "Cold Drinks", "Buttermilk", "Beverages", "veg", "exact"),
    ("Mattha", "Cold Drinks", "Chaas", "Beverages", "veg", "exact"),
    ("Flower Masala (Cauliflower Curry)", "Main Course", "Gobi Masala", "Main Course", "veg", "strong+"),
    ("Cheese N Corn Pizza - Medium", "Pizza", "Corn & Cheese Pizza", "Pizza", "veg", "exact"),
    ("Veg Cheese Pizza - Large", "Pizza", "Veg Cheese Pizza", "Pizzas", "veg", "exact"),
    ("Paneer Pulao", "Rice", "Paneer Pulav", "Rice", "veg", "exact"),
    ("Chapati", "Roti", "Chapati", "Breads", "veg", "exact"),
    ("Bajri Bhakri", "Bhakri", "Bajra Bhakri", "Breads", "veg", "exact"),
    ("Nagali Papad (Ragi Papad)", "Papad", "Ragi Papad", "Papad", "veg", "exact"),
    ("Dum Murgh (Dum Chicken)", "Non Veg", "Chicken Dum", "Main Course", "nonveg", "exact"),
    ("Chicken Biryani", "Biryani", "Chicken Dum Biryani", "Biryani", "nonveg", "strong+"),
    ("Adrak Chai", "Tea", "Ginger Tea", "Beverages", "veg", "strong+"),
    ("Irani Maska (Bun Maska)", "Bakery", "Bun Maska", "Bakery", "veg", "strong+"),
    ("Peri Peri Fries", "Fries", "Peri Peri Fries", "Sides", "veg", "exact"),
    ("French Fries", "Fries", "Classic French Fries", "Sides", "veg", "exact"),
    ("Sabudana Khichdi", "Fasting", "Sabudana Khichadi", "Maharashtrian", "veg", "exact"),
    ("Shira Plate", "Sweets", "Rava Sheera", "Desserts", "veg", "exact"),
    ("Aamras", "Cold Drinks", "Aamras (250 ml)", "Desserts", "veg", "exact"),
    ("Masala Taak", "Cold Drinks", "Masala Chaas", "Beverages", "veg", "exact"),
    ("Egg Bhurji", "Egg", "Anda Bhurji", "Egg Dishes", "egg", "exact"),
    ("Mutton Handi (Full)", "Non Veg", "Mutton Handi", "Main Course", "nonveg", "exact"),
    ("Tandoor Roti", "Roti", "Tandoori Roti", "Breads", "veg", "exact"),
    ("Paneer & Corn Cheese Burger", "Burgers", "Paneer Corn Cheese Burger", "Burgers", "veg", "exact"),
    ("Dahi Wati", "Fasting", "Curd", "Sides", "veg", "exact"),
    ("Veg Burger", "Burgers", "Classic Veg Burger", "Burgers", "veg", "exact"),
    ("Masala Maggi", "Maggi", "Maggi Masala", "Maggi", "veg", "exact"),
    ("Peri Peri Paneer Pizza - Medium", "Pizza", "Paneer Pizza", "Pizza", "veg", "close"),
    ("Cheese Burst Pizza - Large", "Pizza", "Cheese Burst Pizza", "Pizza", "veg", "exact"),
    ("Cold Coffee With Ice Cream", "Beverages", "Cold Coffee with Ice cream", "Beverages", "veg", "exact"),
    ("Oreo Thick Shake", "Shakes", "Oreo Shake", "Shakes", "veg", "exact"),
    ("Gobi Roast", "Main Course", "Roasted Gobi", "Main Course", "veg", "exact"),
    ("Gulab Jamun (2 pcs)", "Sweets", "Gulab Jamun", "Desserts", "veg", "exact"),
    ("Jain Dal Fry", "Main Course", "Dal Fry (Jain)", "Main Course", "veg", "exact"),
    ("Soyabean Masala", "Main Course", "Soya Chunks Masala", "Main Course", "veg", "strong+"),
    ("Dal Fry", "Main Course", "Dal Fry", "Main Course", "veg", "exact"),
    ("Shevga Curry", "Main Course", "Shevga Rassa", "Main Course", "veg", "strong+"),
    ("Shevga Masala Lal (Drumstick Curry)", "Main Course", "Shevga Rassa", "Main Course", "veg", "strong+"),
    ("Kaju Curry", "Main Course", "Kaju Masala", "Main Course", "veg", "close+"),
    ("Shev Bhaji (Kala Masala Special)", "Main Course", "Shev Bhaji", "Maharashtrian", "veg", "close+"),
    ("Cheese Pizza (Half) & Veg Cheese Corn Pizza (Half)", "Combos", "Cheese Corn Pizza Combo", "Combos",
     "veg", "close"),  # combos: close+ and NOT exact/strong
]

ALLOWED = {
    "reject": {"reject"},
    "exact": {"exact"},
    "strong": {"strong"},
    "strong+": {"exact", "strong"},
    "close+": {"exact", "strong", "close"},
    "close": {"close"},  # P27: close and NOT exact/strong
}

TIER_RANGE = {"exact": (0.90, 1.0), "strong": (0.75, 0.90), "close": (0.55, 0.75)}

# (name, category, diet): a realistic mixed pool, so idf and the median idf mean something
POOL_ROWS = [
    ("Margherita Pizza", "Pizzas", "veg"), ("Farmhouse Pizza", "Pizzas", "veg"),
    ("Chicken Tikka Pizza", "Pizzas", "nonveg"), ("Cheese Pizza", "Pizzas", "veg"),
    ("Double Cheese Margherita", "Pizzas", "veg"), ("Veg Loaded Pizza", "Pizzas", "veg"),
    ("Aloo Tikki Burger", "Burgers", "veg"), ("Crispy Chicken Burger", "Burgers", "nonveg"),
    ("Paneer Burger", "Burgers", "veg"), ("Chocolate Thick Shake", "Shakes", "veg"),
    ("Strawberry Shake", "Shakes", "veg"), ("Pineapple Shake", "Shakes", "veg"),
    ("Kitkat Shake", "Shakes", "veg"), ("Masala Chai", "Tea", "veg"),
    ("Cutting Chai", "Tea", "veg"), ("Paneer Butter Masala", "Main Course", "veg"),
    ("Chicken Tikka Masala", "Main Course", "nonveg"), ("Kadai Paneer", "Main Course", "veg"),
    ("Chicken Tikka", "Starters", "nonveg"), ("Veg Biryani", "Biryani", "veg"),
    ("Hyderabadi Chicken Biryani", "Biryani", "nonveg"), ("Egg Biryani", "Biryani", "egg"),
    ("Steam Veg Momos", "Momos", "veg"), ("Fried Chicken Momos", "Momos", "nonveg"),
    ("Masala Dosa", "South Indian", "veg"), ("Idli Sambar", "South Indian", "veg"),
    ("Butter Naan", "Breads", "veg"), ("Jeera Rice", "Rice", "veg"),
    ("Misal Pav", "Maharashtrian", "veg"), ("Vada Pav", "Maharashtrian", "veg"),
    ("Kaju Curry", "Main Course", "veg"), ("Veg Cheese Sandwich", "Sandwiches", "veg"),
]
POOL_ROWS += [(item, cat, diet) for _, _, item, cat, diet, _ in GOLDEN]


def make_item(name, category, diet, item_id=1, img_url="https://b.zmtcdn.com/x.jpg"):
    return PoolItem(item_id=item_id, name=name, category=category, menu_name=category,
                    description="", diet=diet, img_url=img_url, res_id="1", res_name="R",
                    res_url="https://www.zomato.com/pune/r", city="pune", chain_key="r")


def build_pool():
    seen, items = set(), []
    for name, cat, diet in POOL_ROWS:
        if name.lower() not in seen:
            seen.add(name.lower())
            items.append(make_item(name, cat, diet, len(items) + 1, f"https://b.zmtcdn.com/{len(items) + 1}.jpg"))
    return items


POOL = build_pool()
INDEX = PoolIndex(POOL)


def constant_idf(_token):
    return 5.0


@pytest.mark.parametrize("dish,dish_cat,item,item_cat,diet,expected", GOLDEN,
                         ids=[f"{g[0]}->{g[2]}" for g in GOLDEN])
def test_golden(dish, dish_cat, item, item_cat, diet, expected):
    s = score(parse_dish(dish, dish_cat), make_item(item, item_cat, diet), INDEX.idf)
    assert s.tier in ALLOWED[expected], s
    if s.tier == "reject":
        assert s.text == 0.0 and s.reasons
    else:
        lo, hi = TIER_RANGE[s.tier]
        assert lo <= s.text <= 1.0 if s.tier == "exact" else lo <= s.text < hi


def test_golden_rejects_hold_with_constant_idf():
    for dish, dish_cat, item, item_cat, diet, expected in GOLDEN:
        if expected == "reject":
            s = score(parse_dish(dish, dish_cat), make_item(item, item_cat, diet), constant_idf)
            assert s.tier == "reject", (dish, item, s)


def test_one_common_extra_visual_token_is_close():
    q = parse_dish("Corn Pizza", "Pizza")
    item = make_item("Corn Cheese Pizza", "Pizza", "veg")
    assert INDEX.idf("cheese") < INDEX.median_idf()
    s = score(q, item, INDEX.idf)
    assert s.tier == "close" and 0.55 <= s.text < 0.75
    assert score(q, item, constant_idf).tier == "reject"
    rare = score(q, make_item("Corn Jalapeno Pizza", "Pizza", "veg"), INDEX.idf)
    assert rare.tier == "reject" and rare.reasons == ("extra jalapeno",)


def test_soft_extra_is_strong_and_combo_query_is_close():
    s = score(parse_dish("Paneer Pizza"), make_item("Paneer Pizza Masala", "Pizza", "veg"), INDEX.idf)
    assert s.tier == "strong" and 0.75 <= s.text < 0.90


def test_combo_query_is_never_exact_or_strong():
    q = parse_dish("Cheese Pizza (Half) & Veg Cheese Corn Pizza (Half)", "Combos")
    for item in ("Cheese Corn Pizza Combo", "Cheese Pizza & Corn Cheese Pizza"):
        s = score(q, make_item(item, "Combos", "veg"), constant_idf)
        assert s.tier == "close" and 0.55 <= s.text < 0.75, (item, s)


def test_close_needs_two_matched_tokens():
    s = score(parse_dish("Shevga Dry (Drumstick Dry)"), make_item("Veg Drumsticks", "Starters", "veg"),
              constant_idf)
    assert s == MatchScore("reject", 0.0, ("too little evidence",))
    chilli_pool = PoolIndex(make_item(n, "Chinese", "veg") for n in (
        "Chilli Paneer", "Chilli Potato", "Chilli Mushroom", "Chilli Gobi", "Soyabean Chilli", "Dal Fry"))
    assert chilli_pool.idf("CHILLI") < chilli_pool.median_idf()
    soya = score(parse_dish("Soyabean Dry"), make_item("Soyabean Chilli", "Chinese", "veg"), chilli_pool.idf)
    assert soya.reasons == ("too little evidence",)
    kaju = score(parse_dish("Kaju Curry"), make_item("Kaju Masala", "Main Course", "veg"), constant_idf)
    assert kaju.tier == "close"


def test_rank_prefers_plain_name():
    q = parse_dish("Cheese Pizza - Small", "Pizza")
    items = [
        make_item("Four Cheese Pizza", "Pizza", "veg", 1, "https://b.zmtcdn.com/1.jpg"),
        make_item("Veg Cheese Pizza", "Pizza", "veg", 2, "https://b.zmtcdn.com/2.jpg"),
        make_item("Cheese Burst Pizza", "Pizza", "veg", 3, "https://b.zmtcdn.com/3.jpg"),
        make_item("Cheese Pizza", "Pizza", "veg", 4, "https://b.zmtcdn.com/4.jpg"),
    ]
    ranked = rank(q, items, INDEX.idf)
    assert ranked[0].item.name == "Cheese Pizza"
    assert all(c.item.name != "Four Cheese Pizza" for c in ranked)
    assert all(c.score.tier != "reject" for c in ranked)
    tiers = [(c.score.tier, c.score.text) for c in ranked]
    assert tiers == sorted(tiers, key=lambda t: ({"exact": 0, "strong": 1, "close": 2}[t[0]], -t[1]))


def test_rank_dedupes_by_image():
    q = parse_dish("Dal Fry")
    items = [make_item("Dal Fry", "Main Course", "veg", 1, "https://b.zmtcdn.com/same.jpg"),
             make_item("Dal Fry", "Dal", "veg", 2, "https://b.zmtcdn.com/same.jpg")]
    assert len(rank(q, items, INDEX.idf)) == 1


def test_same_dish_menu_match_uses_category_head():
    menu = [
        make_item("Margherita", "Veg Pizza", "veg", 1, "https://b.zmtcdn.com/m1.jpg"),
        make_item("Peppy Paneer", "Veg Pizza", "veg", 2, "https://b.zmtcdn.com/m2.jpg"),
        make_item("Chicken Dominator", "Non-Veg Pizza", "nonveg", 3, "https://b.zmtcdn.com/m3.jpg"),
        make_item("Garlic Breadsticks", "Sides", "veg", 4, "https://b.zmtcdn.com/m4.jpg"),
        make_item("Choco Lava Cake", "Desserts", "veg", 5, "https://b.zmtcdn.com/m5.jpg"),
    ]
    c = same_dish_menu_match(parse_dish("Peppy Paneer Pizza - Medium", "Pizza"), menu, INDEX.idf)
    assert c is not None and c.item.name == "Peppy Paneer"
    assert c.score.tier in ("exact", "strong")


def test_same_dish_menu_match_fuzzy_fallback_and_none():
    menu = [make_item("Kothimbir Vadi", "Starters", "veg", 1),
            make_item("Sabudana Vada", "Starters", "veg", 2)]
    c = same_dish_menu_match(parse_dish("Kothimbir Wadi", "Starters"), menu, INDEX.idf)
    assert c is not None and c.item.name == "Kothimbir Vadi"
    assert c.score.tier == "strong" and 0.75 <= c.score.text < 0.90
    assert same_dish_menu_match(parse_dish("Thalipeeth", "Starters"), menu, INDEX.idf) is None


def test_tune2_tc2_same_product_name_beats_combo_gate_but_not_diet():
    menu = [make_item("Non Veg Pack Of 4", "Tacos", "nonveg", 1)]
    c = same_dish_menu_match(parse_dish("Non Veg Pack Of 4", "Tacos"), menu, INDEX.idf)
    assert c is not None and c.item.name == "Non Veg Pack Of 4" and c.score.tier == "exact"
    assert c.score.text == 1.0
    veg_menu = [make_item("Veg Pack Of 4", "Tacos", "nonveg", 2)]
    assert same_dish_menu_match(parse_dish("Veg Pack Of 4", "Tacos"), veg_menu, INDEX.idf) is None


def test_tune2_tc3_same_product_name_ignores_spacing_and_case():
    menu = [make_item("Cheesy Margherita (Personal Giant Slice)", "Personal Giant Slices", "veg", 1)]
    c = same_dish_menu_match(parse_dish("Cheesy Margherita(personal Giant Slice)", "Personal Giant Slices"),
                             menu, INDEX.idf)
    assert c is not None and c.score.tier == "exact"


@pytest.mark.parametrize("dish,target", [
    ("Paneer Pulao", "Paneer Pulav"),
    ("Egg Bhurji", "Anda Bhurji"),
    ("Masala Taak", "Masala Chaas"),
    ("Peri Peri Fries", "Peri Peri Fries"),
    ("Shira", "Rava Sheera"),
])
def test_retrieve_finds_target(dish, target):
    q = parse_dish(dish)
    found = INDEX.retrieve(q, limit=10)
    assert target in [i.name for i in found]
    assert rank(q, found, INDEX.idf)[0].item.name == target


def test_retrieve_never_returns_nonveg_for_veg_query():
    for dish in ("Veg Biryani", "Veg Burger", "Paneer Tikka", "Veg Cheese Pizza", "Veg Momos"):
        q = parse_dish(dish)
        assert q.diet == "veg"
        assert all(i.diet == "veg" for i in INDEX.retrieve(q))


def test_index_basics():
    assert len(INDEX) == len(POOL)
    assert INDEX.idf("NOT_A_TOKEN") > INDEX.idf("PIZZA")
    assert INDEX.item_tokens(POOL[0]) == frozenset({"margherita", "PIZZA"})
    assert PoolIndex().retrieve(parse_dish("Dal Fry")) == []


def test_unicode_dish_is_empty_reject():
    s = score(parse_dish("पनीर टिक्का"), make_item("Paneer Tikka", "Starters", "veg"), INDEX.idf)
    assert s.tier == "reject" and s.reasons == ("empty",)


_HEAD_WORDS = ["pizza", "burger", "sandwich", "pasta", "noodles", "momos", "fries", "shake",
               "biryani", "pulao", "dosa", "idli", "roll", "salad", "soup", "curry", "tikka",
               "kebab", "paratha", "naan", "cake", "juice", "lassi", "thali"]


def _word(rng):
    return "".join(rng.choice("bcdfghjklmnprtvz") + rng.choice("aeiou") for _ in range(rng.randint(2, 4)))


def test_perf_400k_index():
    rng = random.Random(7)
    vocab = sorted({_word(rng) for _ in range(3600)})[:3000]
    diets = ("veg", "veg", "nonveg", "egg", "unknown")

    def name():
        return " ".join(rng.sample(vocab, rng.randint(1, 3)) + [rng.choice(_HEAD_WORDS)])

    items = [make_item(name(), "Menu", rng.choice(diets), i) for i in range(400_000)]
    start = time.perf_counter()
    index = PoolIndex(items)
    assert time.perf_counter() - start < 60
    assert len(index) == 400_000

    queries = [parse_dish(name()) for _ in range(50)]
    times = []
    for q in queries:
        start = time.perf_counter()
        found = index.retrieve(q)
        times.append(time.perf_counter() - start)
        assert found and len(found) <= 600
    assert statistics.mean(times) < 0.05, statistics.mean(times)

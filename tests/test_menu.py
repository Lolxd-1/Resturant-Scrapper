"""Tests for studio.menu: read_menu, parse_price, clean_category, derive_sku_prefix."""
from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from studio.menu import clean_category, derive_sku_prefix, parse_price, read_menu
from tests.conftest import make_xlsx

GANESH_PATH = Path(
    r"C:/Users/omkar/OneDrive/Desktop/zomato/This/Resturant-Scrapper/New Ganesh/Ganesh Bhojnalaya Menu.xlsx"
)


def test_parse_price_examples():
    assert parse_price("₹120") == 120.0
    assert parse_price("Rs. 99/-") == 99.0
    assert parse_price("100/180") == 100.0
    assert parse_price("120.50") == 120.5
    assert parse_price(0) is None
    assert parse_price("") is None
    assert parse_price(None) is None
    assert parse_price("free") is None
    assert parse_price(150) == 150.0
    assert parse_price(float("nan")) is None


def test_clean_category_and_sku_prefix():
    assert clean_category("  MAIN   COURSE ") == "Main Course"
    assert clean_category("Chinese Starters") == "Chinese Starters"
    assert derive_sku_prefix("H-Food Cafe") == "HFC"
    assert derive_sku_prefix("Domino's") == "DOM"
    assert derive_sku_prefix("Shivraj Biryani House") == "SBH"
    assert derive_sku_prefix("  ") == "SKU"
    assert derive_sku_prefix("7 Heaven") == "7H"


def test_tc1_v1_layout_happy(tmp_path):
    rows = [
        ["Item Name", "Category", "Description", "Price"],
        ["Pizza", "Main", "Cheesy", 250],
        ["Burger", "Main", "Juicy", 150],
        ["Coke", "Beverages", "Cold", 50],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert len(result.rows) == 3
    assert result.columns == {"name": 0, "category": 1, "description": 2, "price": 3}
    assert [r.price for r in result.rows] == [250.0, 150.0, 50.0]
    assert all(isinstance(r.price, float) for r in result.rows)


def test_tc2_header_after_title_and_blanks(tmp_path):
    rows = [
        ["H-FOOD CAFE MENU"],
        [None],
        [None],
        ["Price", "Dish", "Category"],
        [99, "Sandwich", "Snacks"],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert result.header_row == 4
    assert result.columns == {"price": 0, "name": 1, "category": 2}
    assert len(result.rows) == 1
    assert result.rows[0].name == "Sandwich"
    assert result.rows[0].category == "Snacks"
    assert result.rows[0].price == 99.0


def test_tc3_price_variants(tmp_path):
    header = ["Item Name", "Category", "Description", "Price"]
    rows = [
        header,
        ["Dish1", "Cat", "Desc", "\u20b9120"],
        ["Dish2", "Cat", "Desc", "Rs. 99/-"],
        ["Dish3", "Cat", "Desc", "100/180"],
        ["Dish4", "Cat", "Desc", "120.50"],
        ["Dish5", "Cat", "Desc", 0],
        ["Dish6", "Cat", "Desc", ""],
        ["Dish7", "Cat", "Desc", None],
        ["Dish8", "Cat", "Desc", "free"],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    prices = [r.price for r in result.rows]
    assert prices == [120.0, 99.0, 100.0, 120.5, None, None, None, None]
    for r in result.rows:
        if r.price is None:
            assert any("Price missing or invalid" in w for w in r.warnings)


def test_tc4_section_headers(tmp_path):
    rows = [
        ["Dish", "Price"],
        ["PIZZA", None],
        ["Margherita", 200],
        ["Pepperoni", 250],
        ["Beverages", None],
        ["Coke", 50],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    names = [r.name for r in result.rows]
    categories = [r.category for r in result.rows]
    assert names == ["Margherita", "Pepperoni", "Coke"]
    assert categories == ["Pizza", "Pizza", "Beverages"]


def test_tc5_category_inheritance(tmp_path):
    rows = [
        ["Item Name", "Category", "Description", "Price"],
        ["Idli", "South Indian", "desc", 40],
        ["Dosa", "", "desc", 50],
        ["Vada", "", "desc", 30],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert [r.category for r in result.rows] == ["South Indian", "South Indian", "South Indian"]


def test_fix2_tc5_category_column_beats_type_column(tmp_path):
    rows = [
        ["Item Name", "Type", "Category", "Price"],
        ["Paneer Tikka", "Veg", "Starters", 220],
        ["Chicken Wings", "Non-Veg", "Starters", 260],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert result.columns["category"] == 2
    assert [r.category for r in result.rows] == ["Starters", "Starters"]


def test_tc6_duplicate_names(tmp_path):
    rows = [
        ["Item Name", "Category", "Description", "Price"],
        ["Lassi", "Beverages", "desc", 40],
        ["Lassi", "Beverages", "desc", 45],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert result.rows[0].row == 1
    assert result.rows[1].row == 2
    assert result.rows[0].warnings == []
    assert "Duplicate dish name" in result.rows[1].warnings


def test_tc7_unicode_names(tmp_path):
    rows = [
        ["Item Name", "Category", "Description", "Price"],
        ["\u092a\u0928\u0940\u0930 \u091f\u093f\u0915\u094d\u0915\u093e", "Main", "desc", 180],
        ["Cr\u00e8me Br\u00fbl\u00e9e \u20b9", "Dessert", "desc", 120],
        ["\U0001f355 Pizza", "Pizza", "desc", 200],
    ]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert result.rows[0].name == "\u092a\u0928\u0940\u0930 \u091f\u093f\u0915\u094d\u0915\u093e"
    assert result.rows[1].name == "Cr\u00e8me Br\u00fbl\u00e9e \u20b9"
    assert result.rows[2].name == "\U0001f355 Pizza"


def test_tc8_xls_and_missing_file(tmp_path):
    xls_path = tmp_path / "menu.xls"
    result = read_menu(xls_path)
    assert result.errors == ["Please save the file as .xlsx (Excel Workbook) and upload again."]

    missing_path = tmp_path / "nope.xlsx"
    result2 = read_menu(missing_path)
    assert len(result2.errors) == 1
    assert result2.errors[0].startswith("Could not open the file")


def test_tc9_csv(tmp_path):
    path = tmp_path / "menu.csv"
    path.write_text("Dish,Price,Category\nPizza,250,Main\n", encoding="utf-8-sig")
    result = read_menu(path)
    assert result.errors == []
    assert len(result.rows) == 1
    assert result.rows[0].name == "Pizza"
    assert result.rows[0].price == 250.0
    assert result.rows[0].category == "Main"


def test_tc10_picks_sheet_with_dishes(tmp_path):
    wb = Workbook()
    empty_ws = wb.active
    empty_ws.title = "Empty"
    menu_ws = wb.create_sheet("Menu")
    for row in [
        ["Item Name", "Category", "Description", "Price"],
        ["Pizza", "Main", "Cheesy", 250],
    ]:
        menu_ws.append(row)
    path = tmp_path / "menu.xlsx"
    wb.save(path)

    result = read_menu(path)
    assert result.errors == []
    assert result.sheet_name == "Menu"
    assert len(result.rows) == 1


def test_tc11_no_header_v1_assumption(tmp_path):
    rows = [["Veg Burger", "Burgers", "desc", 99]]
    path = make_xlsx(tmp_path / "menu.xlsx", rows)
    result = read_menu(path)
    assert result.errors == []
    assert result.header_row == 0
    assert len(result.rows) == 1
    assert result.rows[0].name == "Veg Burger"
    assert result.rows[0].category == "Burgers"
    assert result.rows[0].price == 99.0
    assert any("No header row found" in w for w in result.warnings)


@pytest.mark.skipif(not GANESH_PATH.exists(), reason="real Ganesh menu file not available")
def test_tc13_real_ganesh_file():
    result = read_menu(GANESH_PATH)
    assert result.errors == []
    assert len(result.rows) >= 60
    shrikhand_rows = [r for r in result.rows if r.name == "Shrikhand"]
    assert shrikhand_rows
    assert all(r.price is None for r in shrikhand_rows)

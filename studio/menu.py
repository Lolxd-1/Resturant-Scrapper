"""Read any reasonable vendor menu file (xlsx/xlsm/csv) into a MenuParseResult.

Never raises for a bad or messy input file; problems are reported as row
warnings or file-level errors/warnings instead of blocking the run.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import openpyxl

from studio.models import MenuParseResult, MenuRow

_MAX_ROWS = 2000
_MAX_HEADER_SCAN = 15

_ROLE_ORDER = ("name", "category", "description", "price")
_ROLE_SYNONYMS = {
    "name": {
        "item name", "item", "dish", "dish name", "name", "product",
        "product name", "menu item", "particulars",
    },
    "category": {"category", "section", "type", "menu category", "group", "course"},
    "description": {"description", "desc", "details", "item description", "about"},
    "price": {
        "price", "rate", "mrp", "amount", "cost", "selling price",
        "price rs", "price inr", "rs",
    },
}

_PRICE_STRIP_RE = re.compile(r"₹|rs\.?|inr|/-|[,\s]", re.IGNORECASE)
_PRICE_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WHITESPACE_RE = re.compile(r"\s+")
_HEADER_NONLETTER_RE = re.compile(r"[^a-z]+")
_SKU_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")
_SKU_NONALNUM_RE = re.compile(r"[^A-Z0-9]")


def parse_price(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return float(value) if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        cleaned = _PRICE_STRIP_RE.sub("", text)
        match = _PRICE_NUM_RE.search(cleaned)
        if not match:
            return None
        num = float(match.group())
        return num if num > 0 else None
    return None


def clean_category(text: str) -> str:
    s = str(text or "")
    s = _WHITESPACE_RE.sub(" ", s).strip()
    s = s.strip("-:|* ")
    if not s:
        return ""
    if any(c.isalpha() for c in s) and (s.isupper() or s.islower()):
        s = s.title()
    return s[:100]


def derive_sku_prefix(vendor: str) -> str:
    words = _SKU_WORD_RE.findall(vendor or "")
    if not words:
        prefix = "SKU"
    elif len(words) == 1:
        alnum = _SKU_NONALNUM_RE.sub("", words[0].upper())
        prefix = alnum[:3]
    else:
        prefix = "".join(w[0] for w in words[:3]).upper()
    prefix = _SKU_NONALNUM_RE.sub("", prefix)[:6]
    return prefix or "SKU"


def _clean_name(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        s = str(int(value))
    else:
        s = str(value)
    return _WHITESPACE_RE.sub(" ", s).strip()


def _clean_text(value: object) -> str:
    s = str(value or "")
    return _WHITESPACE_RE.sub(" ", s).strip()


def _cell(row: tuple, idx: int | None):
    if idx is None or idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _normalize_header_cell(value: object) -> str:
    s = str(value or "").lower()
    s = _HEADER_NONLETTER_RE.sub(" ", s)
    return _WHITESPACE_RE.sub(" ", s).strip()


def _detect_header(row: tuple) -> dict[str, int] | None:
    columns: dict[str, int] = {}
    for idx, raw in enumerate(row):
        norm = _normalize_header_cell(raw)
        if not norm:
            continue
        for role in _ROLE_ORDER:
            if role in columns:
                continue
            if norm in _ROLE_SYNONYMS[role]:
                columns[role] = idx
                break
    if "name" in columns and ("price" in columns or "category" in columns):
        return columns
    return None


def _first_nonempty_row(rows: list[tuple]) -> tuple | None:
    for row in rows:
        if any(_clean_name(c) for c in row):
            return row
    return None


def _parse_rows(rows: list[tuple]) -> dict:
    """Parse one sheet's raw rows into dish rows plus header/columns metadata."""
    file_warnings: list[str] = []
    header_row_idx = None
    columns: dict[str, int] = {}
    for i in range(min(_MAX_HEADER_SCAN, len(rows))):
        detected = _detect_header(rows[i])
        if detected:
            header_row_idx = i
            columns = detected
            break

    if header_row_idx is None:
        columns = {"name": 0}
        first_row = _first_nonempty_row(rows)
        if first_row is not None:
            price_ok = parse_price(_cell(first_row, 3)) is not None
            col1 = _cell(first_row, 1)
            col1_text = isinstance(col1, str) and col1.strip() != ""
            if price_ok or col1_text:
                columns = {"name": 0, "category": 1, "description": 2, "price": 3}
                file_warnings.append(
                    "No header row found; assumed columns Item Name | Category | Description | Price."
                )
        header_row = 0
        data_start = 0
    else:
        header_row = header_row_idx + 1
        data_start = header_row_idx + 1

    name_idx = columns.get("name")
    category_idx = columns.get("category")
    description_idx = columns.get("description")
    price_idx = columns.get("price")

    dish_rows: list[MenuRow] = []
    current_section = ""
    last_category = ""
    seen: set[tuple[str, str]] = set()
    missing_price_count = 0

    n = len(rows)
    i = data_start
    while i < n:
        row = rows[i]
        name = _clean_name(_cell(row, name_idx))
        if not name:
            i += 1
            continue

        price_raw = _cell(row, price_idx)
        price = parse_price(price_raw)
        description = _clean_text(_cell(row, description_idx))
        category_cell = clean_category(_cell(row, category_idx))

        if price is None and not description and not category_cell:
            next_row = None
            for j in range(i + 1, n):
                if _clean_name(_cell(rows[j], name_idx)):
                    next_row = rows[j]
                    break
            if next_row is not None and parse_price(_cell(next_row, price_idx)) is not None:
                current_section = clean_category(name)
                i += 1
                continue

        if category_cell:
            category = category_cell
        elif current_section:
            category = current_section
        elif last_category:
            category = last_category
        else:
            category = ""
        if category:
            last_category = category

        row_warnings: list[str] = []
        if price is None:
            missing_price_count += 1
            if price_raw is None:
                raw_disp = ""
            elif isinstance(price_raw, str):
                raw_disp = price_raw.strip()
            else:
                raw_disp = str(price_raw)
            row_warnings.append(f"Price missing or invalid ({raw_disp})")
        if len(name) > 200:
            row_warnings.append("Name longer than 200 characters; it will be cut")

        key = (name.lower(), category)
        if key in seen:
            row_warnings.append("Duplicate dish name")
        else:
            seen.add(key)

        dish_rows.append(
            MenuRow(
                row=len(dish_rows) + 1,
                excel_row=i + 1,
                name=name,
                category=category,
                description=description,
                price=price,
                warnings=row_warnings,
            )
        )
        i += 1

    return {
        "rows": dish_rows,
        "header_row": header_row,
        "columns": columns,
        "warnings": file_warnings,
        "missing_price_count": missing_price_count,
    }


def _read_csv_rows(path: Path) -> tuple[list[tuple] | None, str | None]:
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
        except OSError as e:
            return None, f"Could not open the file: {e}"
    if text is None:
        return None, "Could not open the file: unable to decode text"
    try:
        rows = [tuple(r) for r in csv.reader(io.StringIO(text))][:_MAX_ROWS]
    except csv.Error as e:
        return None, f"Could not open the file: {e}"
    return rows, None


def _read_xlsx_sheets(path: Path) -> tuple[list[tuple[str, list[tuple]]] | None, str | None]:
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as e:
        return None, f"Could not open the file: {e}"
    try:
        sheets = []
        for ws in wb.worksheets:
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= _MAX_ROWS:
                    break
                rows.append(row)
            sheets.append((ws.title, rows))
        return sheets, None
    except Exception as e:
        return None, f"Could not open the file: {e}"
    finally:
        wb.close()


def _empty_result(error: str) -> MenuParseResult:
    return MenuParseResult(rows=[], sheet_name="", header_row=0, columns={}, errors=[error])


def read_menu(path: Path) -> MenuParseResult:
    path = Path(path)
    ext = path.suffix.lower()

    if ext == ".xls":
        return _empty_result("Please save the file as .xlsx (Excel Workbook) and upload again.")

    if ext == ".csv":
        rows, err = _read_csv_rows(path)
        if err:
            return _empty_result(err)
        sheet_name = ""
        parse = _parse_rows(rows or [])
    elif ext in (".xlsx", ".xlsm"):
        sheets, err = _read_xlsx_sheets(path)
        if err:
            return _empty_result(err)
        best_name = ""
        best_parse = None
        for name, rows in sheets or []:
            candidate = _parse_rows(rows)
            if best_parse is None or len(candidate["rows"]) > len(best_parse["rows"]):
                best_parse = candidate
                best_name = name
        parse = best_parse if best_parse is not None else _parse_rows([])
        sheet_name = best_name
    else:
        return _empty_result(f"Unsupported file type {ext}. Upload an .xlsx file.")

    dish_rows = parse["rows"]
    warnings = list(parse["warnings"])
    errors: list[str] = []
    if not dish_rows:
        errors.append("No dishes found. Row 1 should be: Item Name | Category | Description | Price.")
    if parse["missing_price_count"] > 0:
        warnings.append(
            f"{parse['missing_price_count']} dishes have no price; they will be listed in the PENDING sheet."
        )
    if "category" not in parse["columns"]:
        warnings.append("No Category column; categories will be inferred from dish names.")

    return MenuParseResult(
        rows=dish_rows,
        sheet_name=sheet_name,
        header_row=parse["header_row"],
        columns=parse["columns"],
        warnings=warnings,
        errors=errors,
    )

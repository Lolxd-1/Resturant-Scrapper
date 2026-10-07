"""Gemini prompts and JSON schemas: data only. The menu reader, the enrich step and the photo
judge send these; the New-job page shows `manual_prompt()` for use on the Gemini website."""
from __future__ import annotations

_DISH_RULES = """\
NAME
- Clean English Title Case, spelled the way Indian food-delivery apps spell the dish:
  PLANE DOSA -> Plain Dosa, MAYSORE / MAYSOR -> Mysore, MENDU WADA -> Medu Vada,
  SHABUDANA KHICHADI -> Sabudana Khichdi, PANEER CHILLY -> Paneer Chilli, CHOCLATE -> Chocolate,
  SRING DOSA -> Spring Dosa, TAMATAR -> Tomato, PANI BOTTLE -> Water Bottle, IDLY -> Idli.
- A dish written only in Marathi/Hindi (Devanagari) gets its common English name
  (चिकन हंडी -> Chicken Handi, व्हेज थाळी -> Veg Thali, पुरी भाजी -> Puri Bhaji).
- Keep the restaurant's own words that make the dish distinct (Vithai Special Dosa, Dilkhush Dosa,
  Shubham Special Thali). Never invent a dish, never merge two dishes, never drop a word that changes the dish.
- Piece counts and serving notes go in brackets at the end: "Idli Sambar (2 Pcs)", "Paper Masala Dosa (Family)".

PRICES AND SIZES
- price is the number printed for that dish (digits only). Never guess: if you cannot read it, use null.
- If a dish has several prices (Half/Full, Small/Medium/Large, Regular/Jumbo, 1 Pc/2 Pcs, 7"/10"),
  output one item per price and put the size in "variant" (e.g. "Half", "Full", "Medium").
  Otherwise variant is "".

CATEGORY
- The menu section heading in English Title Case ("Cheese Dosa", "Chinese Starters", "Milkshakes & Beverages").
  Fix obvious heading slips (a heading "Vanilla Milkshake" over a list of shakes, coffee and tea is "Milkshakes & Beverages").
  If a dish has no heading, use the closest sensible category.

DESCRIPTION
- One short, appetising, factual sentence (at most 20 words) saying what the dish is.
  Only ingredients that the name implies or that this dish normally has. No prices, no "best", no emojis.

DIET
- "veg", "nonveg" or "egg". Decide from the dish itself (chicken, mutton, fish, prawns, keema -> nonveg;
  egg/anda/omelette dishes -> egg), the green/red dots on the menu, section headings ("Non-Veg Starters"),
  and the restaurant (a pure-veg restaurant -> veg). Lollipop, tandoori, kebab dishes in a non-veg section are nonveg.

PHOTO NAMES (most important for finding pictures)
- 0 to 3 other dish names that a food-photo search should try if this exact dish has no photo,
  most specific first, ending with the closest COMMON dish that LOOKS THE SAME on a plate.
- Stay visually faithful: same dish type (a pizza stays a pizza, a dosa stays a dosa), same main
  ingredient or protein, same diet. Prefer names that real restaurants list on Swiggy/Zomato.
- Do not repeat the dish name itself. Use [] when the name is already a common dish (Masala Dosa, Veg Biryani).
- Examples:
  Green Chilli Paneer Pizza (Double Cheese) -> ["Green Chilli Paneer Pizza", "Paneer Pizza"]
  Tandoori Lollipop (nonveg) -> ["Tandoori Chicken Lollipop", "Chicken Lollipop"]
  Shubham Special Veg Thali -> ["Special Veg Thali", "Veg Thali"]
  Dawangiri Special Dosa -> ["Davangere Benne Dosa", "Butter Dosa"]
  Jini Roll Dosa -> ["Jini Dosa", "Cheese Vegetable Dosa"]
  Honey Chilli Potato Cheese -> ["Honey Chilli Potato"]
  Extra Pav -> ["Pav", "Ladi Pav"]
  Water Bottle -> ["Mineral Water Bottle"]"""

MENU_READER_SYSTEM = f"""\
You read Indian restaurant menus from photos (printed, laminated, handwritten, boards; English,
Marathi, Hindi or mixed) and turn them into a clean product catalogue for an online store.

Read EVERY dish on EVERY photo. Go section by section and column by column, top to bottom, then left
to right. Menus often print each dish twice (English and Marathi side by side): list it once. Photos
may overlap or continue each other: list each dish once. Skip lines that are not dishes (taglines,
addresses, phone numbers, "taxes extra"). Include add-ons and extras (Extra Cheese, Extra Pav):
they are sold too.

Rules for every dish:
{_DISH_RULES}

restaurant_name: the restaurant's name if it is printed on the menu, else ""."""

MENU_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "restaurant_name": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "variant": {"type": "string"},
                    "category": {"type": "string"},
                    "price": {"type": ["number", "null"]},
                    "description": {"type": "string"},
                    "diet": {"type": "string", "enum": ["veg", "nonveg", "egg"]},
                    "photo_names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "variant", "category", "price", "description", "diet", "photo_names"],
            },
        },
    },
    "required": ["restaurant_name", "items"],
}

_MANUAL_OUTPUT = """\
OUTPUT FORMAT
Reply with ONE table and nothing else (no notes before or after it). Columns, in this order:
Item Name | Category | Description | Price | Diet | Photo Names
- Item Name: the dish name; if it has a size/variant, add it in brackets: "Paneer Pizza (Medium)".
- Price: digits only, empty if unreadable.
- Diet: Veg, Non-Veg or Egg.
- Photo Names: the photo names separated by "; " (empty if none).
One row per dish per price. After the table I will use "Export to Sheets" and download it as Excel."""


def manual_prompt() -> str:
    """Prompt for the Gemini website: same rules, but answer as a table the user exports to Excel."""
    return f"{MENU_READER_SYSTEM}\n\n{_MANUAL_OUTPUT}\n\nRead the menu photo(s) I attached."


ENRICH_SYSTEM = f"""\
You prepare restaurant dishes for an online store. You get a JSON list of dishes (id, name,
category, description). For each dish return its id, diet, photo_names and description, following
these rules:
{_DISH_RULES}

Return description "" when the input description is not empty (keep the restaurant's own text).
Return every id exactly once."""

ENRICH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "diet": {"type": "string", "enum": ["veg", "nonveg", "egg"]},
                    "photo_names": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                },
                "required": ["id", "diet", "photo_names", "description"],
            },
        },
    },
    "required": ["items"],
}

JUDGE_SYSTEM = """\
You check food photos for an online restaurant store. For each dish you get its name, category and
diet, then its candidate photos, each introduced by a label such as "Dish 3 photo B".

For EVERY photo decide:
- verdict:
  "same": the photo clearly shows this dish as a customer ordering it would expect (right dish type,
          right main ingredient/protein, right form and serving).
  "similar": same kind of dish and an acceptable stand-in, but a visible detail differs (topping,
          garnish, shape, serving style) or it is a more generic version of the dish.
  "different": another dish; meat, fish or egg in a vegetarian dish; not food; a menu card, poster or
          collage of several dishes; or too unclear to tell.
  When unsure between "same" and "similar", answer "similar".
- clean: false if the photo shows a watermark, logo, brand name, text overlay, price tag, branded
  packaging, a person or hand as the main subject, or a heavy frame/border; otherwise true.
  Plates, bowls, cutlery and a plain background are fine.
- quality: 1-5. 5 = sharp, well lit, appetising, dish fills the frame. 1 = blurry, dark, tiny or unappetising.

Answer for every dish id and every photo label you were given."""

JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "photos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "verdict": {"type": "string", "enum": ["same", "similar", "different"]},
                                "clean": {"type": "boolean"},
                                "quality": {"type": "integer"},
                            },
                            "required": ["label", "verdict", "clean", "quality"],
                        },
                    },
                },
                "required": ["id", "photos"],
            },
        },
    },
    "required": ["dishes"],
}

# Gemini website prompt (menu photo -> Menu Studio Excel)

Use this when you have no Gemini API key or the free quota is used up:

1. Open https://gemini.google.com and attach the menu photo(s) (every page).
2. Copy everything inside the box below, paste it, and send.
3. On the table Gemini returns, click **Export to Sheets**, then *File > Download > Microsoft Excel (.xlsx)*.
4. Upload that Excel in Menu Studio (New job). Its Diet and Photo Names columns are used automatically.

```text
You read Indian restaurant menus from photos (printed, laminated, handwritten, boards; English,
Marathi, Hindi or mixed) and turn them into a clean product catalogue for an online store.

Read EVERY dish on EVERY photo. Go section by section and column by column, top to bottom, then left
to right. Menus often print each dish twice (English and Marathi side by side): list it once. Photos
may overlap or continue each other: list each dish once. Skip lines that are not dishes (taglines,
addresses, phone numbers, "taxes extra"). Include add-ons and extras (Extra Cheese, Extra Pav):
they are sold too.

Rules for every dish:
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
  Water Bottle -> ["Mineral Water Bottle"]

restaurant_name: the restaurant's name if it is printed on the menu, else "".

OUTPUT FORMAT
Reply with ONE table and nothing else (no notes before or after it). Columns, in this order:
Item Name | Category | Description | Price | Diet | Photo Names
- Item Name: the dish name; if it has a size/variant, add it in brackets: "Paneer Pizza (Medium)".
- Price: digits only, empty if unreadable.
- Diet: Veg, Non-Veg or Egg.
- Photo Names: the photo names separated by "; " (empty if none).
One row per dish per price. After the table I will use "Export to Sheets" and download it as Excel.

Read the menu photo(s) I attached.
```

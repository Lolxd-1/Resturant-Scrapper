# EVAL — live accuracy evidence (AC13), orchestrator visual audit, 2026-09-27

Build: prodv2.0 after TUNE1-3 (before FIX1-3). Real Zomato, real CLIP + OCR, dry run (no upload) except where noted.
Pool at run time: ~155,000 dish photos from ~2,930 restaurants in 20+ cities (seed + live growth).
Every chosen photo was inspected by eye on contact sheets (orchestrator).

| Menu | Dishes | With photo | Coverage | Wrong | Borderline | Notes |
|---|---|---|---|---|---|---|
| Shivraj Biryani House | 18 | 18 | 100% | 0 | 0 | also a REAL job via the app with ImgBB uploads: 18/18 uploaded, sheets built, 2 min |
| H-Food Cafe | 101 | 89 | 88.1% | 0 | 1 | borderline: Irani Maska -> whole bun (not sliced/buttered) |
| Gevravi | 81 | 72 | 88.9% | 1 | 0 | wrong: GEV-040 Paneer Kheema -> paneer-keema toast (menu means the curry) |
| Ganesh Bhojnalaya | 65 | 62 | 95.4% | 0 | 1 | 3 of the 62 are needs_price (menu has no price); borderline: Rice Plate -> plain rice bowl |
| La Pino'z Pizza (chain) | 35 | 34 | 97.1% | 0 | 0 | all 34 = La Pino'z own product photos |
| Domino's Pizza (chain) | 30 | 30 | 100% | 0 | 0 | all 30 = Domino's own product photos |
| **Total** | **330** | **305** | **92.4%** | **1** | **2** | precision 99.7% (99.0% counting borderline as wrong) |

Before v2 (v1 outputs in the repo folder): H-Food had visibly wrong photos (Pineapple shake -> vanilla, Cheese Momos -> branded plain momos, Peri Peri Momos -> other dish), Shivraj had Dum Murgh -> a pizza and Boiled Egg Fry -> sunny-side eggs; every row's category was "Other Food and Grocery".

Brand guard evidence: 2 of 278 first-run picks showed a red "zomato" matchbox prop (OCR "zomato" 0.99996); after TUNE3 the Shivraj "Boiled Egg Fry" pick moved to a clean alternate.

## Uncovered dishes (owner checklist) — 25
| Ganesh_Bhojnalaya | GB-030 | Besan Tadka | Not found on Zomato |
| Ganesh_Bhojnalaya | GB-037 | Gobi Roast | Not found on Zomato |
| Ganesh_Bhojnalaya | GB-049 | Shevga Bhaji (Kala Masala) | Not found on Zomato |
| Gevravi | GEV-014 | Besan Tadka (Tempered Gram Flour) | Not found on Zomato |
| Gevravi | GEV-044 | Soyabean Roast | Not found on Zomato |
| Gevravi | GEV-046 | Gobi Roast | Not found on Zomato |
| Gevravi | GEV-047 | Gobi Kentucky | Not found on Zomato |
| Gevravi | GEV-052 | Shevga Dry (Drumstick Dry) | Not found on Zomato |
| Gevravi | GEV-059 | Nagali Masala Papad | Not found on Zomato |
| Gevravi | GEV-078 | Shevga Bhaji (Kala Masala Special) | Not found on Zomato |
| Gevravi | GEV-079 | Baingan Bhaji (Kala Masala Special) | Not found on Zomato |
| Gevravi | GEV-080 | Soyabean Bhaji (Kala Masala Special) | Not found on Zomato |
| H_Food_Cafe | HFC-026 | Mushroom Mist Pizza - Medium | Not found on Zomato |
| H_Food_Cafe | HFC-027 | Mushroom Mist Pizza - Large | Not found on Zomato |
| H_Food_Cafe | HFC-035 | Paneer & Corn Cheese Burger | Not found on Zomato |
| H_Food_Cafe | HFC-046 | Veg Tikki Cheese Sandwich | Not found on Zomato |
| H_Food_Cafe | HFC-056 | Veg Paradise Pizza (Half) & Paneer Schezwan Pizza (Half) Combo | Combo dish � ask the owner for a photo of the combo |
| H_Food_Cafe | HFC-063 | Fresh Garlic Dough Balls | Not found on Zomato |
| H_Food_Cafe | HFC-069 | Makhani Cheese Maggi | Not found on Zomato |
| H_Food_Cafe | HFC-075 | Makhani Cheese Momos | Not found on Zomato |
| H_Food_Cafe | HFC-098 | Choco Cream Mastani | Not found on Zomato |
| H_Food_Cafe | HFC-099 | Kit-Kat Choco Cream Mastani | Not found on Zomato |
| H_Food_Cafe | HFC-100 | Ceet-B Mastani | Not found on Zomato |
| H_Food_Cafe | HFC-101 | Ceet-M Mastani | Not found on Zomato |
| La_Pinoz_Pizza | LPP-008 | Non Veg Pack Of 4 | Only uncertain matches found (best: Non Veg Pack Of 4 @ La Pino'z Pizza) |

Reading: 23 of 25 are local/house specials with no Zomato equivalent (correct outcome). Residuals worth a follow-up: LPP-008 "Non Veg Pack Of 4" exists on the chain menu but ended "uncertain"; HFC-056 half-and-half combo (by design -> owner photo).

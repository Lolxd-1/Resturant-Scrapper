"""Tests for studio.spelling: look-alike letters, Devanagari, curated/phonetic/glued spellings."""
from __future__ import annotations

import pytest

from studio import spelling
from studio.spelling import Speller, fold_homoglyphs, phonetic_key, transliterate

_WORDS = (
    "butter garlic naan mushroom masala soyabean chilli steam rice schezwan chicken curry anda "
    "boiled bhurji green peas tomato lemon coriander soup tava biryani kulcha chutney besan pitla "
    "paneer crispy crunchy veg kofta jeera tandoori hyderabadi lachha paratha ghee plate half full "
    "keema zaika lajawab matki masoor roast mutton akkha wheat roti dal tikka lassi thali misal "
    "vada pav bhaji kolhapuri malvani handi"
).split()
VOCAB = {w: 20 for w in _WORDS}

GOLDEN = [
    ("BATER GARLIK NAN", "butter garlic naan"),
    ("MASHRUM MASALA", "mushroom masala"),
    ("SOYABIN CHILLI", "soyabean chilli"),
    ("SEZVAN RICE", "schezwan rice"),
    ("CHICKEN KARI", "chicken curry"),
    ("ANDAKARI", "anda curry"),
    ("BOILANDA BHURJI", "boiled anda bhurji"),
    ("GREENPIS TOMATO", "green peas tomato"),
    ("LEMAN CORIUNDER SOUP", "lemon coriander soup"),
    ("CHECKEN TAVA BIRYANI", "chicken tava biryani"),
    ("KULCHCHHA", "kulcha"),
    ("TOMATO CHATANI", "tomato chutney"),
    ("BESAN PITAL", "besan pitla"),
    ("PANEER CRESPI", "paneer crispy"),
    ("VEG KOPHTA", "veg kofta"),
    ("JIRA RICE", "jeera rice"),
    ("TANDURI ROTI", "tandoori roti"),
    ("HAIDRABADI BIRYANI", "hyderabadi biryani"),
    ("HYDRABADI BIRYANI", "hyderabadi biryani"),
    ("CRANCHI PANEER", "crunchy paneer"),
    ("CRANCHY PANEER", "crunchy paneer"),
    ("LACHCHHA PARATHA", "lachha paratha"),
    ("LACHA PARATHA", "lachha paratha"),
    ("GHI ROTI", "ghee roti"),
    ("MUTTON PLET", "mutton plate"),
    ("MUTTON THALI HAF", "mutton thali half"),
    ("MUTTON THALI FUL", "mutton thali full"),
    ("MUTTON KHIMA", "mutton keema"),
    ("CHICKEN JAYKA", "chicken zaika"),
    ("CHICKEN JAIKA", "chicken zaika"),
    ("PANEER LAJVAB", "paneer lajawab"),
    ("PANEER LAJAWAAB", "paneer lajawab"),
    ("MATAKI MASALA", "matki masala"),
    ("MASUR MASALA", "masoor masala"),
    ("CHICKEN ROST", "chicken roast"),
    ("PANNER TIKKA", "paneer tikka"),
    ("PANIR TIKKA", "paneer tikka"),
    ("MATAN AKHKHA", "mutton akkha"),
    ("MUTTAN BIRYANI", "mutton biryani"),
    ("CHIKEN CRISPI", "chicken crispy"),
    ("CHIKAN TIKKA", "chicken tikka"),
    ("SHEZWAN RICE", "schezwan rice"),
    ("SCHZWAN RICE", "schezwan rice"),
    ("MASHROOM MASALA", "mushroom masala"),
    ("MUSHRUM MASALA", "mushroom masala"),
    ("SOYABEEN CHILLI", "soyabean chilli"),
    ("CHICKEN KARRI", "chicken curry"),
    ("TOMATO CHATNI", "tomato chutney"),
    ("BESAN PITHAL", "besan pitla"),
    ("KULCHHA", "kulcha"),
    ("BATTAR NAN", "butter naan"),
    ("CORIANDAR SOUP", "coriander soup"),
    ("VIT ROTI", "wheat roti"),
    ("HARBHARA KABAB", "hara bhara kabab"),
]


@pytest.mark.parametrize("raw, fixed", GOLDEN)
def test_tc1_golden_table(raw, fixed):
    assert Speller(VOCAB).fix_text(raw) == fixed


def test_tc1_steam_rice_keeps_brackets():
    assert "steam rice" in Speller(VOCAB).fix_text("STIM RICE (Small)")
    assert Speller(VOCAB).fix_text("STIM RICE (Small)") == "steam rice (small)"


MUST_NOT_CHANGE = ["masala", "paneer", "chilli", "tikka", "lassi", "roti", "thali", "misal", "vada",
                   "pav", "dal", "bhaji", "kolhapuri", "malvani", "handi", "jeera", "kulcha", "naan"]


@pytest.mark.parametrize("word", MUST_NOT_CHANGE)
def test_tc2_known_words_never_change(word):
    speller = Speller(VOCAB)
    assert speller.correct(word) is None
    assert speller.fix_text(word.upper()) == word


def test_tc2_short_and_digit_words_unchanged():
    speller = Speller({"pav": 20, "up": 20, "ab": 20, "abc": 20})
    for word in ("ab", "x", "pa", "7up", "5pc"):
        assert speller.correct(word) is None
    assert speller.fix_text("7UP 500 ML") == "7up 500 ml"


def test_tc3_phonetic_correction(monkeypatch):
    monkeypatch.delitem(spelling.MISSPELLINGS, "mashrum")
    assert phonetic_key("mashrum") == phonetic_key("mushroom") == "msrm"
    assert phonetic_key("bater") == phonetic_key("butter") == "btr"
    assert phonetic_key("kulchchha") == phonetic_key("kulcha") == "klc"
    assert Speller({"mushroom": 50, "masala": 40}).correct("mashrum") == "mushroom"


def test_tc3_ambiguous_phonetic_is_left_alone():
    # "kima" sounds like both, and neither is clearly more common
    assert Speller({"keema": 30, "kama": 25}).correct("kima") is None
    assert Speller({"keema": 30, "kama": 5}).correct("kima") == "keema"


def test_tc4_transliterate():
    assert transliterate("चिकन हंडी (हाफ)") == "chicken handi (half)"
    assert transliterate("मालवाणी चिकन ड्राय हंडी (फुल)") == "malvani chicken dry handi (full)"
    assert transliterate("व्हेज थाळी") == "veg thali"
    assert transliterate("स्पे. चिकन थाळी") == "special chicken thali"
    assert transliterate("पनीर टिक्का") == "paneer tikka"
    unknown = transliterate("गावकरी")
    assert unknown and unknown.isascii() and unknown.isalpha()
    assert transliterate("Butter Naan (Half)") == "Butter Naan (Half)"


def test_tc5_homoglyphs():
    assert fold_homoglyphs("PANEER CHАТРАТА") == "PANEER CHATPATA"
    assert Speller(VOCAB).fix_text("PANEER CHАТРАТА") == "paneer chatpata"

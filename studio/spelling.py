"""Read dish names the way local menus write them: look-alike letters, Devanagari script,
phonetic spellings and glued words become the plain English words the pool uses."""
from __future__ import annotations

import re
from typing import Mapping

from rapidfuzz.distance import Levenshtein

from studio.lexicon import NOISE, NON_VISUAL, PHRASES, SYNONYMS

# Cyrillic / Greek letters that look Latin (menus copied from phones and PDFs)
HOMOGLYPHS: dict[str, str] = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "Х": "X", "У": "Y", "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o", "ν": "v",
}
_HOMOGLYPH_TABLE = str.maketrans(HOMOGLYPHS)


def fold_homoglyphs(text: str) -> str:
    return text.translate(_HOMOGLYPH_TABLE)


DEVANAGARI_WORDS: dict[str, str] = {
    "चिकन": "chicken", "मटन": "mutton", "मटण": "mutton", "हंडी": "handi", "हांडी": "handi",
    "थाळी": "thali", "थाली": "thali", "मालवाणी": "malvani", "ड्राय": "dry", "स्पेशल": "special",
    "स्पे.": "special", "हाफ": "half", "फुल": "full", "प्लेट": "plate", "कंदुरी": "kanduri",
    "राजाराणी": "rajarani", "व्हेज": "veg", "मांसाहारी": "nonveg", "शाकाहारी": "veg",
    "पनीर": "paneer", "भाजी": "bhaji", "वडा": "vada", "पाव": "pav", "मिसळ": "misal",
    "पोहे": "poha", "भात": "bhat", "चपाती": "chapati", "भाकरी": "bhakri", "अंडा": "anda",
    "अंडी": "anda", "बिर्याणी": "biryani", "बिर्यानी": "biryani", "रस्सा": "rassa",
    "सुका": "sukka", "सुकं": "sukka", "तांबडा": "tambda", "पांढरा": "pandhra", "फ्राय": "fry",
    "मसाला": "masala", "कोल्हापुरी": "kolhapuri", "डाळ": "dal", "दाल": "dal", "पिठलं": "pithla",
    "पिठले": "pithla", "शेव": "shev", "लस्सी": "lassi", "ताक": "taak", "दही": "dahi",
    "वरण": "varan", "आमटी": "amti", "कोंबडी": "kombdi", "मच्छी": "machhi", "सोलकढी": "solkadhi",
    "भरीत": "bharit", "झुणका": "zunka", "उसळ": "usal", "राडा": "rada",
}

_DEV_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ru", "ए": "e",
    "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
_DEV_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j",
    "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
    "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
    "म": "m", "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v", "श": "sh", "ष": "sh",
    "स": "s", "ह": "h",
}
_DEV_SIGNS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ru", "े": "e", "ै": "ai",
    "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
_DEV_MARKS = {"ं": "n", "ँ": "n", "ः": "h", "।": ".", "॥": "."}
_VIRAMA, _NUKTA = "्", "़"
_DEV_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}

_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_DEV_RUN_RE = re.compile(r"[ऀ-ॿ]+")
_DEV_WORDS_RE = re.compile(
    r"(?<![ऀ-ॿ])("
    + "|".join(re.escape(k) for k in sorted(DEVANAGARI_WORDS, key=len, reverse=True))
    + r")(?![ऀ-ॿ])"
)


def _in_word(ch: str) -> bool:
    return bool(_DEVANAGARI_RE.match(ch)) and ch not in _DEV_DIGITS and ch not in ("।", "॥")


def _transliterate_run(run: str) -> str:
    out: list[str] = []
    pending_a = False
    for i, ch in enumerate(run):
        if ch == _NUKTA:
            continue
        if pending_a:
            pending_a = False
            if ch == _VIRAMA or ch in _DEV_SIGNS:
                nxt = run[i + 1:i + 2]
                # a word-final long "aa" is written "a" in menus ("टिक्का" -> "tikka")
                out.append("a" if ch == "ा" and not (nxt and _in_word(nxt)) else _DEV_SIGNS.get(ch, ""))
                continue
            out.append("a")
        if ch in _DEV_CONSONANTS:
            out.append(_DEV_CONSONANTS[ch])
            nxt = run[i + 1:].lstrip(_NUKTA)[:1]
            # the inherent vowel of a word's last consonant is not spoken ("चिकन" -> "chikan")
            pending_a = bool(nxt) and _in_word(nxt)
        else:
            out.append(_DEV_VOWELS.get(ch) or _DEV_SIGNS.get(ch) or _DEV_MARKS.get(ch) or _DEV_DIGITS.get(ch, ""))
    return "".join(out)


def transliterate(text: str) -> str:
    if not _DEVANAGARI_RE.search(text):
        return text
    text = _DEV_WORDS_RE.sub(lambda m: DEVANAGARI_WORDS[m.group(1)], text)
    return _DEV_RUN_RE.sub(lambda m: _transliterate_run(m.group(0)), text)


# curated: lowercase word -> lowercase replacement (applied before anything else)
MISSPELLINGS: dict[str, str] = {
    "bater": "butter", "battar": "butter", "jira": "jeera", "stim": "steam", "sezvan": "schezwan",
    "shezwan": "schezwan", "schzwan": "schezwan", "mashrum": "mushroom", "mashroom": "mushroom",
    "mushrum": "mushroom", "soyabin": "soyabean", "soyabeen": "soyabean", "kari": "curry",
    "karri": "curry", "tanduri": "tandoori", "haidrabadi": "hyderabadi", "hydrabadi": "hyderabadi",
    "chatani": "chutney", "chatni": "chutney", "pital": "pitla", "pithal": "pitla",
    "crispi": "crispy", "crespi": "crispy", "cranchi": "crunchy", "cranchy": "crunchy",
    "pis": "peas", "garlik": "garlic", "kulchchha": "kulcha", "kulchha": "kulcha",
    "lachchha": "lachha", "lacha": "lachha", "ghi": "ghee", "plet": "plate", "haf": "half",
    "ful": "full", "leman": "lemon", "coriunder": "coriander", "coriandar": "coriander",
    "khima": "keema", "kophta": "kofta", "jayka": "zaika", "jaika": "zaika", "lajvab": "lajawab",
    "lajawaab": "lajawab", "mataki": "matki", "masur": "masoor", "rost": "roast",
    "panner": "paneer", "panir": "paneer", "checken": "chicken", "chiken": "chicken",
    "chikan": "chicken", "matan": "mutton", "muttan": "mutton", "akhkha": "akkha",
    "boil": "boiled", "nan": "naan", "vit": "wheat", "harbhara": "hara bhara",
    "harabhara": "hara bhara",
}

_PHONETIC_STEPS = (
    ("chh", "c"), ("ch", "c"), ("ph", "f"), ("sh", "s"), ("kh", "k"), ("gh", "g"), ("th", "t"),
    ("dh", "d"), ("bh", "b"), ("jh", "j"), ("ck", "k"), ("q", "k"), ("x", "ks"), ("w", "v"),
    ("z", "j"), ("ee", "i"), ("oo", "u"),
)
_VOWELS = frozenset("aeiouy")
_FIRST_GROUP = {"k": "c", "q": "c", "z": "j", "w": "v"}
_WORD_RE = re.compile(r"[a-z0-9]+")
_KNOWN_DF, _SPLIT_DF = 2, 5


def _sound(word: str) -> str:
    s = word.lower()
    for old, new in _PHONETIC_STEPS:
        s = s.replace(old, new)
    return s


def phonetic_key(word: str) -> str:
    s = _sound(word)
    if not s:
        return ""
    kept = s[0] + "".join(c for c in s[1:] if c not in _VOWELS)
    return re.sub(r"(.)\1+", r"\1", kept)


def _first_group(word: str) -> str:
    return _FIRST_GROUP.get(word[0], word[0])


class Speller:
    def __init__(self, vocab: Mapping[str, int]):
        self.vocab = vocab
        self._lexicon = frozenset(SYNONYMS) | frozenset(PHRASES) | NOISE | NON_VISUAL
        common = [(w, df) for w, df in vocab.items() if df >= _SPLIT_DF]
        self._by_key: dict[str, list[tuple[str, int]]] = {}
        for w, df in common:
            self._by_key.setdefault(phonetic_key(w), []).append((w, df))

    def _split(self, word: str) -> str | None:
        def part_df(part: str) -> int | None:
            if part in MISSPELLINGS:
                return max(self.vocab.get(MISSPELLINGS[part], 0), _SPLIT_DF)
            df = self.vocab.get(part, 0)
            return df if df >= _SPLIT_DF else None

        best: tuple[int, int, list[str]] | None = None
        n = len(word)
        splits = [[word[:i], word[i:]] for i in range(3, n - 2)]
        splits += [[word[:i], word[i:j], word[j:]] for i in range(3, n - 5) for j in range(i + 3, n - 2)]
        for parts in splits:
            dfs = [part_df(p) for p in parts]
            if None in dfs:
                continue
            rank = (-len(parts), min(dfs))
            if best is None or rank > best[:2]:
                best = (*rank, parts)
        if best is None:
            return None
        return " ".join(MISSPELLINGS.get(p, p) for p in best[2])

    def _phonetic(self, word: str) -> str | None:
        limit = 1 if len(word) <= 5 else 2
        sound, group = _sound(word), _first_group(word)
        found = sorted(
            ((w, df) for w, df in self._by_key.get(phonetic_key(word), ())
             if w != word and _first_group(w) == group
             and Levenshtein.distance(sound, _sound(w)) <= limit),
            key=lambda c: -c[1],
        )
        if not found:
            return None
        if len(found) > 1 and found[1][1] >= 0.5 * found[0][1]:
            return None  # two pool words sound alike: do not guess
        return found[0][0]

    def correct(self, word: str) -> str | None:
        word = word.lower()
        if len(word) < 3 or any(c.isdigit() for c in word):
            return None
        if word in MISSPELLINGS:
            return MISSPELLINGS[word]
        if self.vocab.get(word, 0) >= _KNOWN_DF or word in self._lexicon:
            return None
        return self._split(word) or self._phonetic(word)

    def fix_text(self, text: str) -> str:
        """Lowercased text with every misspelled word replaced; brackets and punctuation kept."""
        s = " ".join(transliterate(fold_homoglyphs(text or "")).lower().split())
        return _WORD_RE.sub(lambda m: self.correct(m.group(0)) or m.group(0), s)

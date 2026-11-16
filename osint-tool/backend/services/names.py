"""Name handling for record linkage: cross-script keys, rarity, variants.

The same Uzbek name is written many ways online: Latin (Abdubaniyev),
Cyrillic (Абдубаниев), Russian-style Latin (Abdubaniev), with or without the
patronymic, family name first or last. `name_key` maps all of those to one
comparable key so "the same name" is detected across spellings, and
`name_bits` says how much a name match is worth: two "Aziz Karimov"s are
common, two "Lutfullo Abdubaniyev"s are not.
"""

from __future__ import annotations

import re
import unicodedata

_APOSTROPHES = re.compile("[ʻʼ’‘`´']")

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q",
    "ғ": "g", "ҳ": "h", "і": "i", "ї": "i", "є": "e",
}

# Ordered rewrites that fold Uzbek-Latin, Russian-Latin and English spellings
# of one sound onto a single letter sequence.
_FOLDS = [
    ("dzh", "j"), ("dj", "j"), ("zh", "j"), ("kh", "h"), ("x", "h"),
    ("q", "k"), ("w", "v"), ("ph", "f"), ("iy", "i"), ("ye", "e"),
    ("yo", "o"), ("yu", "u"), ("ya", "a"), ("ck", "k"), ("c", "k"),
]
_DOUBLE_RE = re.compile(r"(.)\1+")

# Patronymics and connectors that do not identify the person on their own.
_PATRONYMIC_RE = re.compile(r"(ovich|evich|ovna|evna|ogli|ugli|kizi|qizi)$")
_CONNECTORS = {"ogli", "ugli", "kizi", "qizi", "bin", "ibn", "van", "von", "de", "al"}

# Folded keys of very common first names and family names (Uzbek, Russian,
# English). A match on these says little; a match on anything else says more.
_COMMON_TOKENS = {
    # first names
    "aziz", "alisher", "akmal", "anvar", "bobur", "bekzod", "dilshod", "doniyor",
    "doner", "farhod", "jasur", "javohir", "jamshid", "kamol", "mansur", "murod",
    "nodir", "otabek", "rustam", "sardor", "sherzod", "shuhrat", "ulugbek",
    "umid", "zafar", "abdula", "muhamad", "muhammad", "ali", "ahmad", "said",
    "nilufar", "dilnoza", "gulnora", "madina", "malika", "nigora", "shahnoza",
    "zarina", "aleksandr", "alexander", "sergei", "sergey", "andrei", "andrey",
    "dmitri", "dmitry", "ivan", "elena", "olga", "natalia", "tatiana", "anna",
    "maria", "john", "james", "michael", "david", "robert", "william", "mary",
    "jennifer", "linda", "daniel", "thomas", "paul", "mark",
    # family names (folded: Karimov/Каримов -> karimov, Aliyev -> aliev)
    "karimov", "karimova", "aliev", "alieva", "rahimov", "rahimova", "usmanov",
    "usmanova", "toshmatov", "ismoilov", "ismailov", "abdulaev", "abdulaeva",
    "ahmedov", "ahmedova", "hasanov", "hasanova", "yusupov", "yusupova",
    "sultonov", "nazarov", "nazarova", "rashidov", "mirzaev", "salimov",
    "ergashev", "tursunov", "kodirov", "kodirova", "saidov", "saidova",
    "ivanov", "ivanova", "smirnov", "smirnova", "kuznetsov", "popov", "petrov",
    "sokolov", "smith", "johnson", "williams", "brown", "jones", "garcia",
    "miller", "davis", "wilson", "taylor", "lee", "khan", "kim",
}

# Folded city spellings -> one canonical place, so Toshkent / Ташкент /
# Tashkent do not read as a contradiction.
_PLACE_ALIASES = {
    "toshkent": "tashkent", "tashkent": "tashkent", "taskent": "tashkent",
    "samarkand": "samarkand", "samarkant": "samarkand",
    "buhoro": "bukhara", "buhara": "bukhara",
    "namangan": "namangan",
    "andijon": "andijan", "andijan": "andijan",
    "fargona": "fergana", "fergana": "fergana", "ferghana": "fergana",
    "nukus": "nukus", "karshi": "karshi", "karsi": "karshi",
    "termiz": "termez", "termez": "termez",
    "jizah": "jizzakh", "jizak": "jizzakh",
    "navoi": "navoi", "urganch": "urgench", "urgench": "urgench",
    "guliston": "gulistan", "gulistan": "gulistan",
    "uzbekistan": "uzbekistan", "ozbekiston": "uzbekistan", "uzbekiston": "uzbekistan",
}


def fold(text: str) -> str:
    """One word -> a script- and spelling-independent letter key."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = "".join(_CYR_TO_LAT.get(ch, ch) for ch in text)
    text = _APOSTROPHES.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z]", "", text)
    for src, dst in _FOLDS:
        text = text.replace(src, dst)
    text = _DOUBLE_RE.sub(r"\1", text)
    # Uzbek -llo / Russian -lla (Lutfullo / Лутфулла, Abdullo / Abdulla)
    if text.endswith("lo"):
        text = text[:-1] + "a"
    return text


def name_tokens(name: str) -> frozenset[str]:
    """Identifying tokens of a full name, order-free, patronymic dropped."""
    tokens = set()
    for word in re.split(r"[\s,.\-_/]+", str(name or "")):
        key = fold(word)
        if len(key) < 2 or key in _CONNECTORS or _PATRONYMIC_RE.search(key):
            continue
        tokens.add(key)
    return frozenset(tokens)


def names_match(a: str, b: str) -> frozenset[str]:
    """The shared tokens if two names denote the same full name, else empty.

    At least two tokens must agree and the shorter name must be contained in
    the longer one: "Shavkat Miromonovich Mirziyoyev" matches "Shavkat
    Mirziyoyev"; "Aziz Karimov" does not match "Aziz Rahimov".
    """
    ta, tb = name_tokens(a), name_tokens(b)
    common = ta & tb
    if len(common) >= 2 and common == (ta if len(ta) <= len(tb) else tb):
        return common
    return frozenset()


def name_bits(tokens: frozenset[str]) -> float:
    """Evidence weight of a full-name match: common names are cheap."""
    bits = sum(0.4 if t in _COMMON_TOKENS else 1.0 for t in tokens)
    return round(min(bits, 2.5), 2)


def is_common_token(token: str) -> bool:
    return fold(token) in _COMMON_TOKENS


def place_key(text: str) -> frozenset[str]:
    """Canonical places mentioned in a location string."""
    keys = set()
    for word in re.split(r"[\s,;/()\-]+", str(text or "")):
        key = fold(word)
        if len(key) >= 3:
            keys.add(_PLACE_ALIASES.get(key, key))
    return frozenset(keys)


def places_conflict(a: str, b: str) -> bool:
    """Two stated locations that share no place at all.

    "Namangan" vs "Наманган, Uzbekistan" agree; "Tashkent" vs "London, UK"
    conflict. Containment counts as agreement (a city inside its country).
    """
    ka, kb = place_key(a), place_key(b)
    return bool(ka) and bool(kb) and not (ka & kb)


def username_variants(name: str, birth_year: int | None = None, limit: int = 8) -> list[str]:
    """Plausible handles built from a full name — leads to check, not facts."""
    words = [fold_ascii(w) for w in str(name or "").split()]
    words = [w for w in words if len(w) >= 2 and not _PATRONYMIC_RE.search(fold(w))]
    if len(words) < 2:
        return []
    first, last = words[0], words[-1]
    out = [
        f"{first}{last}", f"{first}.{last}", f"{first}_{last}",
        f"{last}{first}", f"{first[0]}{last}", f"{first}.{last[0]}",
        f"{last}.{first}", f"{first}{last[0]}",
    ]
    if birth_year:
        yy = str(birth_year)[-2:]
        out[2:2] = [f"{first}{last}{yy}", f"{first}_{last}{birth_year}"]
    seen, unique = set(), []
    for handle in out:
        if 3 <= len(handle) <= 30 and handle not in seen:
            seen.add(handle)
            unique.append(handle)
    return unique[:limit]


def fold_ascii(word: str) -> str:
    """A word as plain ASCII letters (Cyrillic transliterated, apostrophes gone),
    without the phonetic folding: what people actually type into handles."""
    text = unicodedata.normalize("NFKC", str(word or "")).casefold()
    text = "".join(_CYR_TO_LAT.get(ch, ch) for ch in text)
    text = _APOSTROPHES.sub("", text)
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z0-9]", "", "".join(ch for ch in text if not unicodedata.combining(ch)))

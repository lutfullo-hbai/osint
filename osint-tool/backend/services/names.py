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


# 10.5b: countries and large regions. A town and a country (or state) that are
# not both named in one string cannot be compared without a gazetteer, so
# "Los Angeles" vs "United States" is unknown, not a conflict. Several-word names
# and abbreviations become one key first, so "United Kingdom" and "United States"
# no longer agree through "united".
_COUNTRY_PHRASES = {
    "united states of america": "usa", "united states": "usa", "u.s.a.": "usa", "u.s.": "usa", "usa": "usa",
    "united kingdom": "britain", "great britain": "britain", "u.k.": "britain", "uk": "britain",
    "united arab emirates": "emirates", "uae": "emirates",
    "south korea": "southkorea", "north korea": "northkorea", "new zealand": "newzealand",
    "saudi arabia": "saudiarabia", "south africa": "southafrica", "czech republic": "czechia",
    "sri lanka": "srilanka", "costa rica": "costarica", "hong kong": "hongkong",
    "silicon valley": "siliconvalley", "bay area": "bayarea", "new york state": "newyorkstate",
    "new jersey": "newjersey", "new mexico": "newmexico", "new hampshire": "newhampshire",
    "north carolina": "northcarolina", "south carolina": "southcarolina", "north dakota": "northdakota",
    "south dakota": "southdakota", "west virginia": "westvirginia", "rhode island": "rhodeisland",
    "british columbia": "britishcolumbia",
    # several-word towns, one key each (so "New York" and "New Delhi" share nothing)
    "new york city": "newyork", "new york": "newyork", "nyc": "newyork", "los angeles": "losangeles",
    "san francisco": "sanfrancisco", "mountain view": "mountainview", "palo alto": "paloalto",
    "san jose": "sanjose", "san diego": "sandiego", "santa clara": "santaclara", "las vegas": "lasvegas",
    "salt lake city": "saltlakecity", "tel aviv": "telaviv", "abu dhabi": "abudhabi", "new delhi": "newdelhi",
    "rio de janeiro": "riodejaneiro", "sao paulo": "saopaulo", "buenos aires": "buenosaires",
    "kuala lumpur": "kualalumpur", "cape town": "capetown", "mexico city": "mexicocity",
    "saint petersburg": "petersburg", "st. petersburg": "petersburg", "st petersburg": "petersburg",
    "sankt peterburg": "petersburg", "nizhny novgorod": "nizhnynovgorod",
}
_COUNTRY_PHRASE_RE = re.compile(
    r"(?<![\w.])(" + "|".join(re.escape(p) for p in sorted(_COUNTRY_PHRASES, key=len, reverse=True)) + r")(?![\w])",
    re.IGNORECASE)
_REGION_WORDS = (
    # countries
    "afghanistan albania algeria argentina armenia australia austria azerbaijan bahrain bangladesh belarus "
    "belgium bolivia bosnia brazil bulgaria cambodia cameroon canada chile china colombia croatia cuba cyprus "
    "denmark ecuador egypt estonia ethiopia finland france georgia germany ghana greece hungary iceland india "
    "indonesia iran iraq ireland israel italy japan jordan kazakhstan kenya kuwait kyrgyzstan laos latvia "
    "lebanon libya lithuania luxembourg malaysia mexico moldova mongolia montenegro morocco nepal netherlands "
    "nigeria norway oman pakistan palestine panama paraguay peru philippines poland portugal qatar romania "
    "russia serbia singapore slovakia slovenia spain sweden switzerland syria taiwan tajikistan tanzania "
    "thailand tunisia turkey turkmenistan uganda ukraine uruguay uzbekistan venezuela vietnam yemen zambia "
    "zimbabwe england scotland wales holland deutschland rossiya ozbekiston uzbekiston qozogiston "
    "kazakstan turkiya "
    # states and provinces that people write instead of a town
    "alabama alaska arizona arkansas california colorado connecticut delaware florida hawaii idaho illinois "
    "indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi "
    "missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont virginia "
    "washington wisconsin wyoming ontario quebec alberta manitoba bavaria"
).split()
# words that name no place by themselves ("New York" and "New Delhi" share only "new")
_PLACE_STOP = {"new", "san", "los", "las", "saint", "sankt", "city", "the", "of", "de", "del", "la", "el",
               "north", "south", "east", "west", "greater", "area", "metro", "region"}


def place_key(text: str) -> frozenset[str]:
    """Canonical places mentioned in a location string."""
    text = _COUNTRY_PHRASE_RE.sub(lambda m: " " + _COUNTRY_PHRASES[m.group(1).lower()] + " ", str(text or ""))
    keys = set()
    for word in re.split(r"[\s,;/()\-]+", text):
        key = fold(word)
        if len(key) >= 3 and key not in _PLACE_STOP_KEYS:
            keys.add(_PLACE_ALIASES.get(key, key))
    return frozenset(keys)


_PLACE_STOP_KEYS = {fold(w) for w in _PLACE_STOP}

# A small gazetteer: towns whose country is not in doubt, so "Portland" vs
# "Italy" conflicts and "Los Angeles" vs "United States" agrees. A town that
# is not listed (or is ambiguous, like Cambridge) stays unknown against a country.
_TOWN_COUNTRY = {
    "uzbekistan": "tashkent samarkand bukhara namangan andijan fergana nukus karshi termez jizzakh navoi "
                  "urgench gulistan kokand margilan chirchiq angren",
    "usa": "newyork losangeles sanfrancisco mountainview paloalto sanjose sandiego santaclara lasvegas "
           "saltlakecity seattle portland boston chicago austin denver atlanta miami houston dallas "
           "philadelphia pittsburgh berkeley stanford cupertino sunnyvale redmond oakland brooklyn "
           "manhattan detroit baltimore minneapolis",
    "russia": "moscow moskva petersburg kazan novosibirsk yekaterinburg nizhnynovgorod samara",
    "kazakhstan": "almaty astana shymkent",
    "britain": "london manchester edinburgh glasgow birmingham bristol",
    "france": "paris lyon marseille toulouse", "germany": "berlin munich hamburg frankfurt cologne",
    "spain": "madrid barcelona", "italy": "rome milan turin naples", "netherlands": "amsterdam rotterdam",
    "switzerland": "zurich geneva", "austria": "vienna", "czechia": "prague", "poland": "warsaw krakow",
    "ukraine": "kyiv kiev kharkiv odesa", "turkey": "istanbul ankara", "emirates": "dubai abudhabi",
    "japan": "tokyo osaka kyoto", "southkorea": "seoul busan", "china": "beijing shanghai shenzhen",
    "india": "bangalore bengaluru mumbai newdelhi delhi hyderabad chennai pune", "israel": "telaviv",
    "australia": "sydney melbourne brisbane", "canada": "toronto vancouver montreal ottawa",
    "brazil": "riodejaneiro saopaulo", "argentina": "buenosaires", "malaysia": "kualalumpur",
    "southafrica": "capetown johannesburg", "mexico": "mexicocity", "egypt": "cairo", "nigeria": "lagos",
    "kenya": "nairobi", "indonesia": "jakarta", "thailand": "bangkok", "vietnam": "hanoi",
    "philippines": "manila", "pakistan": "karachi lahore", "iran": "tehran", "azerbaijan": "baku",
    "georgia": "tbilisi", "armenia": "yerevan", "belarus": "minsk", "kyrgyzstan": "bishkek",
    "tajikistan": "dushanbe", "turkmenistan": "ashgabat",
}
# the several-word keys above that are countries or states (the rest are towns)
_REGION_PHRASE_KEYS = (
    "usa britain emirates southkorea northkorea newzealand saudiarabia southafrica czechia srilanka "
    "costarica hongkong siliconvalley bayarea newyorkstate newjersey newmexico newhampshire northcarolina "
    "southcarolina northdakota southdakota westvirginia rhodeisland britishcolumbia").split()
_REGION_KEYS = frozenset(_PLACE_ALIASES.get(fold(w), fold(w)) for w in _REGION_WORDS + _REGION_PHRASE_KEYS)


_TOWN_TO_COUNTRY = {_PLACE_ALIASES.get(fold(t), fold(t)): fold(country)
                    for country, towns in _TOWN_COUNTRY.items() for t in towns.split()}


_US_STATES = (
    "alabama alaska arizona arkansas california colorado connecticut delaware florida hawaii idaho illinois "
    "indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi "
    "missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont virginia "
    "washington wisconsin wyoming newjersey newmexico newhampshire northcarolina southcarolina northdakota "
    "southdakota westvirginia rhodeisland newyorkstate siliconvalley bayarea").split()
# a state or another name of a country -> the country
_REGION_PARENT = {fold(k): fold(v) for k, v in [
    *((st, "usa") for st in _US_STATES),
    *((pr, "canada") for pr in ("ontario", "quebec", "alberta", "manitoba", "britishcolumbia")),
    ("england", "britain"), ("scotland", "britain"), ("wales", "britain"), ("bavaria", "germany"),
    ("holland", "netherlands"), ("deutschland", "germany"), ("rossiya", "russia"), ("qozogiston", "kazakhstan"),
    ("kazakstan", "kazakhstan"), ("turkiya", "turkey")]}


def _regions(keys: frozenset[str]) -> frozenset[str]:
    """The countries/states a location names, or else those of its known towns."""
    named = keys & _REGION_KEYS
    return named or frozenset(_TOWN_TO_COUNTRY[k] for k in keys if k in _TOWN_TO_COUNTRY)


def _up(regions: frozenset[str]) -> frozenset[str]:
    """Regions plus the countries they lie in (California -> California, USA)."""
    return regions | {_REGION_PARENT[r] for r in regions if r in _REGION_PARENT}


def place_relation(a: str, b: str) -> str:
    """"agree", "conflict" or "unknown" for two stated locations.

    "Namangan" vs "Наманган, Uzbekistan" agree (a shared place), and so do
    "Los Angeles" and "United States" (a known town inside the country).
    "Tashkent" vs "London, UK" conflict, and so do two different towns even
    in one country (Portland vs Seattle): a shared country makes two towns
    no closer. A country vs a town we cannot place is unknown.
    """
    ka, kb = place_key(a), place_key(b)
    if not ka or not kb:
        return "unknown"
    if ka & kb:
        return "agree"
    only_region_a, only_region_b = ka <= _REGION_KEYS, kb <= _REGION_KEYS
    if not (only_region_a or only_region_b):
        return "conflict"                       # two different towns
    if only_region_a and only_region_b:         # California vs USA agree, California vs Texas do not
        return "agree" if ka <= _up(kb) or kb <= _up(ka) else "conflict"
    region, other = (ka, kb) if only_region_a else (kb, ka)
    where = _regions(other)                     # what the town side names or is known to lie in
    if not where:
        return "unknown"                        # a town we cannot place
    if region <= _up(where):
        return "agree"                          # Los Angeles is in the USA
    if where <= _up(region):
        return "unknown"                        # Mountain View (USA) vs California: cannot tell
    return "conflict"


def places_conflict(a: str, b: str) -> bool:
    """Two stated locations that clearly name different places."""
    return place_relation(a, b) == "conflict"


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

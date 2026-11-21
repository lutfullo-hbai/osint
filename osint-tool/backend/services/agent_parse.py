"""Free-text request parser for Agent mode (ROADMAP 6.1).

"lutfullo abdubaniyev 19 yosh namangandan" ->
    name "Lutfullo Abdubaniyev", age 19 (born ~2006-2007), place Namangan.

Rule-based and deterministic: every value it returns is literally present in
the text (no model guesses), so the agent never searches for something the
user did not say. Understands Uzbek (Latin and Cyrillic), Russian and English
phrasing for age, birth year and home town.
"""
from __future__ import annotations

import re
from datetime import date

from services.correlate import handle_from_url
from services.names import fold

MAX_NAME_TOKENS = 4
MAX_TEXT = 500

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?:/[^\s,;]*)?")
_PHONE_RE = re.compile(r"(?<![\w@])\+?\d[\d\s()\-]{7,}\d(?!\w)")
_HANDLE_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_.]{3,32})\b")

_AGE_WORDS = (r"yosh(?:da|li|lik|ga|im)?|ёш(?:да|ли)?|years?(?:\s+old)?|y\.?\s?o\.?|yo|"
              r"лет|года?|годиков")
_AGE_RE = re.compile(rf"(?<!\d)(\d{{1,2}})\s*(?:-|\s)?\s*(?:{_AGE_WORDS})(?![a-zа-я])", re.IGNORECASE)
_AGE_PREFIX_RE = re.compile(r"(?:aged?|yoshi|возраст)\s*:?\s*(\d{1,2})(?!\d)", re.IGNORECASE)
_YEAR_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*(?:-?\s*(?:yil(?:da|i)?|йил(?:да)?|г\.?|года?|yilgi))?"
    r"(?:\s*(?:tug['ʻ’`]?il(?:gan)?|туғилган|рождения|born))?",
    re.IGNORECASE,
)
_BORN_BEFORE_RE = re.compile(r"(?:born|tug['ʻ’`]?ilgan|родил(?:ся|ась)|р\.)\s*(?:in\s+)?((?:19|20)\d{2})",
                             re.IGNORECASE)

# Folded place stem -> display name. Uzbek regions, regional centres and
# larger towns, plus a few neighbours people often name.
_PLACES = {
    "toshkent": "Tashkent", "tashkent": "Tashkent", "tashkient": "Tashkent",
    "namangan": "Namangan", "andijon": "Andijan", "andijan": "Andijan",
    "fargona": "Fergana", "fergana": "Fergana", "ferghana": "Fergana",
    "samarkand": "Samarkand", "samarqand": "Samarkand", "buhoro": "Bukhara",
    "buhara": "Bukhara", "bukhara": "Bukhara", "navoi": "Navoi", "navoiy": "Navoi",
    "jizah": "Jizzakh", "jizzakh": "Jizzakh", "jizak": "Jizzakh",
    "guliston": "Gulistan", "gulistan": "Gulistan", "sirdaro": "Syrdarya",
    "sirdarya": "Syrdarya", "kashkadaro": "Kashkadarya", "kashkadarya": "Kashkadarya",
    "karshi": "Karshi", "karsi": "Karshi", "surhondaro": "Surkhandarya",
    "surhandarya": "Surkhandarya", "termiz": "Termez", "termez": "Termez",
    "horazm": "Khorezm", "horezm": "Khorezm", "urganch": "Urgench", "urgench": "Urgench",
    "hiva": "Khiva", "nukus": "Nukus", "koraqalpogiston": "Karakalpakstan",
    "koraqalpoq": "Karakalpakstan", "karakalpakstan": "Karakalpakstan",
    "kokand": "Kokand", "kokon": "Kokand", "margilan": "Margilan", "margilon": "Margilan",
    "chirchik": "Chirchiq", "olmalik": "Almalyk", "almalik": "Almalyk", "angren": "Angren",
    "bekobod": "Bekabad", "chust": "Chust", "asaka": "Asaka", "shahrisabz": "Shahrisabz",
    "denov": "Denau", "zarafshon": "Zarafshan", "uchkurgan": "Uchkurgan",
    "chortok": "Chartak", "pop": "Pop", "kosonsoy": "Kasansay", "turakurgan": "Turakurgan",
    "ozbekiston": "Uzbekistan", "uzbekiston": "Uzbekistan", "uzbekistan": "Uzbekistan",
    "moskva": "Moscow", "moscow": "Moscow", "almati": "Almaty", "almaty": "Almaty",
    "bishkek": "Bishkek", "dushanbe": "Dushanbe", "istanbul": "Istanbul", "seul": "Seoul",
    "seoul": "Seoul", "dubai": "Dubai",
}
# Endings a place name takes in a sentence: Uzbek -dan/-da/-lik/-ga/-ning/-dagi
# ("-an": fold() merges the double d of "Samarqanddan"),
# Russian -a/-e/-u/-skiy, English none.
_PLACE_SUFFIXES = ("", "dan", "an", "tan", "da", "ta", "lik", "lig", "ga", "ka", "ning", "dagi", "liklar",
                   "a", "e", "u", "i", "ski", "skii", "skai", "skoi", "ets", "tsi")
_PLACE_WORDS = {"shahar", "shahri", "shahridan", "shahrida", "viloyat", "viloyati", "viloyatidan",
                "tuman", "tumani", "tumanidan", "city", "region", "oblast", "город", "область",
                "from", "in", "dan", "iz", "в", "из", "lives", "living", "yashaydi", "живет", "живёт"}

# Filler words that are never part of a name.
_STOPWORDS = {
    "va", "ham", "bilan", "u", "bu", "uning", "ismi", "ismli", "familiyasi", "degan", "kishi",
    "odam", "yigit", "qiz", "bola", "ayol", "erkak", "haqida", "topib", "ber", "toping", "top",
    "kerak", "malumot", "ma'lumot", "and", "the", "a", "an", "of", "is", "who", "person", "named",
    "name", "guy", "girl", "man", "woman", "about", "find", "please", "info", "и", "по", "имени",
    "человек", "парень", "девушка", "найди", "найти", "лет", "года", "год", "yosh", "yoshda",
    "yoshli", "years", "year", "old", "yo", "born", "tugilgan", "tug'ilgan", "yil", "yilda",
    "telefon", "phone", "email", "pochta", "username", "nik", "nick", "student", "talaba",
    "o'quvchi", "ishlaydi", "works", "at", "da", "dan",
} | _PLACE_WORDS
_PREPOSITIONS = {"from", "in", "iz", "из", "в", "во"}

# 7.6: workplace and place of study. Uzbek puts the place first ("Artelda
# ishlaydi", "TATU talabasi"), English and Russian after a verb ("works at",
# "работает в"). The captured words are taken out of the text so they never
# become part of the name.
_APOS = "['ʻ’`]"
_UZ_WORK_RE = re.compile(rf"(\S+?){_APOS}?(?:da|de|ta)\s+(?:ishla\w*|xodim\w*|faoliyat\s+yurit\w*)", re.IGNORECASE)
_UZ_STUDY_RE = re.compile(rf"(\S+?){_APOS}?(?:da|de|ta)\s+o{_APOS}?qi(?:ydi|gan|yapti|yotgan)\b", re.IGNORECASE)
_UZ_ROLE_RE = re.compile(rf"(\S+)\s+(talabasi|o{_APOS}?quvchisi|bitiruvchisi|xodimi)\b", re.IGNORECASE)
_EN_WORK_RE = re.compile(r"\b(?:works?|working|worked|employed|job)\s+(?:at|for|in)\s+([^,;.!?]+)", re.IGNORECASE)
_EN_STUDY_RE = re.compile(r"\b(?:stud(?:ies|ied|ying|ent)|graduated?|alumn(?:us|a))\s+(?:at|of|from|in)\s+([^,;.!?]+)",
                          re.IGNORECASE)
_RU_WORK_RE = re.compile(r"(?:работает|работал[аи]?|сотрудник(?:ца)?)\s+(?:в|во|на)\s+([^,;.!?]+)", re.IGNORECASE)
_RU_STUDY_RE = re.compile(r"(?:учится|учился|училась|студент(?:ка)?|окончил[аи]?)\s+(?:в|во|на)?\s*([^,;.!?]+)",
                          re.IGNORECASE)
# words that name the kind of organisation, not which one
_ORG_GENERIC = {"kompaniyasi", "kompaniya", "firmasi", "firma", "korxonasi", "zavodi", "banki", "bank",
                "universiteti", "universitet", "instituti", "institut", "maktabi", "maktab", "litseyi",
                "kolleji", "akademiyasi", "vazirligi", "hokimligi", "company", "university", "school",
                "college", "institute", "компании", "университете", "институте", "школе", "банке"}
# where a phrase after "works at" ends: "works at Artel from Namangan 25 years old"
_ORG_END_WORDS = {"from", "in", "and", "aged", "age", "born", "since", "as", "в", "из", "и", "с", "dan",
                  "va", "years", "year", "yosh", "лет"}
MAX_ORG_WORDS = 4
_NAME_WORD_RE = re.compile(r"^[A-Za-zÀ-ɏЀ-ӿ][A-Za-zÀ-ɏЀ-ӿʻʼ’'`\-]*$")


# 10.5: places of two or more words; one word at a time, "from United States"
# became the place "United" and the name "Terence Tao States"
_MULTI_PLACES = (
    "united states of america", "united states", "united kingdom", "united arab emirates", "new york city",
    "new york", "san francisco", "los angeles", "san diego", "san jose", "santa clara", "palo alto",
    "mountain view", "silicon valley", "bay area", "las vegas", "salt lake city", "new jersey",
    "north carolina", "south carolina", "rhode island", "new zealand", "south korea", "north korea",
    "saudi arabia", "south africa", "hong kong", "sri lanka", "costa rica", "czech republic", "new delhi",
    "abu dhabi", "tel aviv", "rio de janeiro", "buenos aires", "kuala lumpur", "cape town", "mexico city",
    "saint petersburg", "st petersburg", "st. petersburg", "sankt peterburg", "nizhny novgorod",
)
_MULTI_PLACE_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(p) for p in sorted(_MULTI_PLACES, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE)
# "from Ann Arbor", "in Santa Monica": capitalised words right after a preposition
_CAP_PLACE_RE = re.compile(
    r"(?<![\w-])(?:from|in|из|в|во)\s+((?:[A-ZА-ЯЁ][\w'’\-]*)(?:\s+(?:[A-ZА-ЯЁ][\w'’\-]*)){1,3})(?=\s*(?:[,;.!?]|$))")

_PLACE_STEMS = sorted(((fold(k), v) for k, v in _PLACES.items()), key=lambda kv: len(kv[0]), reverse=True)
_STOP_KEYS = {fold(s) for s in _STOPWORDS}


def _place_of(word: str) -> str | None:
    key = fold(word)
    if len(key) < 3:
        return None
    for stem, display in _PLACE_STEMS:
        if key.startswith(stem) and key[len(stem):] in _PLACE_SUFFIXES:
            if len(stem) <= 3 and key != stem:
                continue            # "pop" must not swallow "popov"
            return display
    return None


def _org_words(raw: str) -> str:
    """The organisation name at the start of a captured phrase (≤ 4 words)."""
    words = []
    for word in raw.split():
        bare = word.strip("\"'«»“”.,")
        if not bare or bare.casefold() in _ORG_END_WORDS or re.fullmatch(r"\d+", bare):
            break
        words.append(bare)
        if len(words) >= MAX_ORG_WORDS:
            break
    return " ".join(words)


def _take_orgs(rest: str, out: dict) -> str:
    """Pull workplace / place-of-study phrases out of the text (7.6)."""
    def keep(kind: str, value: str) -> None:
        value = value.strip(" \"'«»“”-")
        if len(value) < 2 or _place_of(value) or value.casefold() in _STOPWORDS:
            if _place_of(value) and _place_of(value) not in out["places"]:
                out["places"].append(_place_of(value))      # "работает в Ташкенте"
            return
        if value not in out[kind]:
            out[kind].append(value[:80])

    def uz(pattern: re.Pattern, kind: str, text: str) -> str:
        pieces, last = [], 0
        for m in pattern.finditer(text):
            start, word = m.start(1), m.group(1)
            if fold(word) in {fold(g) for g in _ORG_GENERIC}:
                # "Artel kompaniyasida ishlaydi": take the word before as well
                before = re.search(r"(\S+)\s+$", text[last:start])
                if before:
                    start = last + before.start(1)
                    word = before.group(1) + " " + word
            keep(kind, word)
            pieces.append(text[last:start])
            last = m.end()
        pieces.append(text[last:])
        return " ".join(pieces)

    def forward(pattern: re.Pattern, kind: str, text: str) -> str:
        def repl(m: re.Match) -> str:
            org = _org_words(m.group(1))
            keep(kind, org)
            tail = m.group(1)[len(org):] if m.group(1).startswith(org) else m.group(1)
            return " " + tail.lstrip() if org else m.group(0)
        return pattern.sub(repl, text)

    rest = uz(_UZ_WORK_RE, "workplaces", rest)
    rest = uz(_UZ_STUDY_RE, "schools", rest)
    for m in list(_UZ_ROLE_RE.finditer(rest)):
        kind = "workplaces" if m.group(2).casefold().startswith("xodim") else "schools"
        word, start = m.group(1), m.start(1)
        if fold(word) in {fold(g) for g in _ORG_GENERIC}:
            before = re.search(r"(\S+)\s+$", rest[:start])
            if before:
                word = before.group(1) + " " + word
                rest = rest[:before.start(1)] + " " * (start - before.start(1)) + rest[start:]
        keep(kind, word)
    rest = _UZ_ROLE_RE.sub(" ", rest)
    rest = forward(_EN_WORK_RE, "workplaces", rest)
    rest = forward(_EN_STUDY_RE, "schools", rest)
    rest = forward(_RU_WORK_RE, "workplaces", rest)
    rest = forward(_RU_STUDY_RE, "schools", rest)
    return rest


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if not 9 <= len(digits) <= 15:
        return None
    if len(digits) == 9:            # local Uzbek mobile: 90 123 45 67
        digits = "998" + digits
    return "+" + digits


def parse_request(text: str, today: date | None = None) -> dict:
    """Split a free-text request into searchable fields. Never invents values."""
    original = " ".join(str(text or "").split())[:MAX_TEXT]
    today = today or date.today()
    rest = original
    out: dict = {"text": original, "names": [], "age": None, "birth_years": [], "places": [],
                 "usernames": [], "emails": [], "phones": [], "domains": [],
                 "workplaces": [], "schools": []}

    def take(pattern: re.Pattern, handler) -> None:
        nonlocal rest
        for match in list(pattern.finditer(rest)):
            handler(match)
        rest = pattern.sub(" ", rest)

    take(_EMAIL_RE, lambda m: out["emails"].append(m.group(0).lower()))

    def on_url(m: re.Match) -> None:
        raw = m.group(0)
        if re.fullmatch(r"[\d.]+", raw):
            return
        url = raw if raw.startswith("http") else "https://" + raw
        handle = handle_from_url(url)
        if handle:
            out["usernames"].append(handle)
        elif "/" not in raw.split("//")[-1].rstrip("/"):
            out["domains"].append(re.sub(r"^(?:https?://)?(?:www\.)?", "", raw).rstrip("/").lower())
    take(_URL_RE, on_url)
    take(_HANDLE_RE, lambda m: out["usernames"].append(m.group(1)))
    rest = _take_orgs(rest, out)

    def on_age(m: re.Match) -> None:
        age = int(m.group(1))
        if 5 <= age <= 100 and out["age"] is None:
            out["age"] = age
    take(_AGE_RE, on_age)
    take(_AGE_PREFIX_RE, on_age)

    def on_year(m: re.Match) -> None:
        year = int(m.group(1))
        if 1920 <= year <= today.year - 5 and year not in out["birth_years"]:
            out["birth_years"].append(year)
    take(_BORN_BEFORE_RE, on_year)
    take(_YEAR_RE, on_year)
    take(_PHONE_RE, lambda m: (p := _clean_phone(m.group(0))) and out["phones"].append(p))

    if out["age"] is not None and not out["birth_years"]:
        # a 19-year-old was born this year minus 19, or a year earlier
        out["birth_years"] = [today.year - out["age"] - 1, today.year - out["age"]]

    def on_multi_place(m: re.Match) -> None:
        place = " ".join(w[:1].upper() + w[1:] for w in m.group(1).split())
        if place not in out["places"]:
            out["places"].append(place)
    take(_MULTI_PLACE_RE, on_multi_place)

    def cap_place(m: re.Match) -> str:
        # "from Namangan Ali Valiyev": a known town first means the rest is a name
        if _place_of(m.group(1).split()[0]):
            return m.group(0)
        on_multi_place(m)
        return " "
    rest = _CAP_PLACE_RE.sub(cap_place, rest)

    name_words = []
    previous = ""
    for word in re.split(r"[\s,;:!?()\"]+", rest):
        word = word.strip(".-'’`")
        if not word:
            continue
        after_preposition = previous in _PREPOSITIONS
        previous = word.casefold()
        place = _place_of(word)
        if not place and after_preposition and _NAME_WORD_RE.match(word) and word.casefold() not in _STOPWORDS:
            place = word[:1].upper() + word[1:]      # "from London", "из Казани"
        if place:
            if place not in out["places"]:
                out["places"].append(place)
            continue
        if word.casefold() in _STOPWORDS or fold(word) in _STOP_KEYS:
            continue
        if _NAME_WORD_RE.match(word) and len(word) >= 2:
            name_words.append(word)
    if name_words:
        name = " ".join(w[:1].upper() + w[1:] for w in name_words[:MAX_NAME_TOKENS])
        out["names"].append(name)

    for key in ("usernames", "emails", "phones", "domains", "workplaces", "schools"):
        out[key] = list(dict.fromkeys(out[key]))[:3]
    return out


def has_target(parsed: dict) -> bool:
    return any(parsed.get(k) for k in ("names", "usernames", "emails", "phones", "domains"))


def describe(parsed: dict) -> str:
    """One line for the step log: what the agent understood."""
    parts = []
    if parsed["names"]:
        parts.append(f"name '{parsed['names'][0]}'")
    if parsed["age"] is not None:
        parts.append(f"age {parsed['age']}")
    if parsed["birth_years"]:
        years = sorted(parsed["birth_years"])
        parts.append(f"born {years[0]}" if len(years) == 1 else f"born {years[0]}–{years[-1]}")
    if parsed["places"]:
        parts.append("place " + ", ".join(parsed["places"]))
    for key, label in (("workplaces", "works at"), ("schools", "studies/studied at"), ("usernames", "username"),
                       ("emails", "email"), ("phones", "phone"), ("domains", "domain")):
        if parsed.get(key):
            parts.append(f"{label} " + ", ".join(parsed[key]))
    return "; ".join(parts) or "nothing searchable"

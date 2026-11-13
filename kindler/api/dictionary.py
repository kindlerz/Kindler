import logging
from pathlib import Path

from flask import Blueprint, render_template, request

dictionary_bp = Blueprint("dictionary", __name__, url_prefix="/dictionary")

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "wort"
INDEXES = {"de": "wort.idx", "en": "wort-en.idx"}
MAX_ENTRIES = 32  # same cap as wort's plain mode
NEIGHBOURS = 20

# fold() is copied from wort's tools/build-db.py; it must stay identical, or lookups miss.
FOLD_LAT = ["a", "a", "a", "a", "ae", "a", "ae", "c", "e", "e", "e", "e", "i", "i", "i", "i",
            "d", "n", "o", "o", "o", "o", "oe", None, "o", "u", "u", "u", "ue", "y", "th", "y"]  # fmt: skip


def fold(s):
    """Search key: lowercase, ä/ö/ü -> ae/oe/ue, ß -> ss, other Latin-1 accents dropped."""
    out = []
    for c in s:
        if "A" <= c <= "Z" or ("\xc0" <= c <= "\xde" and c != "\xd7"):
            c = chr(ord(c) + 32)
        if c == "\xdf":
            c = "ss"
        elif "\xe0" <= c <= "\xff" and FOLD_LAT[ord(c) - 0xE0]:
            c = FOLD_LAT[ord(c) - 0xE0]
        out.append(c)
    return "".join(out)


def _key_at(f, pos):
    """Key of the index line containing byte pos."""
    while pos > 0:
        f.seek(pos - 1)
        if f.read(1) == b"\n":
            break
        pos -= 1
    f.seek(pos)
    return f.readline().split(b"\t", 1)[0]


def lookup(index_path, word):
    """Index lines (shown, offset) whose key equals fold(word), plus the lines that follow
    alphabetically when there is no match. Binary search on the sorted file, like BSD look.
    """
    key = fold(word).encode()
    with open(index_path, "rb") as f:
        lo, hi = 0, f.seek(0, 2)
        while lo < hi:  # first byte whose line has a key >= key; always a line start
            mid = (lo + hi) // 2
            if _key_at(f, mid) >= key:
                hi = mid
            else:
                lo = mid + 1
        f.seek(lo)
        matches, neighbours = [], []
        for raw in f:
            k, shown, offset = raw.decode().rstrip("\n").split("\t")
            if k.encode() == key and len(matches) < MAX_ENTRIES:
                matches.append((shown, int(offset)))
            elif k.encode() != key:
                if matches or len(neighbours) == NEIGHBOURS:
                    break
                neighbours.append(shown)
    return matches, neighbours


def load_record(offset):
    """Record at offset in wort.dat as (type, text) pairs; type is one of @ # : ' ' >."""
    lines = []
    with open(DATA_DIR / "wort.dat", "rb") as f:
        f.seek(offset)
        for raw in f:
            line = raw.decode().rstrip("\n")
            if line == "%":
                break
            lines.append((line[:1], line[1:]))
    return lines


def data_date():
    """The "!Wiktionary <date>, OpenThesaurus <date>" first line of wort.dat, without the "!"."""
    with open(DATA_DIR / "wort.dat", encoding="utf-8") as f:
        return f.readline()[1:].strip()


@dictionary_bp.route("/")
def home():
    return render_template("index_dictionary.html")


# /<lang>/search is the results page's form action: the shared search bar has no lang field
@dictionary_bp.route("/search", defaults={"lang": None})
@dictionary_bp.route("/<lang>/search")
def search(lang):
    query = request.args.get("q", "").strip()
    lang = lang or request.args.get("lang", "de")
    if not query or lang not in INDEXES:
        return render_template("index_dictionary.html")
    if not (DATA_DIR / INDEXES[lang]).exists():
        logging.error("Dictionary data missing in %s", DATA_DIR)
        return "The dictionary data is not installed.", 503
    matches, neighbours = lookup(DATA_DIR / INDEXES[lang], query)
    # entries spelled exactly as typed first ("Straße" before "Strass"), one per record
    matches.sort(key=lambda m: m[0].split(" → ")[0] != query)
    entries, seen = [], set()
    for shown, offset in matches:
        if offset not in seen:
            seen.add(offset)
            entries.append({"shown": shown, "lines": load_record(offset)})
    return render_template(
        "result_dictionary.html",
        query=query,
        lang=lang,
        entries=entries,
        neighbours=neighbours,
        data_date=data_date(),
    )

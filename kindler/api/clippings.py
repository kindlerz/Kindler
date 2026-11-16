import bisect
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import uuid
import zlib

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from markupsafe import escape
from pathvalidate import sanitize_filename

from kindler.abuse import guard
from kindler.cache import cache

clippings_bp = Blueprint("clippings", __name__, url_prefix="/clippings")

allowed_formats = {"pdf", "epub", "mobi", "azw3"}
MAX_UPLOAD = 5 * 1024 * 1024
CACHE_SECONDS = 3600

# Type word on the second line of an entry, English and German Kindles:
# "- Your Highlight on page 3 | Location 40-42 | Added on ...",
# "- Ihre Markierung auf Seite 3 | bei Position 40-42 | Hinzugefügt am ...",
# "- Markierung | Seite 3 | ..." (newer firmware), "- Highlight Loc. 2919-28" (older).
META = re.compile(r"^- (?:Your |Ihre |Ihr )?(\w+)", re.IGNORECASE)
KINDS = {
    "highlight": "Highlight",
    "markierung": "Highlight",
    "note": "Note",
    "notiz": "Note",
    "bookmark": "Bookmark",
    "lesezeichen": "Bookmark",
}
PAGE = re.compile(r"\b(?:page|seite)\s+(\d+)(?:-(\d+))?", re.IGNORECASE)
LOCATION = re.compile(
    r"\b(?:location|loc\.|position|pos\.)\s+(\d+)(?:-(\d+))?", re.IGNORECASE
)


def range_end(start, end):
    """Old firmware shortens a range end: 2919-28 means 2919 to 2928."""
    if not end:
        return start
    value = int(end)
    if value < start:
        value = int(str(start)[: -len(end)] + end) if len(end) < len(str(start)) else 0
    return value if value >= start else start


def read_entries(text):
    """Yield (order, title, kind, meta_line, body) for each recognised entry."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    for order, chunk in enumerate(text.split("==========\n")):
        lines = chunk.strip("\n").split("\n")
        match = META.match(lines[1]) if len(lines) >= 2 else None
        kind = KINDS.get(match.group(1).lower()) if match else None
        if kind:
            # Kindle also writes a BOM before some titles mid-file
            title = lines[0].replace("\ufeff", "").strip()
            yield order, title, kind, lines[1], "\n".join(lines[3:]).strip()


def is_clippings(text):
    return "==========" in text and any(True for _ in read_entries(text))


def parse_clippings(text):
    """Return [(book_title, author, [entry, ...]), ...] sorted by title.

    Each entry is a highlight dict with an optional list of notes; old versions
    of edited highlights are dropped.
    """
    books = {}
    for order, title, kind, meta, body in read_entries(text):
        if kind == "Bookmark" or not body:
            continue
        loc = LOCATION.search(meta)
        page = PAGE.search(meta)
        start = int(loc.group(1)) if loc else None
        entry = {
            "kind": kind,
            "text": body,
            "order": order,
            "start": start,
            "end": range_end(start, loc.group(2)) if loc else None,
            "page": "-".join(g for g in page.groups() if g) if page else None,
            "notes": [],
        }
        books.setdefault(title, []).append(entry)

    result = []
    for title, entries in books.items():
        highlights = drop_superseded([e for e in entries if e["kind"] == "Highlight"])
        notes = [e for e in entries if e["kind"] == "Note"]
        standalone = attach_notes(highlights, notes)
        items = sorted(highlights + standalone, key=sort_key)
        match = re.match(r"^(.*?)\s*\(([^()]*)\)$", title)
        name, author = (match.group(1), match.group(2)) if match else (title, "")
        result.append((clean_title(name, author) or title, author, items))
    return sorted(result, key=lambda b: b[0].lower())


# How many neighbours (sorted by location) to compare with. Keeps the work
# linear for crafted files where thousands of entries share one location.
NEIGHBOURS = 20


def span(entry):
    """(first, last) location of an entry, else its page range, else None."""
    if entry["start"] is not None:
        return entry["start"], entry["end"]
    if entry["page"]:
        first, _, last = entry["page"].partition("-")
        return int(first), int(last or first)
    return None


def drop_superseded(highlights):
    """Drop old versions of edited highlights.

    Editing a highlight on the Kindle appends a new entry and keeps the old one.
    Two highlights are versions of one when their ranges overlap and one text
    contains the other; the later entry wins.
    """
    placed = sorted((h for h in highlights if span(h)), key=span)
    dropped = set()
    for i, h in enumerate(placed):
        for other in placed[i + 1 : i + 1 + NEIGHBOURS]:
            if span(other)[0] > span(h)[1]:
                break
            if h["text"] in other["text"] or other["text"] in h["text"]:
                dropped.add(id(min(h, other, key=lambda e: e["order"])))
    return [h for h in highlights if id(h) not in dropped]


def attach_notes(highlights, notes):
    """Put each note on the highlight whose range contains it; return the rest."""
    placed = sorted((h for h in highlights if h["start"] is not None), key=span)
    starts = [h["start"] for h in placed]
    standalone = []
    for note in notes:
        owners = []
        if note["start"] is not None:
            last = bisect.bisect_right(starts, note["start"])
            owners = [
                h
                for h in placed[max(0, last - NEIGHBOURS) : last]
                if h["end"] >= note["start"]
            ]
        if owners:
            # Kindle places a note at the end of its highlight
            owners.sort(key=lambda h: (h["end"] != note["start"], -h["order"]))
            owners[0]["notes"].append(note["text"])
        else:
            standalone.append(note)
    return standalone


def clean_title(name, author):
    """Turn a file-name style title into a readable one.

    "Into The Wild (Jon Krakauer) (Z-Library)" -> "Into The Wild",
    "The_Inmate_-_Freida_McFadden" -> "The Inmate".
    """
    name = re.sub(r"(\s*\([^()]*\))+$", "", name.replace("_", " "))
    for joiner in (" - ", " by "):
        if author and name.endswith(joiner + author):
            name = name[: -len(joiner + author)]
    return " ".join(name.split())


def with_ellipsis(text):
    """Mark a highlight that starts or ends mid-sentence."""
    if text[0].islower():
        text = "…" + text
    if text[-1].isalnum():
        text += "…"
    return text


def direction(text):
    """' dir="rtl"' when the first letter is right-to-left (Persian, Arabic, Hebrew)."""
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in ("R", "AL"):
            return ' dir="rtl"'
        if kind == "L":
            return ""
    return ""


def sort_key(entry):
    page = entry["page"].split("-")[0] if entry["page"] else "0"
    return (entry["start"] or 0, int(page), entry["order"])


BOOK_CSS = """
/* Persian etc. use the first font in the list that has the letters */
body { font-size: 13pt; line-height: 1.5; color: #000;
        font-family: "EB Garamond", "Noto Naskh Arabic", serif; }
h1 { font-size: 22pt; margin: 0 0 0.3em 0; text-align: center; }
.byline { font-size: 14pt; margin: 0; text-align: center; }
.counts { font-size: 11pt; margin: 0.4em 0 2em 0; text-align: center; }
.item { margin: 0 0 1.6em 0; page-break-inside: avoid; }
.cite { font-size: 9pt; color: #000; text-decoration: none; }
h2.refs { font-size: 15pt; margin: 2em 0 0.5em 0; }
.ref { font-size: 11pt; margin: 0 0 0.2em 0; }
.highlight, .note { margin: 0; padding: 0.15em 0.6em 0.15em 0.8em;
        border-left: 3px solid #555; }
/* highlight text starts at the margin, where the note's bar is */
.highlight { border-left: none; padding-left: 0; }
/* the yellow reaches into the margin so its text still starts at the margin */
.plain { background-color: #fff6c2; margin-left: -0.5em; padding-left: 0.5em; }
.note { margin-top: 0.4em; padding-top: 0.3em; padding-bottom: 0.3em;
        background-color: #eeeeee; font-size: 12pt; }
/* right-to-left paragraphs mirror the left-side layout;
   Noto Naskh reads smaller than EB Garamond at the same size */
[dir="rtl"] { text-align: right; }
.counts[dir="rtl"] { text-align: center; }
.note[dir="rtl"] { border-left: none; border-right: 3px solid #555;
        padding-left: 0.6em; padding-right: 0.8em; font-size: 14pt; }
.highlight[dir="rtl"] { padding-left: 0.6em; padding-right: 0; font-size: 15pt; }
.plain[dir="rtl"] { margin-left: 0; margin-right: -0.5em; padding-right: 0.5em; }
"""

PDF_OPTIONS = [
    "--paper-size", "a4",
    "--pdf-page-numbers",
    "--pdf-default-font-size", "13",
    "--disable-font-rescaling",
    "--pdf-page-margin-top", "56",
    "--pdf-page-margin-bottom", "56",
    "--pdf-page-margin-left", "72",
    "--pdf-page-margin-right", "72",
]  # fmt: skip


LABELS = {
    "en": {"page": "Page", "location": "Location", "references": "References",
           "highlight": ("highlight", "highlights"), "note": ("note", "notes")},
    "fa": {"page": "صفحه", "location": "موقعیت", "references": "پی‌نوشت‌ها",
           "highlight": ("هایلایت", "هایلایت"), "note": ("یادداشت", "یادداشت")},
}  # fmt: skip
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def number(n, lang):
    return str(n).translate(PERSIAN_DIGITS) if lang == "fa" else str(n)


def counts(items, lang="en"):
    """ "23 highlights, 1 note" (or the Persian equivalent) for one book."""
    labels = LABELS[lang]
    highlights = sum(1 for item in items if item["kind"] == "Highlight")
    notes = sum(len(item["notes"]) for item in items) + len(items) - highlights

    def count(n, label):
        return f"{number(n, lang)} {labels[label][0 if n == 1 else 1]}"

    separator = "، " if lang == "fa" else ", "
    return f'{count(highlights, "highlight")}{separator}{count(notes, "note")}'


def to_html(title, author, items):
    # a right-to-left title means a Persian book: Persian labels and digits
    rtl = direction(title)
    lang = "fa" if rtl else "en"
    labels = LABELS[lang]
    parts = []
    if author:
        parts.append(f'<p class="byline">{escape(author)}</p>')
    parts.append(f'<p class="counts"{rtl}>{counts(items, lang)}</p>')
    references = []
    for item in items:
        where = []
        if item["page"]:
            where.append(f"{labels['page']} {number(item['page'], lang)}")
        if item["start"] is not None:
            span = number(item["start"], lang)
            if item["end"] != item["start"]:
                span += "–" + number(item["end"], lang)
            where.append(f"{labels['location']} {span}")
        cite = ""
        if where:
            references.append(" &middot; ".join(where))
            n = len(references)
            cite = f' <a class="cite" id="cite-{n}" href="#ref-{n}">[{number(n, lang)}]</a>'
        parts.append('<div class="item">')
        notes = list(item["notes"])
        if item["kind"] == "Note":
            notes.insert(0, item["text"])
        else:
            text = with_ellipsis(item["text"])
            css = "highlight" if notes else "highlight plain"
            parts.append(f'<p class="{css}"{direction(text)}>{escape(text)}{cite}</p>')
            cite = ""
        for note in notes:
            # str() first: Markup.replace would escape the inserted <br> too
            note_html = str(escape(note)).replace("\n", "<br>")
            parts.append(f'<p class="note"{direction(note)}>{note_html}{cite}</p>')
            cite = ""
        parts.append("</div>")
    if references:
        parts.append(f'<h2 class="refs"{rtl}>{labels["references"]}</h2>')
        for n, ref in enumerate(references, 1):
            parts.append(
                f'<p class="ref" id="ref-{n}"{rtl}>'
                f'<a class="cite" href="#cite-{n}">[{number(n, lang)}]</a> {ref}</p>'
            )
    return "\n".join(parts)


@clippings_bp.route("/")
def home():
    return render_template("index_clippings.html")


def not_clippings():
    return redirect(url_for("error.error", status_code=400, reason="clippings"))


@clippings_bp.route("/upload", methods=["POST"])
def upload():
    # reject big bodies before Flask parses them; the extra 16 KB is form overhead
    request.max_content_length = MAX_UPLOAD + 16 * 1024
    try:
        upload_file = request.files.get("file")
    except RequestEntityTooLarge:
        return redirect(url_for("error.error", status_code=413))
    if not upload_file or not upload_file.filename.lower().endswith(".txt"):
        return not_clippings()
    data = upload_file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return redirect(url_for("error.error", status_code=413))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return not_clippings()
    if "\x00" in text or not is_clippings(text):
        return not_clippings()
    books = parse_clippings(text)
    clippings_id = uuid.uuid4().hex
    # compressed: plain text shrinks about 4x, so Redis holds less per upload
    cache.set(f"clippings:{clippings_id}", zlib.compress(data), timeout=CACHE_SECONDS)
    return render_template(
        "result_clippings.html",
        books=books,
        clippings_id=clippings_id,
        counts=counts,
    )


@clippings_bp.route("/save_page")
def save_page():
    clippings_id = request.args.get("id", "")
    save_format = request.args.get("format")
    book = request.args.get("book", type=int)
    if save_format not in allowed_formats or book is None:
        abort(400, "Invalid request")
    text = None
    if re.fullmatch(r"[0-9a-f]{32}", clippings_id):
        stored = cache.get(f"clippings:{clippings_id}")
        text = zlib.decompress(stored).decode("utf-8") if stored else None
    if text is None:
        return redirect(url_for("error.error", status_code=404, reason="expired"))
    books = parse_clippings(text)
    if not 0 <= book < len(books):
        return redirect(url_for("error.error", status_code=404))
    blocked = guard()
    if blocked:
        return blocked
    title, author, items = books[book]
    html_content = render_template(
        "read_save_formatted.html",
        title=escape(title),
        content=to_html(title, author, items),
    )
    options = [
        "--title",
        f"{title} - Highlights",
        "--authors",
        author or "Unknown",
        "--extra-css",
        BOOK_CSS,
    ]
    if save_format == "pdf":
        options.extend(PDF_OPTIONS)
    # read into memory and delete now: gunicorn's file wrapper skips call_on_close
    work_dir = tempfile.mkdtemp()
    try:
        input_html_file = os.path.join(work_dir, "book.html")
        output_file = os.path.join(work_dir, f"book.{save_format}")
        with open(input_html_file, "w", encoding="utf-8") as html_file:
            html_file.write(html_content)
        subprocess.run(
            ["ebook-convert", input_html_file, output_file, *options], check=True
        )
        with open(output_file, "rb") as book_file:
            data = book_file.read()
    except subprocess.CalledProcessError as e:
        logging.error(f"Clippings conversion failed: {e}")
        abort(500, f"Conversion failed: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=sanitize_filename(f"{title} - Highlights.{save_format}"),
    )

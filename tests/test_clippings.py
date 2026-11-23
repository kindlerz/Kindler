import io
import os
import subprocess

import pytest

from kindler.api import clippings
from kindler.api.home import home_bp
from kindler.api.clippings import (
    clean_title,
    clippings_bp,
    counts,
    direction,
    is_clippings,
    parse_clippings,
    range_end,
    to_html,
    with_ellipsis,
)
from kindler.cache import cache

SEP = "==========\r\n"

# Made-up English clippings with the quirks a real Kindle file has: BOM at the
# start and again before a title mid-file, CRLF, an edited (extended) highlight,
# a note at the end of its highlight, a bookmark, a page-only highlight.
ENGLISH = (
    "\ufeffThe Book (Jane Doe) (Z-Library) (Jane Doe)\r\n"
    "- Your Highlight on page 3 | Location 40-42 | Added on Monday, 1 January 2024 10:00:00\r\n"
    "\r\n"
    "first highlight that starts mid-sentence\r\n"
    + SEP
    + "The Book (Jane Doe) (Z-Library) (Jane Doe)\r\n"
    "- Your Highlight on page 2 | Location 20-21 | Added on Monday, 1 January 2024 09:00:00\r\n"
    "\r\n"
    "An early highlight.\r\n"
    + SEP
    + "\ufeffThe Book (Jane Doe) (Z-Library) (Jane Doe)\r\n"
    "- Your Highlight on page 3 | Location 40-43 | Added on Monday, 1 January 2024 10:05:00\r\n"
    "\r\n"
    "first highlight that starts mid-sentence, now extended.\r\n"
    + SEP
    + "The Book (Jane Doe) (Z-Library) (Jane Doe)\r\n"
    "- Your Note on page 3 | Location 43 | Added on Monday, 1 January 2024 10:06:00\r\n"
    "\r\n"
    "My note\r\nsecond line\r\n"
    + SEP
    + "The Book (Jane Doe) (Z-Library) (Jane Doe)\r\n"
    "- Your Bookmark on page 9 | Location 100 | Added on Monday, 1 January 2024 11:00:00\r\n"
    "\r\n"
    "\r\n" + SEP + "Paper  \r\n"
    "- Your Highlight on page 5-6 | Added on Tuesday, 2 January 2024 08:00:00\r\n"
    "\r\n"
    "Page only.\r\n" + SEP
)

# Made-up German clippings: the forms German Kindles write.
GERMAN = (
    "Das Buch (Max Mustermann)\n"
    "- Ihre Markierung auf Seite 12 | bei Position 180-184 | Hinzugefügt am Montag, 1. Januar 2024 10:00:00\n"
    "\n"
    "Ein Satz.\n"
    "==========\n"
    "Das Buch (Max Mustermann)\n"
    "- Ihre Notiz auf Seite 12 | bei Position 184 | Hinzugefügt am Montag, 1. Januar 2024 10:01:00\n"
    "\n"
    "Meine Notiz.\n"
    "==========\n"
    "Das Buch (Max Mustermann)\n"
    "- Ihr Lesezeichen auf Seite 20 | bei Position 300 | Hinzugefügt am Montag, 1. Januar 2024 10:02:00\n"
    "\n"
    "\n"
    "==========\n"
    "Das Buch (Max Mustermann)\n"
    "- Markierung | Seite 30 | Hinzugefügt am Montag, 1. Januar 2024 10:03:00\n"
    "\n"
    "Neuere Firmware.\n"
    "==========\n"
    "Das Buch (Max Mustermann)\n"
    "- Markierung Pos. 2919-28\n"
    "\n"
    "Alte Firmware.\n"
    "==========\n"
)

PERSIAN = (
    "کتاب نمونه (نویسنده نمونه)\n"
    "- Your Highlight on page 3 | Location 40-42 | Added on Monday, 1 January 2024 10:00:00\n"
    "\n"
    "این یک جمله است.\n"
    "==========\n"
)


def book(books, title):
    return next(b for b in books if b[0] == title)


def test_english_titles_bom_and_dedupe():
    books = parse_clippings(ENGLISH)
    assert [b[0] for b in books] == ["Paper", "The Book"]
    title, author, items = book(books, "The Book")
    assert author == "Jane Doe"
    # the shorter, earlier version of the extended highlight is dropped
    assert [i["text"] for i in items] == [
        "An early highlight.",
        "first highlight that starts mid-sentence, now extended.",
    ]


def test_english_note_attached_and_bookmark_ignored():
    _, _, items = book(parse_clippings(ENGLISH), "The Book")
    assert items[1]["notes"] == ["My note\nsecond line"]
    assert all(i["kind"] == "Highlight" for i in items)
    assert (items[1]["page"], items[1]["start"], items[1]["end"]) == ("3", 40, 43)


def test_page_only_highlight_keeps_page_range():
    _, author, items = book(parse_clippings(ENGLISH), "Paper")
    assert author == ""
    assert (items[0]["page"], items[0]["start"]) == ("5-6", None)


def test_german_forms():
    title, author, items = parse_clippings(GERMAN)[0]
    assert (title, author) == ("Das Buch", "Max Mustermann")
    assert [i["text"] for i in items] == [
        "Neuere Firmware.",  # page only, so it sorts first
        "Ein Satz.",
        "Alte Firmware.",
    ]
    assert items[1]["notes"] == ["Meine Notiz."]
    assert (items[1]["page"], items[1]["start"], items[1]["end"]) == ("12", 180, 184)
    assert items[0]["page"] == "30"
    assert (items[2]["start"], items[2]["end"]) == (2919, 2928)


@pytest.mark.parametrize(
    "start,end,expected",
    [(40, "42", 42), (2919, "28", 2928), (2919, None, 2919), (99, "3", 99)],
)
def test_range_end(start, end, expected):
    assert range_end(start, end) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        (ENGLISH, True),
        (GERMAN, True),
        ("just some notes\n", False),
        ("Title\n- something else\n\ntext\n==========\n", False),
        ("Title\n- Your Highlight on page 1\n\ntext\n", False),  # no separator
    ],
)
def test_is_clippings(text, expected):
    assert is_clippings(text) is expected


@pytest.mark.parametrize(
    "name,author,expected",
    [
        ("Into The Wild (Jon Krakauer) (Z-Library)", "Jon Krakauer", "Into The Wild"),
        ("The_Inmate_-_Freida_McFadden", "Freida McFadden", "The Inmate"),
        (
            "First Person Singular by Haruki Murakami",
            "Haruki Murakami",
            "First Person Singular",
        ),
    ],
)
def test_clean_title(name, author, expected):
    assert clean_title(name, author) == expected


def test_with_ellipsis():
    assert with_ellipsis("it was. As") == "…it was. As…"
    assert with_ellipsis("Done.") == "Done."


def test_direction():
    assert direction("سلام") == ' dir="rtl"'
    assert direction("Hello سلام") == ""
    assert direction("…123 سلام") == ' dir="rtl"'


def test_counts_singular_and_persian():
    one = [{"kind": "Highlight", "notes": ["n"]}]
    assert counts(one) == "1 highlight, 1 note"
    assert counts(one * 2) == "2 highlights, 2 notes"
    assert counts(one * 2, "fa") == "۲ هایلایت، ۲ یادداشت"


def test_to_html_references_and_escaping():
    items = [
        {"kind": "Highlight", "text": "A <b>bold</b> claim.", "notes": ["n & m"],
         "page": "3", "start": 40, "end": 42},
        {"kind": "Highlight", "text": "No place.", "notes": [],
         "page": None, "start": None, "end": None},
    ]  # fmt: skip
    html = to_html("Book", "Jane", items)
    assert "A &lt;b&gt;bold&lt;/b&gt; claim." in html
    assert "n &amp; m" in html
    assert 'href="#ref-1">[1]</a>' in html and "[2]" not in html
    assert "[1]</a> Page 3 &middot; Location 40–42" in html
    assert "References" in html
    assert 'class="highlight plain"' in html  # no note: yellow


def test_to_html_persian():
    _, author, items = parse_clippings(PERSIAN)[0]
    html = to_html("کتاب نمونه", author, items)
    assert "[۱]</a>" in html
    assert "صفحه ۳ &middot; موقعیت ۴۰–۴۲" in html
    assert "پی‌نوشت‌ها" in html
    assert '<p class="highlight plain" dir="rtl">' in html


@pytest.fixture
def client(app, monkeypatch):
    app.config["CACHE_TYPE"] = "SimpleCache"
    cache.init_app(app)
    app.register_blueprint(home_bp)  # result page links back to Home
    app.register_blueprint(clippings_bp)
    monkeypatch.setattr(clippings, "highlights_guard", lambda kind: None)
    return app.test_client()


def upload(client, data, name="My Clippings.txt"):
    return client.post(
        "/clippings/upload",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_upload_lists_books_with_counts(client):
    r = upload(client, ENGLISH.encode())
    assert r.status_code == 200
    assert b"The Book" in r.data and b"Paper" in r.data
    assert b"2 highlights, 1 note" in r.data
    assert b"format=pdf" in r.data


@pytest.mark.parametrize(
    "data,name",
    [
        (ENGLISH.encode(), "clippings.pdf"),  # not .txt
        (b"\xff\xfe\x00junk", "My Clippings.txt"),  # not UTF-8
        (b"hello\x00world\n==========\n", "My Clippings.txt"),  # NUL byte
        (b"a shopping list\n", "My Clippings.txt"),  # not clippings
    ],
)
def test_upload_rejects_non_clippings(client, data, name):
    r = upload(client, data, name)
    assert r.status_code == 302
    assert "status_code=400" in r.location and "reason=clippings" in r.location


def test_upload_without_file_is_rejected(client):
    r = client.post("/clippings/upload", data={}, content_type="multipart/form-data")
    assert r.status_code == 302 and "reason=clippings" in r.location


def test_upload_too_large(client, monkeypatch):
    monkeypatch.setattr(clippings, "MAX_UPLOAD", 1024)
    r = upload(client, (ENGLISH * 200).encode())
    assert r.status_code == 302 and "status_code=413" in r.location


def test_save_page_expired_and_bad_requests(client):
    r = client.get("/clippings/save_page?id=" + "0" * 32 + "&book=0&format=pdf")
    assert r.status_code == 302 and "reason=expired" in r.location
    r = client.get("/clippings/save_page?id=../etc&book=0&format=pdf")
    assert r.status_code == 302 and "reason=expired" in r.location
    r = client.get("/clippings/save_page?id=" + "0" * 32 + "&book=0&format=exe")
    assert r.status_code == 400


def uploaded_id(client):
    html = upload(client, ENGLISH.encode()).data.decode()
    return html.split("id=")[1][:32]


def test_save_page_converts_and_cleans_up(client, monkeypatch):
    seen = {}

    def fake_run(cmd, check):
        seen["cmd"] = cmd
        seen["dir"] = os.path.dirname(cmd[1])
        with open(cmd[2], "wb") as out:
            out.write(b"%PDF fake")

    monkeypatch.setattr(subprocess, "run", fake_run)
    clippings_id = uploaded_id(client)
    r = client.get(f"/clippings/save_page?id={clippings_id}&book=1&format=pdf")
    assert r.status_code == 200
    assert r.data == b"%PDF fake"
    assert "The Book - Highlights.pdf" in r.headers["Content-Disposition"]
    assert "--paper-size" in seen["cmd"]
    assert not os.path.exists(seen["dir"])  # temp folder removed right away


def test_save_page_unknown_book(client):
    clippings_id = uploaded_id(client)
    r = client.get(f"/clippings/save_page?id={clippings_id}&book=9&format=epub")
    assert r.status_code == 302 and "status_code=404" in r.location


def test_save_page_respects_highlights_guard(client, monkeypatch):
    from flask import redirect

    clippings_id = uploaded_id(client)
    monkeypatch.setattr(
        clippings,
        "highlights_guard",
        lambda kind: (
            redirect("/error?status_code=429") if kind == "downloads" else None
        ),
    )
    r = client.get(f"/clippings/save_page?id={clippings_id}&book=0&format=epub")
    assert r.status_code == 302 and "status_code=429" in r.location


def highlight_entry(location, text, added):
    return (
        "Words (Ann Author)\n"
        f"- Your Highlight on Location {location} | Added on {added}\n"
        f"\n{text}\n==========\n"
    )


def test_same_words_elsewhere_are_kept():
    text = highlight_entry("10-11", "What lovely weather.", "Mon") + highlight_entry(
        "900", "love", "Tue"
    )
    _, _, items = parse_clippings(text)[0]
    assert [i["text"] for i in items] == ["What lovely weather.", "love"]


def test_highlight_edited_shorter_keeps_new_version():
    text = highlight_entry("40-45", "A long first version.", "Mon") + highlight_entry(
        "40-42", "A long first", "Tue"
    )
    _, _, items = parse_clippings(text)[0]
    assert [i["text"] for i in items] == ["A long first"]


def test_crafted_file_parses_in_linear_time():
    import time

    # thousands of entries at one location must not compare all pairs
    text = "".join(highlight_entry("5-6", f"text {i}", "Mon") for i in range(20000))
    started = time.monotonic()
    parse_clippings(text)
    assert time.monotonic() - started < 3


def test_upload_respects_highlights_guard(client, monkeypatch):
    from flask import redirect

    monkeypatch.setattr(
        clippings,
        "highlights_guard",
        lambda kind: redirect("/error?status_code=429") if kind == "uploads" else None,
    )
    r = upload(client, ENGLISH.encode())
    assert r.status_code == 302 and "status_code=429" in r.location

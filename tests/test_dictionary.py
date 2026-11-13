import pytest

from kindler.api import dictionary
from kindler.api.dictionary import dictionary_bp, fold, lookup
from kindler.api.home import home_bp

RECORDS = {
    "Haus": "@Haus\n#Substantiv, Neutrum\n:Bedeutungen\n [1] Gebäude\n>Das Haus steht.\n%\n",
    "hausen": "@hausen\n#Verb\n:Bedeutungen\n [1] wohnen\n%\n",
    "Straße": "@Straße\n#Substantiv\n [1] <b>Weg</b>\n%\n",
}


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A tiny wort.dat/wort.idx/wort-en.idx in wort's format."""
    dat = "!Wiktionary 2026-11-01, OpenThesaurus 2026-11-09\n"
    offsets = {}
    for word, record in RECORDS.items():
        offsets[word] = len(dat.encode())
        dat += record
    (tmp_path / "wort.dat").write_text(dat, encoding="utf-8")
    idx = [
        ("haus", "Haus", "Haus"),
        ("haus", "haus → hausen", "hausen"),
        ("hausen", "hausen", "hausen"),
        ("haeuser", "Häuser → Haus", "Haus"),
        ("strasse", "Straße", "Straße"),
    ]
    lines = sorted(f"{k}\t{s}\t{offsets[w]}\n".encode() for k, s, w in idx)
    (tmp_path / "wort.idx").write_bytes(b"".join(lines))
    (tmp_path / "wort-en.idx").write_text(
        f"house\thouse → Haus\t{offsets['Haus']}\n", encoding="utf-8"
    )
    monkeypatch.setattr(dictionary, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(app):
    app.register_blueprint(home_bp)
    app.register_blueprint(dictionary_bp)
    return app.test_client()


def test_fold_matches_wort():
    assert fold("Häuser") == fold("haeuser") == "haeuser"
    assert fold("Maße") == "masse"
    assert fold("Café ÄÖÜ×") == "cafe aeoeue\xd7"


def test_lookup_finds_all_lines_with_the_key(data):
    matches, neighbours = lookup(data / "wort.idx", "HAUS")
    assert [shown for shown, _ in matches] == ["Haus", "haus → hausen"]
    assert neighbours == []


def test_lookup_folds_umlauts(data):
    matches, _ = lookup(data / "wort.idx", "Häuser")
    assert [shown for shown, _ in matches] == ["Häuser → Haus"]


def test_lookup_without_match_returns_following_words(data):
    matches, neighbours = lookup(data / "wort.idx", "hausa")
    assert matches == []
    assert neighbours == ["hausen", "Straße"]


def test_lookup_past_the_end(data):
    assert lookup(data / "wort.idx", "zzz") == ([], [])


def test_search_renders_entries(data, client):
    body = client.get("/dictionary/search?q=haus&lang=de").get_data(as_text=True)
    assert "<h3>Haus</h3>" in body and "<h3>hausen</h3>" in body
    assert "<i>Das Haus steht.</i>" in body
    assert "2 entries" in body
    assert "Wiktionary 2026-11-01, OpenThesaurus 2026-11-09" in body
    assert 'action="/dictionary/de/search"' in body


def test_search_in_english(data, client):
    body = client.get("/dictionary/en/search?q=house").get_data(as_text=True)
    assert "house → Haus" in body and "<h3>Haus</h3>" in body
    assert 'action="/dictionary/en/search"' in body


def test_search_escapes_data_and_query(data, client):
    body = client.get("/dictionary/search?q=<script>straße").get_data(as_text=True)
    assert "<script>" not in body
    body = client.get("/dictionary/search?q=Straße").get_data(as_text=True)
    assert "&lt;b&gt;Weg&lt;/b&gt;" in body


def test_missing_data_returns_503(tmp_path, monkeypatch, client):
    monkeypatch.setattr(dictionary, "DATA_DIR", tmp_path)
    assert client.get("/dictionary/search?q=haus").status_code == 503

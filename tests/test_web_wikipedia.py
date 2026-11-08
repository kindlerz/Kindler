from html import unescape
from urllib.parse import parse_qs, quote

import pytest

web = pytest.importorskip("kindler.api.web")
wikipedia = pytest.importorskip("kindler.api.wikipedia")

ARTICLE_URL = "https://en.wikipedia.org/wiki/Alan_Turing"


@pytest.fixture
def client(app):
    from kindler.api.home import home_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(web.web_bp)
    app.register_blueprint(wikipedia.wikipedia_bp)
    return app.test_client()


class FakePage:
    def __init__(self, title):
        self.title = title
        self.text = "<p>Turing worked on Enigma.</p>"
        self.links = {"Enigma": None}
        self.fullurl = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))

    def exists(self):
        return True


@pytest.mark.parametrize(
    "url,expected",
    [
        (ARTICLE_URL, "Alan Turing"),
        ("https://en.m.wikipedia.org/wiki/AC/DC", "AC/DC"),
        ("https://en.wikipedia.org/wiki/Caf%C3%A9#History", "Café"),
        ("https://de.wikipedia.org/wiki/Alan_Turing", None),
        ("https://en.wikipedia.org/w/index.php?title=X", None),
        ("https://en.wikipedia.org/wiki/", None),
        (
            "https://en.wikipedia.org/wiki/Dude,_Where%27s_My_Car%3F",
            "Dude, Where's My Car?",
        ),
        ("https://en.wikipedia.org/wiki/Foo;_Bar", "Foo; Bar"),
        (
            "https://en.wikipedia.org/wiki/Star_Wars:_Episode_IV",
            "Star Wars: Episode IV",
        ),
        ("https://en.wikipedia.org/wiki/Alan_Turing?oldid=1", None),
        ("https://en.wikipedia.org/wiki/Talk:Alan_Turing", None),
        ("https://en.wikipedia.org/wiki/User_talk:Someone", None),
        ("https://en.wikipedia.org/wiki/File:X.jpg", None),
        ("https://en.wikipedia.org/wiki/Category:Physics", None),
        ("https://example.com/wiki/Alan_Turing", None),
        (None, None),
    ],
)
def test_wikipedia_title(url, expected):
    assert wikipedia.wikipedia_title(url) == expected


def test_web_readability_renders_wikipedia_article(client, monkeypatch):
    requested = []

    def page(title):
        requested.append(title)
        return FakePage(title)

    monkeypatch.setattr(wikipedia.wiki, "page", page)
    monkeypatch.setattr(web, "is_blob_content", lambda url: pytest.fail("fetched"))

    resp = client.get(
        "/web/readability", query_string={"q": "turing", "url": ARTICLE_URL}
    )

    assert resp.status_code == 200
    assert requested == ["Alan Turing"]
    html = resp.get_data(as_text=True)
    assert "Turing worked on" in html
    # search bar and article links stay in /web
    assert 'action="/web/search"' in html
    link = html.split("<a href=/web/readability?", 1)[1].split(">", 1)[0]
    params = parse_qs(link)
    assert params["q"] == ["turing"]
    assert params["url"] == ["https://en.wikipedia.org/wiki/Enigma"]
    # downloads use the renderer the page was shown with
    assert "/wikipedia/save_page?" in html
    assert "/web/save_page?" not in html


class Resp:
    text = "<html><body><p>generic body</p></body></html>"


def assert_generic(resp):
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "generic body" in html
    assert "/web/save_page?" in html
    assert "/wikipedia/save_page?" not in html


def test_web_readability_falls_back_when_article_missing(client, monkeypatch):
    class NoPage(FakePage):
        def exists(self):
            return False

    monkeypatch.setattr(wikipedia.wiki, "page", NoPage)
    monkeypatch.setattr(web, "is_blob_content", lambda url: (False, Resp()))
    assert_generic(client.get("/web/readability", query_string={"url": ARTICLE_URL}))


def test_web_readability_falls_back_when_wikipedia_api_fails(client, monkeypatch):
    def page(title):
        raise KeyError("query")

    monkeypatch.setattr(wikipedia.wiki, "page", page)
    monkeypatch.setattr(web, "is_blob_content", lambda url: (False, Resp()))
    assert_generic(client.get("/web/readability", query_string={"url": ARTICLE_URL}))


def test_alternative_renderer_skips_wikipedia(client, monkeypatch):
    monkeypatch.setattr(wikipedia.wiki, "page", lambda t: pytest.fail("wiki used"))
    monkeypatch.setattr(web, "is_blob_content", lambda url: (False, Resp()))
    assert_generic(
        client.get(
            "/web/readability",
            query_string={"url": ARTICLE_URL, "alternative_renderer": "True"},
        )
    )


def test_wikipedia_links_do_not_nest_when_query_is_a_link_title(client, monkeypatch):
    class Page(FakePage):
        def __init__(self, title):
            super().__init__(title)
            self.text = "<p>Abwehr and Enigma, Alan Turing and Turing.</p>"
            self.links = {"Abwehr": 0, "Enigma": 0, "Turing": 0, "Alan Turing": 0}

    monkeypatch.setattr(wikipedia.wiki, "page", Page)
    html = client.get(
        "/web/readability", query_string={"q": "Enigma", "url": ARTICLE_URL}
    ).get_data(as_text=True)
    content = html.split('<div class="content">', 1)[1]
    assert content.count("<a href=") == 4
    assert "q=<a" not in content
    assert ">Alan Turing</a> and <a href=" in content


def test_export_links_quote_titles(app, monkeypatch):
    class Page(FakePage):
        def __init__(self, title):
            super().__init__(title)
            self.text = "<p>Read Ender's Game.</p>"
            self.links = {"Ender's Game": 0}

    monkeypatch.setattr(wikipedia.wiki, "page", Page)
    with app.test_request_context():
        content = wikipedia.get_wikipedia_article("X", True)["content"]
    assert "<a href='http://wikipedia.org/wiki/Ender%27s_Game'>" in content


def test_wikipedia_save_page_keeps_slash_in_title(client, monkeypatch):
    requested = []

    def page(title):
        requested.append(title)
        return FakePage(title)

    monkeypatch.setattr(wikipedia.wiki, "page", page)
    monkeypatch.setattr(wikipedia, "download_cover_image", lambda title: None)

    resp = client.get(
        "/wikipedia/save_page",
        query_string={"url": "https://en.wikipedia.org/wiki/AC/DC", "format": "html"},
    )
    assert resp.status_code == 200
    assert requested == ["AC/DC"]


def test_wikipedia_save_link_keeps_question_mark_in_title(client, monkeypatch):
    requested = []

    def page(title):
        requested.append(title)
        return FakePage(title)

    monkeypatch.setattr(wikipedia.wiki, "page", page)
    monkeypatch.setattr(wikipedia, "download_cover_image", lambda title: None)

    # search result hrefs are encoded; read_wikipedia.html builds save links from
    # the unquoted article URL. q differs from the title so q can't stand in for it.
    html = client.get(
        "/wikipedia/readability",
        query_string={
            "q": "car movie",
            "url": "https://en.wikipedia.org/wiki/Dude,_Where%27s_My_Car%3F",
        },
    ).get_data(as_text=True)
    save = html.split('href="/wikipedia/save_page?', 1)[1].split('"', 1)[0]
    resp = client.get("/wikipedia/save_page?" + unescape(save))
    assert resp.status_code == 200
    assert [t.replace("_", " ") for t in requested] == ["Dude, Where's My Car?"] * 2

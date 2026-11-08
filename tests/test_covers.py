import pytest
import requests

from kindler.api import standard_ebooks
from kindler.api.gutenberg_project import gutenberg_bp
from kindler.api.home import home_bp
from kindler.api.standard_ebooks import standard_ebooks_bp

CACHE = "public, max-age=2592000"


class FakeResp:
    def __init__(self, status_code=200, content=b"IMG", content_type="image/jpeg"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type} if content_type else {}


@pytest.fixture
def client(app):
    app.register_blueprint(home_bp)
    app.register_blueprint(gutenberg_bp)
    app.register_blueprint(standard_ebooks_bp)
    return app.test_client()


@pytest.fixture
def upstream(monkeypatch):
    """Stub requests.get; set .response (or .exc) and inspect .calls."""

    class Stub:
        response = FakeResp()
        exc = None
        calls = []

    stub = Stub()
    stub.calls = []

    def fake_get(url, **kwargs):
        stub.calls.append((url, kwargs))
        if stub.exc:
            raise stub.exc
        return stub.response

    monkeypatch.setattr(requests, "get", fake_get)
    return stub


def test_favicon_served_as_icon(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.mimetype == "image/x-icon"


def test_gutenberg_cover_builds_upstream_url_and_passes_through(client, upstream):
    resp = client.get("/gutenberg/cover/1342.jpg")
    assert resp.status_code == 200
    assert resp.get_data() == b"IMG"
    assert resp.headers["Content-Type"] == "image/jpeg"
    assert resp.headers["Cache-Control"] == CACHE
    url, kwargs = upstream.calls[0]
    assert url == "https://www.gutenberg.org/cache/epub/1342/pg1342.cover.medium.jpg"
    assert kwargs["timeout"]


def test_standard_ebooks_cover_builds_upstream_url_and_passes_through(client, upstream):
    upstream.response = FakeResp(content_type="image/png")
    resp = client.get("/standard_ebooks/cover/images/covers/a-b.png")
    assert resp.status_code == 200
    assert resp.get_data() == b"IMG"
    assert resp.headers["Content-Type"] == "image/png"
    assert resp.headers["Cache-Control"] == CACHE
    url, kwargs = upstream.calls[0]
    assert url == "https://standardebooks.org/images/covers/a-b.png"
    assert kwargs["timeout"]


COVER_URLS = ["/gutenberg/cover/1.jpg", "/standard_ebooks/cover/a.jpg"]


@pytest.mark.parametrize("url", COVER_URLS)
@pytest.mark.parametrize(
    "upstream_resp",
    [
        FakeResp(status_code=404),
        FakeResp(status_code=500),
        FakeResp(content_type="text/html"),
        FakeResp(content_type=None),
    ],
    ids=["404", "500", "html", "no-content-type"],
)
def test_cover_bad_upstream_is_404_uncached(client, upstream, url, upstream_resp):
    upstream.response = upstream_resp
    resp = client.get(url)
    assert resp.status_code == 404
    assert "Cache-Control" not in resp.headers


@pytest.mark.parametrize("url", COVER_URLS)
def test_cover_request_exception_is_502_uncached(client, upstream, url):
    upstream.exc = requests.ConnectTimeout("boom")
    resp = client.get(url)
    assert resp.status_code == 502
    assert "Cache-Control" not in resp.headers


@pytest.mark.parametrize(
    "path",
    [
        "images/covers/a.svg",
        "secret.txt",
        "noextension",
        "../a.jpg",
        "images/../../a.jpg",
    ],
)
def test_standard_ebooks_cover_rejects_bad_paths_without_upstream_call(
    client, upstream, path
):
    resp = client.get(f"/standard_ebooks/cover/{path}")
    assert resp.status_code == 404
    assert upstream.calls == []


def test_standard_ebooks_cover_extension_check_is_case_insensitive(client, upstream):
    assert client.get("/standard_ebooks/cover/a/B.JPG").status_code == 200


def test_standard_ebooks_results_rewrite_only_se_covers(client, monkeypatch):
    books = [
        {
            "id": "a",
            "title": "A",
            "author": "x",
            "coverImageUrl": "https://standardebooks.org/images/covers/a.jpg",
        },
        {
            "id": "b",
            "title": "B",
            "author": "y",
            "coverImageUrl": "https://other.example/b.jpg",
        },
    ]
    monkeypatch.setattr(standard_ebooks, "search_book_by_provider", lambda p, q: books)
    html = client.get("/standard_ebooks/search?q=x").get_data(as_text=True)
    assert 'src="/standard_ebooks/cover/images/covers/a.jpg"' in html
    assert 'src="https://other.example/b.jpg"' in html
    assert "https://standardebooks.org/images" not in html

import socket

import pytest

from kindler import util

DNS = {
    "medium.com": ["162.159.152.4", "162.159.153.4"],
    "netflixtechblog.com": ["162.159.153.4", "162.159.152.4"],
    "example.com": ["104.20.23.154"],
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def lookup(host):
        if host not in DNS:
            raise socket.gaierror("no such host")
        return host, [], DNS[host]

    monkeypatch.setattr(util.socket, "gethostbyname_ex", lookup)


@pytest.mark.parametrize(
    "url",
    ["https://medium.com/@a/post-1", "https://netflixtechblog.com/post-2?x=1"],
)
def test_medium_sites_go_through_mirror(url):
    assert util.redirect_medium(url) == "https://freedium-mirror.cfd/" + url


@pytest.mark.parametrize(
    "url",
    ["https://example.com/a", "https://unknown.invalid/", "not a url", "http://[abc/x"],
)
def test_other_urls_unchanged(url):
    assert util.redirect_medium(url) == url


def test_mirror_failure_falls_back_to_original(monkeypatch):
    fetched = []

    def fetch(url):
        fetched.append(url)
        if url.startswith("https://freedium-mirror.cfd/"):
            raise util.requests.ConnectionError("down")
        return False, "original"

    monkeypatch.setattr(util, "_is_blob_content", fetch)
    url = "https://medium.com/@a/post-1"
    assert util.is_blob_content(url) == (False, "original")
    assert fetched == ["https://freedium-mirror.cfd/" + url, url]

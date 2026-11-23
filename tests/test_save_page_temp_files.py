import subprocess

import pytest

wikipedia = pytest.importorskip("kindler.api.wikipedia")

ARTICLE = {"title": "Kindle", "content": "<p>x</p>", "url": "u", "cover": None}


@pytest.fixture
def client(app, monkeypatch, tmp_path):
    app.register_blueprint(wikipedia.wikipedia_bp, url_prefix="/wikipedia")
    monkeypatch.setattr(wikipedia.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(wikipedia, "guard", lambda url: None)
    monkeypatch.setattr(
        wikipedia, "get_wikipedia_article_with_cover_image", lambda *a: ARTICLE
    )
    return app.test_client()


def test_conversion_leaves_no_temp_files(client, monkeypatch, tmp_path):
    def convert(cmd, check):
        with open(cmd[2], "wb") as f:
            f.write(b"EPUB")

    monkeypatch.setattr(wikipedia.subprocess, "run", convert)
    response = client.get("/wikipedia/save_page?q=Kindle&format=epub")
    assert response.status_code == 200
    assert response.data == b"EPUB"
    assert list(tmp_path.iterdir()) == []


def test_failed_conversion_leaves_no_temp_files(client, monkeypatch, tmp_path):
    def fail(cmd, check):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(wikipedia.subprocess, "run", fail)
    response = client.get("/wikipedia/save_page?q=Kindle&format=epub")
    assert response.status_code == 500
    assert list(tmp_path.iterdir()) == []

import fakeredis
import pytest
from flask import Flask

from kindler import abuse
from kindler.api.error import error_bp


@pytest.fixture
def app():
    app = Flask(
        "kindler", root_path=str(__import__("pathlib").Path(abuse.__file__).parent)
    )
    app.register_blueprint(error_bp)
    return app


@pytest.fixture
def fake_redis(monkeypatch):
    r = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(abuse, "_redis", r)
    return r

import pytest
from ddgs.exceptions import DDGSException

wikipedia = pytest.importorskip("kindler.api.wikipedia")


class FailingDDGS:
    def text(self, *args, **kwargs):
        raise DDGSException("No results found.")


def test_search_without_results_renders_empty_page(app, monkeypatch):
    from kindler.api.home import home_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(wikipedia.wikipedia_bp)
    monkeypatch.setattr(wikipedia, "has_wikipedia_article", lambda query: False)
    monkeypatch.setattr(wikipedia, "DDGS", FailingDDGS)

    response = app.test_client().get("/wikipedia/search?q=qzxvbnmplk")

    assert response.status_code == 200
    assert b"qzxvbnmplk" in response.data

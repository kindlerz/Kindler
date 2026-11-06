from kindler.api.home import home_bp


def test_robots_txt_disallows_anthropic_agents(app):
    app.register_blueprint(home_bp)
    resp = app.test_client().get("/robots.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    for agent in ("ClaudeBot", "Claude-SearchBot", "Claude-User"):
        assert f"User-agent: {agent}" in body
    assert "Disallow: /" in body

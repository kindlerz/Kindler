import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def test_429_returns_real_status_and_short_message(client):
    r = client.get("/error?status_code=429")
    assert r.status_code == 429
    assert b"Daily limit of 10 conversions reached" in r.data
    assert b"try again later" in r.data.lower()
    assert r.headers["Retry-After"] == "172800"


def test_403_network_returns_403_and_network_message(client):
    r = client.get("/error?status_code=403&reason=network")
    assert r.status_code == 403
    assert b"Datacenter or VPN" in r.data


def test_plain_403_still_200(client):
    r = client.get("/error?status_code=403")
    assert r.status_code == 200
    assert b"Website denied access (403)" in r.data


def test_403_other_reason_still_200(client):
    r = client.get("/error?status_code=403&reason=other")
    assert r.status_code == 200
    assert b"Website denied access (403)" in r.data


@pytest.mark.parametrize(
    "code,text",
    [
        ("400", b"Please provide a URL"),
        ("401", b"(401)"),
        ("404", b"Page not found"),
        ("500", b"internal error"),
    ],
)
def test_other_codes_unchanged_200(client, code, text):
    r = client.get(f"/error?status_code={code}")
    assert r.status_code == 200
    assert text in r.data


def test_reason_network_ignored_for_non_403(client):
    r = client.get("/error?status_code=404&reason=network")
    assert r.status_code == 200


def test_unknown_code_200(client):
    assert client.get("/error?status_code=418").status_code == 200

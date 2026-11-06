import threading
from datetime import datetime, timezone

import pytest

from kindler import abuse

IP = "203.0.113.7"


def call_guard(app, ip=IP, headers=None):
    h = {"CF-Connecting-IP": ip} if headers is None else headers
    with app.test_request_context("/", headers=h):
        return abuse.guard("http://example.com")


def location(resp):
    return resp.headers["Location"]


# ---- _normalise ----


def test_normalise_ipv4():
    assert abuse._normalise(" 1.2.3.4 ") == "1.2.3.4"


def test_normalise_ipv6_collapses_to_64():
    a = abuse._normalise("2001:db8:1:2:aaaa::1")
    b = abuse._normalise("2001:db8:1:2:bbbb::ffff")
    assert a == b == "2001:db8:1:2::/64"


def test_normalise_ipv6_different_64_differs():
    assert abuse._normalise("2001:db8:1:2::1") != abuse._normalise("2001:db8:1:3::1")


@pytest.mark.parametrize("bad", ["garbage", "", None, "1.2.3"])
def test_normalise_invalid_returns_none(bad):
    assert abuse._normalise(bad) is None


# ---- _client_key ----


def test_client_key_prefers_cf_header(app):
    with app.test_request_context(
        "/",
        headers={"CF-Connecting-IP": "1.1.1.1"},
        environ_base={"REMOTE_ADDR": "9.9.9.9"},
    ):
        assert abuse._client_key() == "1.1.1.1"


def test_client_key_falls_back_to_remote_addr(app):
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "9.9.9.9"}):
        assert abuse._client_key() == "9.9.9.9"


def test_client_key_invalid_header_falls_back(app):
    with app.test_request_context(
        "/",
        headers={"CF-Connecting-IP": "not-an-ip"},
        environ_base={"REMOTE_ADDR": "9.9.9.9"},
    ):
        assert abuse._client_key() == "9.9.9.9"


def test_client_key_none_when_no_valid_ip(app):
    with app.test_request_context(
        "/", headers={"CF-Connecting-IP": "bad"}, environ_base={"REMOTE_ADDR": "bad"}
    ):
        assert abuse._client_key() is None


def test_client_key_ipv6_header_is_64(app):
    with app.test_request_context("/", headers={"CF-Connecting-IP": "2001:db8::1"}):
        assert abuse._client_key() == "2001:db8::/64"


# ---- guard: quota ----


def test_first_ten_pass_eleventh_rejected_429_and_sets_block(app, fake_redis):
    for _ in range(10):
        assert call_guard(app) is None
    resp = call_guard(app)
    assert resp is not None and resp.status_code == 302
    assert "status_code=429" in location(resp)
    assert fake_redis.get(f"block:{IP}") == b"quota"


def test_later_requests_blocked_with_429(app, fake_redis):
    for _ in range(11):
        call_guard(app)
    for _ in range(3):
        resp = call_guard(app)
        assert "status_code=429" in location(resp)


def test_ipv6_same_64_shares_quota(app, fake_redis):
    for i in range(10):
        assert call_guard(app, ip=f"2001:db8:1:2::{i + 1:x}") is None
    resp = call_guard(app, ip="2001:db8:1:2:ffff::1")
    assert "status_code=429" in location(resp)


def test_different_ips_have_separate_quota(app, fake_redis):
    for _ in range(11):
        call_guard(app, ip="1.1.1.1")
    assert call_guard(app, ip="2.2.2.2") is None


def test_new_utc_day_gets_fresh_counter(app, fake_redis, monkeypatch):
    class Day1(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    class Day2(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(abuse, "datetime", Day1)
    for _ in range(10):
        assert call_guard(app) is None
    assert fake_redis.get("quota:%s:2026-01-01" % IP) == b"10"
    monkeypatch.setattr(abuse, "datetime", Day2)
    assert call_guard(app) is None
    assert fake_redis.get("quota:%s:2026-01-02" % IP) == b"1"


def test_block_key_ttl_about_48h(app, fake_redis):
    for _ in range(11):
        call_guard(app)
    ttl = fake_redis.ttl(f"block:{IP}")
    assert 48 * 3600 - 10 <= ttl <= 48 * 3600


# ---- guard: datacenter/VPN ----


def test_datacenter_gets_403_network_and_block_key(app, fake_redis, monkeypatch):
    monkeypatch.setattr(abuse, "is_datacenter_or_vpn", lambda ip: True)
    resp = call_guard(app)
    assert "status_code=403" in location(resp)
    assert "reason=network" in location(resp)
    assert fake_redis.get(f"block:{IP}") == b"network"
    assert 48 * 3600 - 10 <= fake_redis.ttl(f"block:{IP}") <= 48 * 3600


def test_network_block_persists_even_if_no_longer_datacenter(
    app, fake_redis, monkeypatch
):
    monkeypatch.setattr(abuse, "is_datacenter_or_vpn", lambda ip: True)
    call_guard(app)
    monkeypatch.setattr(abuse, "is_datacenter_or_vpn", lambda ip: False)
    resp = call_guard(app)
    assert "status_code=403" in location(resp)
    assert "reason=network" in location(resp)
    assert "429" not in location(resp)


def test_network_block_not_overwritten_by_quota(app, fake_redis, monkeypatch):
    monkeypatch.setattr(abuse, "is_datacenter_or_vpn", lambda ip: True)
    for _ in range(15):
        call_guard(app)
    assert fake_redis.get(f"block:{IP}") == b"network"
    assert fake_redis.get(f"quota:{IP}:{datetime.now(timezone.utc):%Y-%m-%d}") is None


# ---- guard: failure mode ----


def test_redis_error_fails_open(app, monkeypatch):
    class Boom:
        def get(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(abuse, "_redis", Boom())
    assert call_guard(app) is None


def test_redis_pipeline_error_fails_open(app, fake_redis, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(fake_redis, "pipeline", boom)
    assert call_guard(app) is None


def test_no_valid_ip_fails_open_without_touching_redis(app, fake_redis):
    with app.test_request_context(
        "/", headers={"CF-Connecting-IP": "bad"}, environ_base={"REMOTE_ADDR": "bad"}
    ):
        assert abuse.guard("http://example.com") is None
    assert fake_redis.keys("*") == []


# ---- concurrency ----


def test_concurrent_requests_same_ip_let_exactly_ten_through(app, fake_redis):
    n = 50
    barrier = threading.Barrier(n)
    results = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        r = call_guard(app)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == n
    passed = [r for r in results if r is None]
    rejected = [r for r in results if r is not None]
    assert len(passed) == abuse.DAILY_QUOTA
    assert len(rejected) == n - abuse.DAILY_QUOTA
    assert all("status_code=429" in location(r) for r in rejected)


# ---- guard only applies to ebook formats ----


@pytest.mark.parametrize(
    "fmt,expected_calls",
    [("html", 0), ("txt", 0), ("md", 0), ("epub", 1), ("mobi", 1), ("azw3", 1)],
)
def test_web_save_page_guards_only_ebook_formats(app, monkeypatch, fmt, expected_calls):
    from flask import redirect

    web = pytest.importorskip("kindler.api.web")

    calls = []

    def fake_guard(url=None):
        calls.append(url)
        return redirect("/blocked")

    monkeypatch.setattr(web, "guard", fake_guard)

    def no_fetch(*a, **k):
        raise RuntimeError("fetched")

    monkeypatch.setattr(web.requests, "get", no_fetch)
    with app.test_request_context(
        "/web/save_page?url=http://example.com&format=" + fmt
    ):
        if expected_calls:
            resp = web.save_page()
            assert resp.headers["Location"] == "/blocked"
        else:
            with pytest.raises(RuntimeError):
                web.save_page()
    assert len(calls) == expected_calls

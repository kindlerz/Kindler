import logging

import pytest

from kindler import abuse


@pytest.fixture
def lists(tmp_path, monkeypatch):
    """Point the loader at a tiny temp list and reset the lazy cache."""
    (tmp_path / "datacenter_ipv4.txt").write_text(
        "# comment\n"
        "\n"
        "10.0.0.0/24\n"
        "not-a-cidr\n"
        "10.1.0.0/16\n"
        "10.1.5.0/24\n"  # inside the /16
        "10.2.0.0/24\n"  # adjacent pair collapses with the next
        "10.2.1.0/24\n"
        "2001:db8::/32\n"  # wrong family for the v4 file, ignored
    )
    (tmp_path / "datacenter_ipv6.txt").write_text("2001:db8:1::/48\nbogus\n")
    monkeypatch.setattr(abuse, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(abuse, "_ranges", None)
    yield tmp_path
    monkeypatch.setattr(abuse, "_ranges", None)


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("10.0.0.0", True),  # first address
        ("10.0.0.255", True),  # last address
        ("10.0.0.77", True),
        ("9.255.255.255", False),
        ("10.0.1.0", False),
        ("10.1.5.9", True),
        ("10.1.255.255", True),
        ("10.2.0.255", True),
        ("10.2.1.0", True),
        ("10.2.2.0", False),
        ("8.8.8.8", False),
    ],
)
def test_ipv4(lists, ip, expected):
    assert abuse.is_datacenter_or_vpn(ip) is expected


def test_overlap_and_adjacent_collapse(lists):
    starts, _ = abuse._get_ranges()[4]
    assert len(starts) == 3  # 10.0.0/24, 10.1/16, 10.2.0/23


@pytest.mark.parametrize(
    "key,expected",
    [
        ("2001:db8:1:5::/64", True),
        ("2001:db8:1:ffff::/64", True),
        ("2001:db8:2::/64", False),
        ("2001:db8:0:ffff::/64", False),
    ],
)
def test_ipv6_64_key(lists, key, expected):
    assert abuse.is_datacenter_or_vpn(key) is expected


def test_invalid_input_is_false(lists):
    assert abuse.is_datacenter_or_vpn("garbage") is False


def test_missing_files_fail_open_and_warn_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(abuse, "_DATA_DIR", tmp_path / "nope")
    monkeypatch.setattr(abuse, "_ranges", None)
    with caplog.at_level(logging.WARNING):
        assert abuse.is_datacenter_or_vpn("10.0.0.1") is False
        assert abuse.is_datacenter_or_vpn("2001:db8::/64") is False
        assert abuse.is_datacenter_or_vpn("10.0.0.2") is False
    warnings = [r for r in caplog.records if "unavailable" in r.getMessage()]
    assert len(warnings) == 2  # one per missing file, only on first load
    monkeypatch.setattr(abuse, "_ranges", None)


def test_guard_redirects_listed_ip_to_403(app, fake_redis, lists):
    with app.test_request_context("/", headers={"CF-Connecting-IP": "10.0.0.5"}):
        resp = abuse.guard("http://example.com")
    assert resp.status_code == 302
    assert "403" in resp.headers["Location"]
    assert "reason=network" in resp.headers["Location"]
    assert fake_redis.keys("*") == []

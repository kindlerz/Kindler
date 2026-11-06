import bisect
import ipaddress
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import redis
from flask import redirect, request, url_for

from kindler.cache import REDIS_URL

DAILY_QUOTA = 10
BLOCK_TTL_SECONDS = 48 * 60 * 60

_redis = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


_DATA_DIR = Path(__file__).parent / "data"
_LIST_FILES = {4: "datacenter_ipv4.txt", 6: "datacenter_ipv6.txt"}
_ranges = None
_ranges_lock = threading.Lock()


def _load_ranges(path, version):
    """Parse a CIDR list into sorted, non-overlapping (starts, ends) int lists."""
    nets = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                nets.append(ipaddress.ip_network(line, strict=False))
            except ValueError:
                continue
    merged = sorted(
        ipaddress.collapse_addresses([n for n in nets if n.version == version]),
        key=lambda n: int(n.network_address),
    )
    return (
        [int(n.network_address) for n in merged],
        [int(n.broadcast_address) for n in merged],
    )


def _get_ranges():
    global _ranges
    if _ranges is None:
        with _ranges_lock:
            if _ranges is None:
                loaded = {}
                for version, name in _LIST_FILES.items():
                    try:
                        loaded[version] = _load_ranges(_DATA_DIR / name, version)
                    except Exception as e:
                        logging.warning("Datacenter IP list %s unavailable: %s", name, e)
                        loaded[version] = ([], [])
                _ranges = loaded
    return _ranges


def is_datacenter_or_vpn(ip):
    """True if the IP (or the network address of an IPv6 /64 key) is in the list."""
    try:
        addr = ipaddress.ip_network(ip, strict=False).network_address
    except ValueError:
        return False
    starts, ends = _get_ranges()[addr.version]
    n = int(addr)
    i = bisect.bisect_right(starts, n) - 1
    return i >= 0 and n <= ends[i]


def _normalise(value):
    """Return the rate-limit key for an IP string, or None if it is invalid."""
    try:
        addr = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def _client_key():
    cf_ip = request.headers.get("CF-Connecting-IP")
    logging.info(
        "Client IP headers: CF-Connecting-IP=%s X-Forwarded-For=%s remote_addr=%s",
        cf_ip,
        request.headers.get("X-Forwarded-For"),
        request.remote_addr,
    )
    return _normalise(cf_ip) or _normalise(request.remote_addr)


def guard(url=None):
    """Return a redirect Response to reject the request, or None to continue."""
    try:
        key = _client_key()
        if key is None:
            logging.warning("No valid client IP found, allowing request")
            return None
        block_key = f"block:{key}"
        blocked_reason = _redis.get(block_key)
        if blocked_reason is not None:
            return _reject(url, key, reason=blocked_reason.decode())
        if is_datacenter_or_vpn(key):
            _redis.set(block_key, "network")
            return _reject(url, key, reason="network")
        quota_key = f"quota:{key}:{datetime.now(timezone.utc):%Y-%m-%d}"
        pipe = _redis.pipeline(transaction=True)
        pipe.incr(quota_key)
        pipe.expire(quota_key, BLOCK_TTL_SECONDS)
        count = pipe.execute()[0]
        if count > DAILY_QUOTA:
            _redis.set(block_key, "quota", ex=BLOCK_TTL_SECONDS, nx=True)
            return _reject(url, key)
    except Exception as e:
        logging.error(f"Abuse guard failed, allowing request: {e}")
    return None


def _reject(url, key, reason=None):
    logging.warning("Rejecting ebook conversion for %s (%s)", key, reason or "quota")
    if reason == "network":
        return redirect(url_for("error.error", status_code=403, reason=reason, url=url))
    return redirect(url_for("error.error", status_code=429, url=url))

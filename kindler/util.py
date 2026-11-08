import logging

import requests
from flask import Response
from requests.exceptions import SSLError

from kindler.cache import cache

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
    "DNT": "1",
}


def is_blob_content(url):
    verify_cert = True
    try:
        head_resp = requests.head(
            url, allow_redirects=True, timeout=5, verify=verify_cert
        )
        content_type = head_resp.headers.get("Content-Type", "").lower()
        if content_type and not (
            content_type.startswith("text/html")
            or content_type.startswith("application/xhtml+xml")
            or content_type.startswith("text/plain")
        ):
            return True, None
    except SSLError as error:
        logging.info(
            f"Cannot get cert, trying without cert verification. Error: {error}"
        )
        verify_cert = False
    except requests.RequestException as error:
        logging.info(
            f"HEAD request failed for {url}, falling back to GET. Error: {error}"
        )
    req = requests.get(
        url, headers=HEADERS, timeout=10, allow_redirects=True, verify=verify_cert
    )
    req.raise_for_status()
    content_type = req.headers.get("Content-Type", "").lower()
    if not (
        content_type.startswith("text/html")
        or content_type.startswith("application/xhtml+xml")
        or content_type.startswith("text/plain")
    ):
        return True, req
    req = redirect_medium(url, req)
    return False, req


def redirect_medium(url, response):
    if 'content="Medium"' not in response.text:
        return response
    try:
        req = requests.get("https://freedium.cfd/" + url, headers=HEADERS, timeout=10)
        req.raise_for_status()
        return req
    except Exception:
        return response


COVER_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
COVER_TTL = 30 * 24 * 60 * 60
COVER_NEGATIVE_TTL = 60 * 60


def _cache_get(key):
    try:
        return cache.get(key)
    except Exception:
        logging.warning("Cover cache read failed", exc_info=True)
        return None


def _cache_set(key, value, timeout):
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logging.warning("Cover cache write failed", exc_info=True)


def _cover_error(status):
    text = "Cover not found" if status == 404 else "Cover unavailable"
    return Response(text, status=status, mimetype="text/plain")


def cover_response(url):
    """Fetch a cover image from a trusted upstream URL and return it, cacheable."""
    key = f"cover:{url}"
    cached = _cache_get(key)
    if cached == "missing":
        return _cover_error(404)
    if cached:
        body, content_type = cached
    else:
        try:
            r = requests.get(url, timeout=5)
        except requests.RequestException:
            return _cover_error(502)
        content_type = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or content_type not in COVER_CONTENT_TYPES:
            _cache_set(key, "missing", COVER_NEGATIVE_TTL)
            return _cover_error(404)
        body = r.content
        _cache_set(key, (body, content_type), COVER_TTL)
    return Response(
        body,
        content_type=content_type,
        headers={
            "Cache-Control": "public, max-age=2592000",
            "X-Content-Type-Options": "nosniff",
        },
    )

import logging

from flask import render_template, Blueprint, request, redirect, url_for
from googlenewsdecoder import gnewsdecoder
from pygooglenews import GoogleNews

from kindler.cache import cache
from urllib.parse import urlparse

news_bp = Blueprint("news", __name__, url_prefix="/news")

EXCLUDED_DOMAINS = {
    "engadget.com",
    "apnews.com",
    "kcra.com",
    "espn.com",
    "kxan.com",
    "pbs.org",
    "fox4kc.com",
    "thehill.com",
    "axios.com",
    "politico.com",
    "nytimes.com",
    "wsj.com",
    "washingtonpost.com",
    "ft.com",
    "sfgate.com",
    "actionnetwork.com",
    "seattletimes.com",
    "phys.org",
}


@news_bp.route("/")
def home():
    return render_template("index_news.html")


# Cache news results for 2 hours per category
@news_bp.route("/search")
@cache.cached(timeout=7200, query_string=True)
def search():
    google_news = GoogleNews()
    category = request.args.get("news-category")
    if "top" == category:
        news = google_news.top_news()
    elif category in ("technology", "business"):
        news = google_news.topic_headlines(category)
    else:
        country_lang = category.split("-")
        google_news = GoogleNews(country=country_lang[0], lang=country_lang[1])
        news = google_news.geo_headlines(country_lang[0])
    return render_template(
        "result_news.html", category=category, results=filter_entries(news["entries"])
    )


# Needs caching of links for 24H TTL
@news_bp.route("/readability")
def readability_page():
    url = decode_google_news_url(request.args.get("url"))
    return redirect(url_for("web.readability_page", url=url, q=""))


# Cache decoded URLs for 30 days (avoids repeated decoding & rate limiting)
@cache.memoize(timeout=30 * 24 * 60 * 60)
def decode_google_news_url(url):
    try:
        decoded_url = gnewsdecoder(url, interval=1)
        if decoded_url.get("status"):
            return decoded_url["decoded_url"]
        else:
            logging.error(f'Error decoding url ${decoded_url["message"]}')
    except Exception as e:
        logging.error(f"Error occurred: {e}")
        return url


def is_excluded(entry) -> bool:
    href = entry.get("source", {}).get("href", "")
    host = (urlparse(href).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in EXCLUDED_DOMAINS)


def filter_entries(entries):
    return [e for e in entries if not is_excluded(e)]

import requests
import logging
from flask import render_template, Blueprint, request, redirect, url_for

from kindler.config import GUTENDEX_THIRD_PARTY_URL, GUTENDEX_SELF_HOST_URL
import wikipediaapi

wikipedia_bp = Blueprint("wikipedia", __name__, url_prefix="/wikipedia")

wiki = wikipediaapi.Wikipedia(user_agent='MyProjectName (merlin@example.com)', language='en',
                                       extract_format=wikipediaapi.ExtractFormat.HTML)


@wikipedia_bp.route("/")
def home():
    return render_template("index_wikipedia.html")


@wikipedia_bp.route("/search")
def search():
    query = request.args.get("q")
    return redirect(url_for("wikipedia.readability_page", q=query))


@wikipedia_bp.route("/readability")
def readability_page():
    query = request.args.get("q")
    result = wiki.page(query)
    links = result.links
    content = result.text
    for title in links.keys():
        content = content.replace(title, f"<a href={url_for("wikipedia.readability_page", q=title)}>{title}</a>", 1)
    return render_template("read_wikipedia.html", query=query, title=result.title, content=content, url = result.fullurl)


def search_book_from_gutendex_api(query):
    try:
        response = requests.get(
            GUTENDEX_SELF_HOST_URL, params={"search": query}, timeout=5
        )
        logging.info(f"Successfully called self-hosted Gutendex for: '{query}' keyword")
        return response
    except (requests.ConnectionError, requests.Timeout):
        logging.info(
            f"Failed to call self-hosted Gutendex for: '{query}' keyword. Trying third-party now"
        )
        return requests.get(
            GUTENDEX_THIRD_PARTY_URL, params={"search": query}, timeout=5
        )


def retrieve_book_details_by_id_from_gutendex_api(book_id):
    try:
        response = requests.get(f"{GUTENDEX_SELF_HOST_URL}{book_id}", timeout=5)
        logging.info(
            f"Successfully called self-hosted Gutendex to retrieve book details of book_id: '{book_id}'"
        )
        return response
    except (requests.ConnectionError, requests.Timeout):
        logging.info(
            f"Failed to call self-hosted Gutendex to retrieve book details of book_id: '{book_id}'. Trying third-party now"
        )
        return requests.get(f"{GUTENDEX_THIRD_PARTY_URL}{book_id}", timeout=5)

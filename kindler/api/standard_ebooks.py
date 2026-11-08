from flask import render_template, Blueprint, request, abort

from kindler.integration.metasearch import (
    get_book_details,
    Provider,
    search_book_by_provider,
)

from kindler.util import cover_response

STANDARD_EBOOKS_HOST = "https://standardebooks.org"
COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

standard_ebooks_bp = Blueprint(
    "standard_ebooks", __name__, url_prefix="/standard_ebooks"
)


@standard_ebooks_bp.route("/")
def home():
    return render_template("index_standard_ebooks.html")


@standard_ebooks_bp.route("/search")
def search():
    # TODO - support multiple pages
    query = request.args.get("q")
    books = search_book_by_provider(Provider.STANDARD_EBOOKS, query)
    return render_template(
        "result_standard_ebooks.html",
        query=query,
        results=books,
        se_host=STANDARD_EBOOKS_HOST,
    )


@standard_ebooks_bp.route("/readability")
def readability_page():
    query = request.args.get("q")
    book_id = request.args.get("id")
    book_details = get_book_details(book_id)
    return render_template("read_standard_ebooks.html", query=query, book=book_details)


@standard_ebooks_bp.route("/cover/<path:path>")
def cover(path):
    if (
        "?" in path
        or "#" in path
        or not path.lower().endswith(COVER_EXTENSIONS)
        or ".." in path.split("/")
    ):
        abort(404)
    return cover_response(f"{STANDARD_EBOOKS_HOST}/{path}")

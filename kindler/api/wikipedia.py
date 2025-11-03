import logging
import os
import subprocess
import tempfile

import wikipediaapi
from flask import redirect, url_for
from flask import render_template, Blueprint, request, Response, send_file, abort
from pathvalidate import sanitize_filename

wikipedia_bp = Blueprint("wikipedia", __name__, url_prefix="/wikipedia")

wiki = wikipediaapi.Wikipedia(
    user_agent="Kindler (kasra@madadipouya.com)",
    language="en",
    extract_format=wikipediaapi.ExtractFormat.HTML,
)

allowed_formats = {"html", "epub", "mobi", "azw3"}


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
    article = get_wikipedia_article(query)
    return render_template(
        "read_wikipedia.html",
        query=query,
        title=article["title"],
        content=article["content"],
        url=article["url"],
    )


@wikipedia_bp.route("/save_page")
def save_page():
    query = request.args.get("q")
    save_format = request.args.get("format", "html")
    if not query:
        return "No page is provided", 400
    if save_format not in allowed_formats:
        abort(400, "Invalid format")

    article = get_wikipedia_article(query)
    html_content = render_template(
        "read_save_formatted.html",
        title=article["title"],
        content=article["content"],
        url=article["url"],
    )
    if "html" == save_format:
        response = Response(html_content, mimetype="text/html")
        response.headers["Content-Disposition"] = (
            f"attachment; filename={sanitize_filename(article['title'] + '.html')}"
        )
        return response
    else:
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as html_tmp:
            html_tmp.write(html_content)
            input_html_file = html_tmp.name
        with tempfile.NamedTemporaryFile(
            suffix=f".{save_format}", delete=False
        ) as output_tmp:
            output_file = output_tmp.name
        try:
            subprocess.run(
                [
                    "ebook-convert",
                    input_html_file,
                    output_file,
                    "--title",
                    article["title"],
                    "--authors",
                    "Wikipedia",
                    "--chapter",
                    "//h2",
                    "--level1-toc",
                    "//h1",
                    "--chapter-mark",
                    "pagebreak",
                ],
                check=True,
            )
            download_file_name = sanitize_filename(f"{article['title']}.{save_format}")
            response = send_file(
                output_file, as_attachment=True, download_name=download_file_name
            )

            @response.call_on_close
            def cleanup():
                for f in [input_html_file, output_file]:
                    try:
                        os.remove(f)
                        logging.info(f"File {f} deleted")
                    except OSError:
                        pass

            return response
        except subprocess.CalledProcessError as e:
            os.remove(input_html_file)
            if os.path.exists(output_file):
                os.remove(output_file)
            abort(500, f"Conversion failed: {e}")


def get_wikipedia_article(query):
    article = {}
    result = wiki.page(query)
    links = result.links
    content = result.text
    for title in links.keys():
        content = content.replace(
            title,
            f"<a href={url_for("wikipedia.readability_page", q=title)}>{title}</a>",
            1,
        )
    article["content"] = content
    article["title"] = result.title
    article["url"] = result.fullurl
    return article

import logging
import os
import subprocess
import tempfile
import re
import textwrap
from urllib.parse import quote, unquote, urlsplit

from ddgs import DDGS
from markitdown import MarkItDown
import io
import requests
import wikipediaapi
from flask import redirect, url_for
from flask import render_template, Blueprint, request, Response, send_file, abort
from pathvalidate import sanitize_filename

from kindler.abuse import guard

wikipedia_bp = Blueprint("wikipedia", __name__, url_prefix="/wikipedia")

USER_AGENT_NAME = "Kindler (kasra@madadipouya.com)"

USER_AGENT_HEADER = {"User-Agent": USER_AGENT_NAME}

wiki = wikipediaapi.Wikipedia(
    user_agent=USER_AGENT_NAME,
    language="en",
    extract_format=wikipediaapi.ExtractFormat.HTML,
)

allowed_formats = {"html", "txt", "md", "epub", "mobi", "azw3"}

md = MarkItDown(enable_plugins=False)


@wikipedia_bp.route("/")
def home():
    return render_template("index_wikipedia.html")


@wikipedia_bp.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        logging.warning("Search query is empty.")
        return "Please provide a search query.", 400
    if has_wikipedia_article(query):
        return redirect(url_for("wikipedia.readability_page", q=query))
    else:
        results = DDGS().text(query, max_results=100, backend=["wikipedia"])
        return render_template("result_wikipedia.html", query=query, results=results)


@wikipedia_bp.route("/readability")
def readability_page():
    query = request.args.get("q")
    url = request.args.get("url")
    title = title_from_url(url) if url else query
    article = get_wikipedia_article(title, False)
    if article is None:
        logging.warning(f"Wikipedia article not found for title: {title}")
        return redirect(url_for("error.error", status_code=404, url=url))
    return render_template(
        "read_wikipedia.html",
        query=query,
        title=article["title"],
        content=article["content"],
        url=unquote(article["url"]),
    )


@wikipedia_bp.route("/save_page")
def save_page():
    query = request.args.get("q")
    url = request.args.get("url")
    save_format = request.args.get("format", "html")
    if not query and not url:
        return "No page is provided", 400
    if save_format not in allowed_formats:
        abort(400, "Invalid format")
    if save_format in {"epub", "mobi", "azw3"}:
        blocked = guard(url)
        if blocked:
            return blocked

    keep_original_links = "txt" == save_format or "md" == save_format
    title = title_from_url(url) if url else query
    article = get_wikipedia_article_with_cover_image(title, keep_original_links)
    if article is None:
        logging.warning(f"Wikipedia article not found for title: {title}")
        return redirect(url_for("error.error", status_code=404, url=url))
    html_content = render_template(
        "read_save_formatted.html",
        title=article["title"],
        content=article["content"],
        url=article["url"],
    )
    if "html" == save_format:
        response = Response(html_content, mimetype="text/html")
        response.headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(sanitize_filename(article['title'] + '.html'))}"
        )
        return response
    elif "txt" == save_format:
        text_content = markdown_to_text(extract_markdown(wrap_to_html(article)))
        response = Response(text_content, mimetype="text/plain")
        response.headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(sanitize_filename(article['title'] + '.txt'))}"
        )
        return response
    elif "md" == save_format:
        markdown_content = extract_markdown(wrap_to_html(article))
        response = Response(markdown_content, mimetype="text/plain")
        response.headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(sanitize_filename(article['title'] + '.md'))}"
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
            cmd = [
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
            ]
            if article["cover"]:
                cmd.extend(["--cover", article["cover"]])
            subprocess.run(
                cmd,
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


def get_wikipedia_article_with_cover_image(query, keep_original_links):
    article = get_wikipedia_article(query, keep_original_links)
    if article is None:
        return None
    article["cover"] = download_cover_image(query)
    return article


NON_ARTICLE_NAMESPACES = {
    "talk",
    "user",
    "wikipedia",
    "wp",
    "project",
    "file",
    "image",
    "media",
    "mediawiki",
    "template",
    "help",
    "category",
    "portal",
    "draft",
    "module",
    "special",
    "timedtext",
}


def title_from_url(url):
    # /wikipedia gets decoded URLs (read_wikipedia.html unquotes them), so a `?`
    # belongs to the title; `#` can't be in a title, so it starts a fragment.
    path = url.partition("/wiki/")[2] or url.split("/")[-1]
    return unquote(path.split("#")[0])


def wikipedia_title(url):
    """Article title for an encoded English Wikipedia article URL, else None."""
    parsed = urlsplit(url or "")  # urlparse would drop ";..." from the path
    # `wiki` only queries en.wikipedia.org
    if parsed.hostname not in ("en.wikipedia.org", "en.m.wikipedia.org"):
        return None
    # ?oldid=, ?diff=, ?action=history are not the current article
    if parsed.query or not parsed.path.startswith("/wiki/"):
        return None
    title = unquote(parsed.path[len("/wiki/") :]).replace("_", " ")
    namespace = title.split(":", 1)[0].strip().lower() if ":" in title else ""
    if namespace in NON_ARTICLE_NAMESPACES or namespace.endswith(" talk"):
        return None
    return title or None


def get_wikipedia_article(
    query,
    keep_original_links,
    link_for=lambda title: url_for("wikipedia.readability_page", q=title),
):
    result = wiki.page(query)
    if not result.exists():
        return None
    article = {}
    links = result.links
    content = result.text
    linked = set()

    def link(match):
        title = match.group(0)
        if title in linked:
            return title
        linked.add(title)
        if keep_original_links:
            href = "http://wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
            return f"<a href='{href}'>{title}</a>"
        return f"<a href={link_for(title)}>{title}</a>"

    # one pass, longest title first, so inserted anchors are never rescanned
    if links:
        titles = sorted(links, key=len, reverse=True)
        content = re.sub("|".join(map(re.escape, titles)), link, content)
    article["content"] = content
    article["title"] = result.title
    article["url"] = result.fullurl
    return article


def has_wikipedia_article(query):
    result = wiki.page(query)
    return bool(result.links)


def download_cover_image(query):
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": query,
        "format": "json",
        "pithumbsize": 1000,
        "prop": "pageimages|pageterms",
        "piprop": "thumbnail",
        "redirects": 1,
    }
    data = requests.get(url, params=params, headers=USER_AGENT_HEADER).json()
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    return page.get("thumbnail", {}).get("source")


def extract_markdown(html):
    return md.convert(io.BytesIO(html.encode("utf-8"))).text_content


def markdown_to_text(md, width=80, max_empty_lines=1):
    lines = md.splitlines()
    output = []
    in_code_block = False
    code_lines = []
    empty_count = 0  # track consecutive empty lines

    for line in lines:
        line = line.rstrip()

        # --- Handle code blocks ---
        if line.startswith("```"):
            if in_code_block:
                # End of code block: append collected lines
                if code_lines:
                    output.append("[code block]")
                    output.extend(code_lines)
                    output.append("[code block]")
                    output.append("")
                    code_lines = []
                in_code_block = False
            else:
                # Start of code block
                in_code_block = True
            continue

        if in_code_block:
            # Collect code lines (do not wrap or alter)
            code_lines.append(line)
            continue

        # --- Strip Markdown links ---
        line = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", line)

        # --- Headers ---
        header_match = re.match(r"^(#{1,6})\s*(.*)", line)
        if header_match:
            level, text = header_match.groups()
            text = text.strip().upper()
            if output and output[-1] != "":
                output.append("")
            output.append(text)
            output.append("=" * len(text))
            empty_count = 0
            continue

        # --- Lists (unordered + ordered) ---
        list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)", line)
        if list_match:
            indent, marker, content = list_match.groups()
            level = len(indent) // 2
            bullet = "- "
            prefix = "  " * level + bullet
            wrapped = textwrap.fill(
                content,
                width=width,
                initial_indent=prefix,
                subsequent_indent="  " * (level + 1),
            )
            output.append(wrapped)
            empty_count = 0
            continue

        # --- Normal paragraph lines ---
        if line.strip():
            wrapped = textwrap.fill(line, width=width)
            output.append(wrapped)
            empty_count = 0
        else:
            # Handle empty lines
            empty_count += 1
            if empty_count <= max_empty_lines:
                output.append("")

    return "\n".join(output).strip()


def wrap_to_html(article):
    html = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{article['title']}</title>
    </head>
    <body>
        <h1>{article['title']}</h1>
        {article['content']}
    </body>
    </html>"""
    return html

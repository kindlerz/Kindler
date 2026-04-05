import logging
import os
import subprocess
import tempfile
import re
import textwrap
from markitdown import MarkItDown
import io
import requests
import wikipediaapi
from flask import redirect, url_for
from flask import render_template, Blueprint, request, Response, send_file, abort
from pathvalidate import sanitize_filename

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
    return redirect(url_for("wikipedia.readability_page", q=query))


@wikipedia_bp.route("/readability")
def readability_page():
    query = request.args.get("q")
    article = get_wikipedia_article(query, False)
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

    keep_original_links = "txt" == save_format or "md" == save_format
    article = get_wikipedia_article_with_cover_image(query, keep_original_links)
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
    elif "txt" == save_format:
        text_content = markdown_to_text(extract_markdown(article["content"]))
        response = Response(text_content, mimetype="text/plain")
        response.headers["Content-Disposition"] = (
            f"attachment; filename={sanitize_filename(article['title'] + '.txt')}"
        )
        return response
    elif "md" == save_format:
        markdown_content = extract_markdown(article["content"])
        response = Response(markdown_content, mimetype="text/plain")
        response.headers["Content-Disposition"] = (
            f"attachment; filename={sanitize_filename(article['title'] + '.md')}"
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
    article["cover"] = download_cover_image(query)
    return article


def get_wikipedia_article(query, keep_original_links):
    article = {}
    result = wiki.page(query)
    links = result.links
    content = result.text
    for title in links.keys():
        if keep_original_links:
            content = content.replace(
                title,
                f"<a href='http://wikipedia.org/wiki/{title}'>{title}</a>",
                1,
            )
        else:
            content = content.replace(
                title,
                f"<a href={url_for("wikipedia.readability_page", q=title)}>{title}</a>",
                1,
            )
    article["content"] = content
    article["title"] = result.title
    article["url"] = result.fullurl
    return article


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
    list_stack = []
    in_code_block = False
    empty_count = 0  # track consecutive empty lines

    for line in lines:
        line = line.rstrip()

        # --- Handle code blocks ---
        if line.startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                output.append("[code block]")
            continue
        if in_code_block:
            continue  # skip code content

        # --- Strip Markdown links ---
        line = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", line)

        # --- Headers ---
        header_match = re.match(r"^(#{1,6})\s*(.*)", line)
        if header_match:
            level, text = header_match.groups()
            text = text.strip().upper()
            if output and output[-1] != "":
                output.append("")  # ensure blank line before header
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

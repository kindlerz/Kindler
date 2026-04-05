import logging
import os
import subprocess
import tempfile
from urllib.parse import urljoin, urlparse, quote
from markitdown import MarkItDown
import re
import textwrap
import io
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from flask import render_template, Blueprint, request, Response, redirect, url_for
from flask import send_file, abort
from pathvalidate import sanitize_filename
from readabilipy import simple_json_from_html_string
from readability import Document

from kindler.util import is_blob_content

web_bp = Blueprint("web", __name__, url_prefix="/web")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
    "DNT": "1",
}

allowed_formats = {"html", "txt", "md", "epub", "mobi", "azw3"}

md = MarkItDown(enable_plugins=False)


@web_bp.route("/")
def home():
    return render_template("index_web.html")


@web_bp.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        logging.warning("Search query is empty.")
        return "Please provide a search query.", 400
    results = DDGS().text(query, max_results=100, backend=["duckduckgo"])
    return render_template("result_web.html", query=query, results=results)


@web_bp.route("/readability")
def readability_page():
    query = request.args.get("q")
    alternative_renderer = request.args.get("alternative_renderer")
    url = request.args.get("url")
    if not url:
        logging.warning("Readability URL is empty.")
        return redirect(url_for("error.error", status_code=400, url=url))
    try:
        is_blob, req = is_blob_content(url)
        if is_blob:
            return redirect(url)
        if alternative_renderer:
            article = get_js_readability_result(req.text, url, query, False)
        else:
            article = get_python_readability_result(req.text, url, query, False)
        return render_template(
            "read_web.html",
            title=article["title"],
            query=query,
            content=article["content"],
            url=url,
            alternative_renderer=alternative_renderer,
        )

    except requests.exceptions.RequestException as e:
        logging.warning(f"Network error fetching URL: {e}")
        status_code = 500
        if hasattr(e, "response") and e.response is not None:
            status_code = getattr(e.response, "status_code", 500)
        return redirect(url_for("error.error", status_code=status_code, url=url))
    except Exception as e:
        logging.error(f"An error occurred during readability processing: {e}")
        return f"An error occurred during processing: {e}", 500


@web_bp.route("/save_page")
def save_page():
    url = request.args.get("url")
    query = request.args.get("q")
    alternative_renderer = request.args.get("alternative_renderer")
    save_format = request.args.get("format", "html")
    if not url:
        return "No URL provided", 400
    if save_format not in allowed_formats:
        abort(400, "Invalid format")

    req = requests.get(url, headers=HEADERS, timeout=10)
    keep_original_links = "txt" == save_format or "md" == save_format
    if alternative_renderer:
        article = get_js_readability_result(req.text, url, query, keep_original_links)
    else:
        article = get_python_readability_result(
            req.text, url, query, keep_original_links
        )
    html_content = render_template(
        "read_save_formatted.html",
        title=article["title"],
        content=article["content"],
        url=url,
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
            subprocess.run(
                [
                    "ebook-convert",
                    input_html_file,
                    output_file,
                    "--title",
                    article["title"],
                    "--chapter",
                    "//h2",
                    "--level1-toc",
                    "//h2",
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


def get_python_readability_result(html_content, base_url, query, keep_original_links):
    doc = Document(html_content)
    return {
        "content": clean_readability_html(
            doc.summary(), base_url, query, True, keep_original_links
        ),
        "title": doc.short_title(),
    }


def get_js_readability_result(html_content, base_url, query, keep_original_links):
    article = simple_json_from_html_string(html_content, use_readability=True)
    return {
        "content": clean_readability_html(
            article["content"], base_url, query, keep_original_links
        ),
        "title": article["title"],
    }


def clean_readability_html(
    html_content, base_url, query, only_links_rewrite=False, keep_original_links=False
):
    soup = BeautifulSoup(html_content, "html.parser")

    if keep_original_links:
        rewrite_original_links_to_absolute_links(soup, base_url)
    else:
        rewrite_links(soup, base_url, query)
    remove_images(soup)
    normalize_pre_blocks(soup)
    if only_links_rewrite:
        return clean_output(str(soup))

    # --- Drop navigation/menus explicitly ---
    for nav in soup.find_all("nav"):
        nav.decompose()
    for div in soup.find_all("div", class_=lambda c: c and "nav" in c.lower()):
        div.decompose()
    for ul in soup.find_all(
        "ul", class_=lambda c: c and ("menu" in c.lower() or "nav" in c.lower())
    ):
        ul.decompose()
    for ol in soup.find_all(
        "ol", class_=lambda c: c and ("menu" in c.lower() or "nav" in c.lower())
    ):
        ol.decompose()

    # --- Strip attributes (keep only essential ones) ---
    for tag in soup.find_all(True):
        allowed_attrs = {"a": ["href", "id", "name"], "sup": ["id"]}
        tag.attrs = {
            k: v for k, v in tag.attrs.items() if k in allowed_attrs.get(tag.name, [])
        }

    # --- Whitelist allowed tags ---
    allowed_tags = [
        "p",
        "a",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "br",
        "sup",
        "sub",
        "strong",
        "em",
        "ul",
        "ol",
        "li",
    ]
    for tag in soup.find_all(True):
        if tag.name not in allowed_tags:
            tag.unwrap()

    # --- Remove empty paragraphs ---
    for p in soup.find_all("p"):
        if not p.get_text(strip=True):
            p.decompose()

    # Find all <ul> and <li> tags in the document.
    empty_tags_to_remove = []

    # Iterate over all <li> tags.
    for li_tag in soup.find_all("li"):
        # Check if the tag's text content, after stripping whitespace, is empty.
        if not li_tag.text.strip():
            empty_tags_to_remove.append(li_tag)

    # Iterate over all <ul> tags.
    for ul_tag in soup.find_all("ul"):
        # Check if the tag's text content, after stripping whitespace, is empty.
        # This will also catch <ul> tags that only contained empty <li> tags.
        if not ul_tag.text.strip():
            empty_tags_to_remove.append(ul_tag)

    # Decompose the tags outside the loop to avoid modifying the list being iterated over.
    for tag in empty_tags_to_remove:
        tag.decompose()

    # --- Return cleaned HTML ---
    return clean_output(str(soup))


def rewrite_links(soup, base_url, query):
    # --- Rewrite links to go through /web/readability ---
    readability_endpoint = f"/web/readability?q={query}&url="
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("#"):
            # Remove back-to-top style anchors
            link.decompose()
            continue
        absolute_url = urljoin(base_url, href)
        if urlparse(absolute_url).scheme not in ("http", "https"):
            continue
        encoded = quote(absolute_url, safe="")
        link["href"] = f"{readability_endpoint}{encoded}"


def rewrite_original_links_to_absolute_links(soup, base_url):
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("#"):
            link.decompose()
            continue
        absolute_url = urljoin(base_url, href)
        if urlparse(absolute_url).scheme not in ("http", "https"):
            continue
        link["href"] = absolute_url


def remove_images(soup):
    # --- Remove unhelpful tags (media, scripts, forms, etc.) ---
    for tag in soup.find_all(
        [
            "img",
            "picture",
            "source",
            "figure",
            "script",
            "style",
            "iframe",
            "form",
            "button",
            "noscript",
            "svg",
            "video",
            "audio",
        ]
    ):
        tag.decompose()


def normalize_pre_blocks(soup):
    for pre in soup.find_all("pre"):
        code_tag = pre.find("code")
        if not code_tag:
            continue
        code_text = code_tag.get_text()
        if not code_text.strip():
            continue
        pre.clear()
        pre.string = code_text
        for code in pre.find_all("code"):
            code.unwrap()
        pre["style"] = "font-family:monospace; margin-left:0;"
    return soup


def clean_output(html):
    lines = html.splitlines()
    result = []
    in_pre = False
    for line in lines:
        if "<pre" in line:
            in_pre = True

        if in_pre:
            result.append(line)  # preserve EXACTLY
        else:
            if line.strip():
                result.append(line.strip())

        if "</pre>" in line:
            in_pre = False
    return "\n".join(result)


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

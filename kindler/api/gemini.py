import io
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import textwrap
from urllib.parse import urljoin, urlparse, quote

from bs4 import BeautifulSoup
from flask import render_template, Blueprint, request, Response, send_file, abort, url_for
from markitdown import MarkItDown
from pathvalidate import sanitize_filename

from kindler.gemini_converter import gemtext_to_html

gemini_bp = Blueprint("gemini", __name__, url_prefix="/gemini")

SEARCH_URL = "gemini://tlgs.one"

allowed_formats = {"html", "txt", "md", "epub", "mobi", "azw3"}

md = MarkItDown(enable_plugins=False)

@gemini_bp.route("/")
def home():
    return render_template("index_gemini.html")


@gemini_bp.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        logging.warning("Search query is empty.")
        return "Please provide a search query.", 400
    response = get_gemini_content(f"{SEARCH_URL}/search?{query}")
    html_content = gemtext_to_html(response["content"], is_search=True)["content"]
    return render_template(
        "result_gemini.html",
        query=query,
        content=clean_gemini_html(html_content, SEARCH_URL, query),
    )


@gemini_bp.route("/readability")
def readability_page():
    url = request.args.get("url")
    query = request.args.get("q")
    if not url:
        logging.warning("Readability URL is empty.")
        return "Please provide a URL to clean.", 400
    is_search_page = "gemini://tlgs.one/search" in url
    response = get_gemini_content(url)
    html_content = gemtext_to_html(response["content"], is_search_page)
    return render_template(
        "read_gemini.html",
        title=html_content["title"],
        content=clean_gemini_html(html_content["content"], url, query),
        url=url,
        query=query,
        is_search_page=is_search_page,
    )


@gemini_bp.route("/save_page")
def save_page():
    url = request.args.get("url")
    query = request.args.get("q")
    save_format = request.args.get("format", "html")
    if not url:
        return "No URL provided", 400
    if save_format not in allowed_formats:
        abort(400, "Invalid format")

    article = gemtext_to_html(get_gemini_content(url)["content"])
    html_content = render_template(
        "read_save_formatted.html",
        title=article["title"],
        content=clean_gemini_html(article["content"], url, query),
        url=url,
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
            subprocess.run(
                [
                    "ebook-convert",
                    input_html_file,
                    output_file,
                    "--title",
                    article["title"],
                    "--chapter",
                    "//h1",
                    "--level1-toc",
                    "//h1",
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


def get_gemini_content(url):
    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    path = parsed_url.path or "/"

    port = parsed_url.port or 1965

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        with socket.create_connection((hostname, port)) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                request = (url + "\r\n").encode("utf-8")
                ssock.sendall(request)

                response_header = b""
                while not response_header.endswith(b"\r\n"):
                    response_header += ssock.recv(1)

                status_meta = response_header.decode("utf-8").strip()
                status, meta = status_meta.split(" ", 1)
                status = int(status)

                content = None
                if status == 20:
                    all_content = b""
                    while True:
                        content_bytes = ssock.recv(4096)
                        if not content_bytes:
                            break
                        all_content += content_bytes
                    content = all_content.decode("utf-8")
                return {"status": status, "meta": meta, "content": content}
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        return None


def clean_gemini_html(html_content, base_url, query, is_search=False):
    soup = BeautifulSoup(html_content, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("#"):
            link.decompose()
            continue
        absolute_url = urljoin(base_url, href)
        scheme = urlparse(absolute_url).scheme
        if scheme == "gemini":
            encoded = quote(absolute_url, safe="")
            link["href"] = f"/gemini/readability?q={query}&url={encoded}"
        elif scheme in ("http", "https"):
            encoded = quote(absolute_url, safe="")
            link["href"] = f"/web/readability?q={query}&url={encoded}"
        elif absolute_url.startswith("/"):
            link["href"] = (
                f"/gemini/readability?q={query}&url=gemini://{urlparse(base_url).netloc}{absolute_url}"
            )
        elif scheme == "mailto":
            pass
        else:
            pass

    return str(soup)

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
        {article['content']}
    </body>
    </html>"""
    return html

import html
import re
from html import escape


def escape(text: str) -> str:
    """A helper function to escape HTML characters in text."""
    return html.escape(text)


def gemtext_to_html(gemtext: str, is_search=False) -> dict:
    """
    Converts a Gemtext string into a dictionary containing HTML content and a title.

    This enhanced version correctly handles code blocks, links, and blockquotes,
    providing a more robust conversion.

    Args:
        gemtext: The input Gemtext content as a string.

    Returns:
        A dictionary with "title" and "content" keys, where content is an
        HTML string.
    """
    html_lines = []
    in_list = False
    in_code_block = False
    title = None
    next_page_pattern = r"=> /search/\d+\?.*?➡️ Next Page"
    previous_page_patten = r"=> /search(?:/\d+)?\?.*?⬅️ Previous Page"
    next_page_href = None
    previous_page_href = None
    lines = gemtext.splitlines()
    for i, line in enumerate(lines):
        if is_search:
            if is_search_page_clutter(line):
                continue
            if re.search(next_page_pattern, line) and not next_page_href:
                href, _ = convert_to_href(line)
                next_page_href = f'<a href="{href}">{escape("Next Page")}</a>'
                continue
            if re.search(previous_page_patten, line) and not previous_page_href:
                href, _ = convert_to_href(line)
                previous_page_href = f'<a href="{href}" style="margin-right: 3em;">{escape("Previous Page")}</a>'
                continue

        # Handle code blocks
        if line.startswith("```"):
            if not in_code_block:
                html_lines.append("<code><pre>")
                in_code_block = True
            else:
                html_lines.append("</pre></code>")
                in_code_block = False
            continue

        if in_code_block:
            html_lines.append(escape(line))
            continue

        # Handle lists
        if line.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{escape(line[2:])}</li>")
            continue
        elif in_list:
            html_lines.append("</ul>")
            in_list = False

        # Handle headings
        if line.startswith("### "):
            html_lines.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            heading_text = line[2:]
            if title is None:
                title = heading_text
            if not is_search:
                html_lines.append(f"<h1>{escape(heading_text)}</h1>")
        # Handle links
        elif line.startswith("=>"):
            href, link_text = convert_to_href(line)
            html_lines.append(f'<p><a href="{href}">{escape(link_text)}</a></p>')
        # Handle blockquotes
        elif line.startswith(">"):
            html_lines.append(f"<blockquote>{escape(line[1:].strip())}</blockquote>")
        # Handle regular paragraphs
        else:
            if line:
                html_lines.append(f"<p>{escape(line)}</p>")
            if is_search:
                html_lines.append("<hr />")

    # Close any open list or code block at the end of the file
    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        html_lines.append("</code></pre>")

    if is_search:
        if previous_page_href and next_page_href:
            html_lines.append(
                f'<p style="text-align: center;">{previous_page_href}{next_page_href}</p>'
            )
        elif next_page_href:
            html_lines.append(f'<p style="text-align: center;">{next_page_href}</p>')
    return {"title": title, "content": "\n".join(html_lines)}


def is_search_page_clutter(gemini_line):
    if (
        not gemini_line
        or "=> / 🏠 Home" in gemini_line
        or "=> /search 🔍 Search" in gemini_line
        or "=> /backlinks? 🔙 Query backlinks" in gemini_line
        or "## Search" in gemini_line
        or "📚 Enter verbose search" in gemini_line
        or gemini_line.startswith("* gemini://")
        or "↗️ Go to page" in gemini_line
        or "📦 Archived page" in gemini_line
        or "Use traditional ranking" in gemini_line
    ):
        return True
    return False


def convert_to_href(gemini_line):
    parts = gemini_line[2:].strip().split(maxsplit=1)
    href = parts[0]
    link_text = parts[1] if len(parts) > 1 else href
    return href, link_text

import pytest
import requests

wikipedia = pytest.importorskip("kindler.api.wikipedia")

# action=parse output: code samples sit in div.mw-highlight, which TextExtracts drops
PARSED = """<div class="mw-parser-output">
<p>Intro.</p>
<div class="mw-heading mw-heading2"><h2 id="Examples">Examples</h2></div>
<p>First.</p>
<div class="mw-highlight mw-highlight-lang-c"><pre><span class="k">int</span><span class="w"> </span><span class="n">a</span><span class="p">;</span> <span class="c1">// a &lt;b&gt;</span></pre></div>
<p>Second.</p>
<div class="mw-heading mw-heading3"><h3 id="Examples_2">Examples</h3></div>
<blockquote><p>Quote one.</p><p>Quote two.</p></blockquote>
<p>Third.</p>
<div class="mw-highlight"><pre>last &lt;script&gt;</pre></div>
<pre>bare pre, kept by TextExtracts</pre>
</div>"""

# wikipediaapi's text for the same article
EXTRACT = (
    "<p>Intro.</p>\n\n"
    "<h2>Examples</h2>\n<p>First.</p>\n\n<p>Second.</p>\n\n"
    "<h3>Examples</h3>\n<blockquote><p>Quote one.</p><p>Quote two.</p></blockquote>\n"
    "<p>Third.</p>\n<pre>bare pre, kept by TextExtracts</pre>"
)


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"parse": {"text": PARSED}}


def test_code_goes_after_the_same_paragraph_of_the_same_section(monkeypatch):
    monkeypatch.setattr(wikipedia.requests, "get", lambda *a, **k: FakeResponse())
    content = wikipedia.add_code_blocks(EXTRACT, "X")
    assert content == (
        "<p>Intro.</p>\n\n"
        "<h2>Examples</h2>\n<p>First.</p>\n"
        '<pre><span class="k">int</span> a; <span class="c1">// a &lt;b&gt;</span></pre>\n'
        "\n\n<p>Second.</p>\n\n"
        "<h3>Examples</h3>\n<blockquote><p>Quote one.</p><p>Quote two.</p></blockquote>\n"
        "<p>Third.</p>\n<pre>last &lt;script&gt;</pre>\n"
        "\n<pre>bare pre, kept by TextExtracts</pre>"
    )


def test_page_renders_without_code_when_wikipedia_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError

    monkeypatch.setattr(wikipedia.requests, "get", fail)
    assert wikipedia.add_code_blocks(EXTRACT, "X") == EXTRACT

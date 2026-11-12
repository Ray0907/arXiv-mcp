"""HTML-first full text with PDF fallback; synthetic Markdown only."""

from types import SimpleNamespace

import httpx
import pytest

import arxiv_mcp.content as content
import arxiv_mcp.server as server
from tests.test_reliability import mock_http  # noqa: F401

HTML = "Reader metadata\n###### Abstract\n## 1 Introduction\n" + "Body text. " * 200 + "\n### 1.1 Detail\nMore.\n"
PDF = "# Pdf paper\nOnly a title."
JINA = "https://r.jina.ai/https://arxiv.org"


def routes(html_response, calls):
    def respond(request):
        calls.append(str(request.url))
        if "/html/" in str(request.url):
            return html_response
        return httpx.Response(200, text=PDF)

    return respond


@pytest.mark.asyncio
async def test_html_text_wins_and_skips_pdf(mock_http):
    calls = []
    mock_http(routes(httpx.Response(200, text=HTML), calls))
    assert await server.paper_content("1706.03762") == HTML
    assert calls == [f"{JINA}/html/1706.03762"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="Title: x.svg\n\nMarkdown Content:\nA figure caption."),  # Jina stub on 200
        httpx.Response(200, text="## No article for ''\n\n" + "invalid arXiv identifier. " * 100),  # one heading
        httpx.Response(200, text="# A\n## B\nshort"),  # headings but too short
        httpx.Response(404, text="missing"),
        httpx.Response(500, text="boom"),
    ],
)
@pytest.mark.asyncio
async def test_bad_html_falls_back_to_pdf_and_is_not_cached(response, mock_http, monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr(server.asyncio, "sleep", no_sleep)
    calls = []
    mock_http(routes(response, calls))
    assert await server.paper_content("1706.03762") == PDF
    assert calls[0] == f"{JINA}/html/1706.03762" and calls[-1] == f"{JINA}/pdf/1706.03762"
    assert server._content_cache["1706.03762"][1] == PDF


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError("down"), httpx.DecodingError("gzip"), httpx.TooManyRedirects("loop")])
@pytest.mark.asyncio
async def test_html_transport_failure_falls_back(error, mock_http):
    def respond(request):
        if "/html/" in str(request.url):
            raise error
        return httpx.Response(200, text=PDF)

    mock_http(respond)
    assert await server.paper_content("1706.03762") == PDF


@pytest.mark.asyncio
async def test_both_fail_reports_pdf_error(mock_http):
    mock_http(lambda request: httpx.Response(500 if "/html/" in str(request.url) else 404))
    with pytest.raises(ValueError, match=r"Jina Reader returned HTTP 404"):
        await server.paper_content("1706.03762")
    assert server._content_cache == {}


@pytest.mark.asyncio
async def test_versions_fetch_own_html_and_cache_separately(mock_http):
    calls = []
    mock_http(routes(httpx.Response(200, text=HTML), calls))
    await server.paper_content("1706.03762")
    await server.paper_content("1706.03762v2")
    assert calls == [f"{JINA}/html/1706.03762", f"{JINA}/html/1706.03762v2"]
    assert set(server._content_cache) == {"1706.03762", "1706.03762v2"}


@pytest.mark.parametrize("html_fails", [False, True])
@pytest.mark.asyncio
async def test_html_attempt_gets_its_own_shorter_deadline(html_fails, monkeypatch):
    deadlines = []

    async def get(url, **kwargs):
        kind = url.split("/")[-2]
        deadlines.append((kind, kwargs["timeout"]))
        if kind == "html":
            if html_fails:
                raise ValueError("html down")
            return httpx.Response(200, text=HTML)
        return httpx.Response(200, text=PDF)

    monkeypatch.setattr(server, "_get", get)
    await server.paper_content("1706.03762")
    expected = [("html", server.TIMEOUT)] + ([("pdf", server.TIMEOUT * 2)] if html_fails else [])
    assert deadlines == expected


STUB = httpx.Response(200, text="Title: fig.svg\n\nMarkdown Content:\nA figure caption.")


def sequence(responses, calls):
    queue = list(responses)

    def respond(request):
        calls.append(str(request.url).removeprefix(JINA))
        if "/html/" in str(request.url):
            return queue.pop(0)
        return httpx.Response(200, text=PDF)

    return respond


@pytest.mark.asyncio
async def test_cold_stub_is_retried_once_and_html_wins(mock_http):
    calls = []
    mock_http(sequence([STUB, httpx.Response(200, text=HTML)], calls))
    assert await server.paper_content("1706.03762") == HTML
    assert calls == ["/html/1706.03762"] * 2
    assert content._content_source["1706.03762"] == "html"


@pytest.mark.asyncio
async def test_two_stubs_fall_back_to_pdf_after_exactly_two_html_attempts(mock_http):
    calls = []
    mock_http(sequence([STUB, STUB], calls))
    assert await server.paper_content("1706.03762") == PDF
    assert calls == ["/html/1706.03762"] * 2 + ["/pdf/1706.03762"]
    assert content._content_source["1706.03762"] == "pdf"


@pytest.mark.parametrize("failure", [httpx.Response(500), httpx.Response(404)])
@pytest.mark.asyncio
async def test_status_errors_are_not_retried(failure, mock_http):
    calls = []
    mock_http(sequence([failure, httpx.Response(200, text=HTML)], calls))
    assert await server.paper_content("1706.03762") == PDF
    assert calls == ["/html/1706.03762", "/pdf/1706.03762"]


@pytest.mark.asyncio
async def test_transport_errors_are_not_retried(mock_http):
    calls = []

    def respond(request):
        calls.append(str(request.url).removeprefix(JINA))
        if "/html/" in str(request.url):
            raise httpx.ConnectError("down")
        return httpx.Response(200, text=PDF)

    mock_http(respond)
    assert await server.paper_content("1706.03762") == PDF
    assert calls == ["/html/1706.03762", "/pdf/1706.03762"]


@pytest.mark.parametrize("elapsed,expected", [(10.0, 20.0), (29.0, content.HTML_RETRY_MIN_TIMEOUT)])
@pytest.mark.asyncio
async def test_retry_uses_what_is_left_of_the_html_budget(elapsed, expected, monkeypatch):
    clock, timeouts = [100.0], []

    async def get(url, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock[0] += elapsed
        return httpx.Response(200, text="stub" if len(timeouts) == 1 else HTML)

    monkeypatch.setattr(server, "_get", get)
    monkeypatch.setattr(content, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    assert await server.paper_content("1706.03762") == HTML
    assert timeouts == [server.TIMEOUT, expected]

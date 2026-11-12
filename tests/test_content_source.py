"""A paper ID keeps one text source for the process, so selectors and offsets stay valid."""

import asyncio

import httpx
import pytest

import arxiv_mcp.content as content
import arxiv_mcp.server as server
from tests.test_html_first import HTML, JINA, PDF
from tests.test_reliability import mock_http  # noqa: F401


class Upstream:
    def __init__(self, html=None):
        self.html, self.calls = html, []

    def __call__(self, request):
        url = str(request.url)
        self.calls.append(url.removeprefix(JINA))
        if "/html/" in url:
            if isinstance(self.html, Exception):
                raise self.html
            return self.html or httpx.Response(404)
        return httpx.Response(200, text=PDF)


@pytest.mark.asyncio
async def test_html_source_survives_cache_expiry(mock_http):
    up = Upstream(httpx.Response(200, text=HTML))
    mock_http(up)
    assert await server.paper_content("1706.03762") == HTML
    server._content_cache.clear()
    assert await server.paper_content("1706.03762") == HTML
    assert up.calls == ["/html/1706.03762"] * 2


@pytest.mark.asyncio
async def test_pdf_source_survives_expiry_and_skips_html(mock_http):
    up = Upstream()
    mock_http(up)
    assert await server.paper_content("1706.03762") == PDF
    server._content_cache.clear()
    up.html, up.calls = httpx.Response(200, text=HTML), []
    assert await server.paper_content("1706.03762") == PDF
    assert up.calls == ["/pdf/1706.03762"]


@pytest.mark.parametrize(
    "bad,message",
    [
        (httpx.Response(500), "Jina Reader returned HTTP 500"),
        (httpx.ConnectError("down"), "could not be reached"),
        (httpx.Response(200, text="Title: x.svg\n\nstub"), "no longer usable"),
    ],
)
@pytest.mark.asyncio
async def test_pinned_html_failure_is_an_error_not_a_pdf_switch(bad, message, mock_http):
    up = Upstream(httpx.Response(200, text=HTML))
    mock_http(up)
    await server.paper_content("1706.03762")
    server._content_cache.clear()
    up.html, up.calls = bad, []
    with pytest.raises(ValueError, match=message):
        await server.paper_content("1706.03762")
    assert all("/pdf/" not in call for call in up.calls)
    assert server._content_cache == {}
    up.html = httpx.Response(200, text=HTML)
    assert await server.paper_content("1706.03762") == HTML


@pytest.mark.asyncio
async def test_each_version_pins_its_own_source(mock_http):
    up = Upstream()
    mock_http(up)
    assert await server.paper_content("1706.03762v1") == PDF
    up.html = httpx.Response(200, text=HTML)
    assert await server.paper_content("1706.03762") == HTML
    server._content_cache.clear()
    assert await server.paper_content("1706.03762v1") == PDF
    assert await server.paper_content("1706.03762") == HTML


@pytest.mark.asyncio
async def test_source_memory_is_bounded_and_outlives_content_cache(mock_http, monkeypatch):
    monkeypatch.setattr(content, "CONTENT_SOURCE_SIZE", 2)
    mock_http(Upstream(httpx.Response(200, text=HTML)))
    for paper_id in ("1706.00001", "1706.00002", "1706.00003"):
        await server.paper_content(paper_id)
    assert list(server._content_source) == ["1706.00002", "1706.00003"]


@pytest.mark.asyncio
async def test_concurrent_first_reads_converge_on_the_first_pinned_source(mock_http):
    second_arrived, html_calls, pdf_calls = asyncio.Event(), [], []

    async def respond(request):
        if "/html/" in str(request.url):
            html_calls.append(1)
            if len(html_calls) == 1:
                await second_arrived.wait()
                return httpx.Response(200, text=HTML)
            second_arrived.set()
            return httpx.Response(500)
        pdf_calls.append(1)
        return httpx.Response(200, text=PDF)

    mock_http(respond)
    first, second = await asyncio.gather(server.paper_content("1706.03762"), server.paper_content("1706.03762"))
    assert first == second == PDF
    assert server._content_source["1706.03762"] == "pdf"
    assert server._content_cache["1706.03762"][1] == PDF
    assert len(pdf_calls) == 1


@pytest.mark.asyncio
async def test_recently_read_paper_keeps_its_pin(mock_http, monkeypatch):
    monkeypatch.setattr(content, "CONTENT_SOURCE_SIZE", 2)
    mock_http(Upstream(httpx.Response(200, text=HTML)))
    await server.paper_content("1706.00001")
    await server.paper_content("1706.00002")
    await server.paper_content("1706.00001")
    await server.paper_content("1706.00003")
    assert list(server._content_source) == ["1706.00001", "1706.00003"]

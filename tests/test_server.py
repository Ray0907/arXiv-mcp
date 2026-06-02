"""Tests for arXiv MCP server — Feature 1: snake_case renaming."""
import inspect

import httpx
import pytest
from arxiv_mcp.server import (
    extract_paper_id,
    clean_text,
    parse_search_results,
)


def test_extract_paper_id_from_abs_url():
    assert extract_paper_id("https://arxiv.org/abs/2301.00001") == "2301.00001"


def test_extract_paper_id_from_pdf_url():
    assert extract_paper_id("https://arxiv.org/pdf/2301.00001") == "2301.00001"


def test_extract_paper_id_from_bare_id():
    assert extract_paper_id("2301.00001") == "2301.00001"


def test_extract_paper_id_invalid():
    assert extract_paper_id("not-an-id") is None


def test_clean_text_normalises_whitespace():
    assert clean_text("hello   world\nnewline") == "hello world newline"


def test_tools_registered():
    from arxiv_mcp.server import mcp
    import asyncio
    tools = asyncio.run(mcp.list_tools()) if asyncio.iscoroutinefunction(mcp.list_tools) else mcp.list_tools()
    names = {t.name for t in tools}
    expected = {"search", "search_advanced", "get_paper", "get_content", "get_recent", "list_categories"}
    assert expected.issubset(names), f"Missing tools: {expected - names}"


def test_search_is_async():
    from arxiv_mcp.server import search

    assert inspect.iscoroutinefunction(search)


def test_get_paper_is_async():
    from arxiv_mcp.server import get_paper

    assert inspect.iscoroutinefunction(get_paper)


@pytest.mark.asyncio
async def test_search_returns_error_on_http_failure(monkeypatch):
    from arxiv_mcp.server import search

    request = httpx.Request("GET", "https://arxiv.org/search/")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("Service Unavailable", request=request, response=response)

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            pass

        async def get(self, url):
            raise error

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await search("transformers")

    assert "error" in result
    assert "503" in result["error"]


@pytest.mark.asyncio
async def test_get_content_rejects_non_arxiv_url():
    from arxiv_mcp.server import get_content

    with pytest.raises(ValueError, match='must point to arxiv.org'):
        await get_content('https://evil.com/something')


@pytest.mark.asyncio
async def test_get_content_rejects_evil_url_with_arxiv_id_in_path():
    from arxiv_mcp.server import get_content

    with pytest.raises(ValueError, match='must point to arxiv.org'):
        await get_content('https://evil.com/abs/2301.00001')

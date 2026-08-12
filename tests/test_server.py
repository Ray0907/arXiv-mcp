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


def test_list_categories_precomputed():
    """Categories are pre-computed at module load, not inside the tool call."""
    from arxiv_mcp.models import Category
    from arxiv_mcp.server import _CATEGORIES_CACHE, list_categories
    import asyncio
    # Module-level constant should already be populated
    assert len(_CATEGORIES_CACHE) > 0
    assert all(isinstance(c, Category) for c in _CATEGORIES_CACHE)
    # Tool returns the same list
    result = asyncio.run(list_categories())
    assert result == _CATEGORIES_CACHE
    # Sorted by (group, code)
    codes_by_group: dict = {}
    for c in result:
        codes_by_group.setdefault(c.group, []).append(c.code)
    for g, codes in codes_by_group.items():
        assert codes == sorted(codes), f'Group {g} not sorted: {codes}'


@pytest.mark.asyncio
async def test_search_raises_on_http_failure(monkeypatch):
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

    with pytest.raises(ValueError, match="503"):
        await search("transformers")


@pytest.mark.asyncio
async def test_search_advanced_requires_a_field():
    from arxiv_mcp.server import search_advanced

    with pytest.raises(ValueError, match="At least one search field"):
        await search_advanced()


@pytest.mark.asyncio
async def test_tools_have_output_schema():
    from arxiv_mcp.server import mcp

    tools = {t.name: t for t in await mcp.list_tools()}
    for name in ("search", "search_advanced", "get_paper", "get_recent", "list_categories"):
        assert tools[name].output_schema, f"{name} missing output_schema"
    assert "papers" in tools["search"].output_schema["properties"]
    # Non-object return types are wrapped under a "result" key by the SDK
    assert list(tools["list_categories"].output_schema["properties"]) == ["result"]


@pytest.mark.asyncio
async def test_list_categories_structured_content_wrapped():
    from arxiv_mcp.server import mcp

    result = await mcp.call_tool("list_categories", {})
    assert set(result.structured_content) == {"result"}
    assert result.structured_content["result"][0]["code"]


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

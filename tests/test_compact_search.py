"""Compact projections must never poison the shared full-metadata cache."""

import inspect

import pytest

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed, atom_api, no_rate_limit  # noqa: F401


@pytest.fixture(autouse=True)
def paper_feed(atom_api):
    atom_api.body = _feed(_entry(summary="An abstract."), total=5)


SEARCHES = [
    (server.search, {"query": "test"}),
    (server.search_advanced, {"title": "test"}),
    (server.get_recent, {"category": "cs.AI"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,kwargs", SEARCHES)
@pytest.mark.parametrize("limit", [0, 8])
async def test_compact_abstracts_and_full_cache_are_independent(atom_api, tool, kwargs, limit):
    compact = await tool(**kwargs, abstract_max_chars=limit)
    assert compact.papers[0].abstract == "An abstract."[:limit]
    assert compact.model_dump()["papers"][0]["abstract"] == "An abstract."[:limit]
    full = await tool(**kwargs)
    assert full.papers[0].abstract == "An abstract."
    compact.papers[0].abstract = "mutated"
    again = await tool(**kwargs, abstract_max_chars=limit)
    assert again.papers[0].abstract == "An abstract."[:limit]
    assert len(atom_api.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,kwargs", SEARCHES)
async def test_negative_abstract_limit_fails_before_http(atom_api, tool, kwargs):
    with pytest.raises(ValueError, match="abstract_max_chars.*non-negative"):
        await tool(**kwargs, abstract_max_chars=-1)
    assert atom_api.requests == []


@pytest.mark.asyncio
async def test_compact_keeps_pagination_and_default_contract(atom_api):
    result = await server.search("test", page_size=1, abstract_max_chars=0)
    assert (result.total_results, result.has_more, result.next_page) == (5, True, 2)
    assert inspect.signature(server.search).parameters["page_size"].default == 25
    assert inspect.signature(server.search_advanced).parameters["page_size"].default == 25
    assert inspect.signature(server.get_recent).parameters["count"].default == 10
    paper = await server.get_paper("2401.00001")
    assert paper.abstract == "An abstract."


@pytest.mark.asyncio
async def test_compact_schema_and_mcp_output(atom_api):
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    for name in ("search", "search_advanced", "get_recent"):
        assert "abstract_max_chars" in tools[name].input_schema["properties"]
    result = await server.mcp.call_tool("search", {"query": "test", "abstract_max_chars": 0})
    assert not result.is_error
    assert result.structured_content["papers"][0]["abstract"] == ""
    assert "An abstract." not in str(result.content)

"""Regression for resource/reading state under python -m, without network access."""

import httpx
import pytest

import arxiv_mcp.content as content
import arxiv_mcp.server as server
from tests.test_entrypoint import execute_module


@pytest.mark.asyncio
async def test_runpy_resource_and_bounded_read_share_one_fetch(monkeypatch):
    namespace, started = execute_module(monkeypatch)
    calls = []

    async def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, text="# Methods\nSynthetic methods.\n")

    monkeypatch.setitem(namespace, "_get", get)
    monkeypatch.setattr(server, "_get", get)
    await namespace["read_paper_content"]("2401.00001")
    result = await namespace["read_paper"]("2401.00001", section="Methods")
    assert result == "# Methods\nSynthetic methods.\n"
    assert calls == [content._jina_url("2401.00001")]
    assert started == [server.mcp]
    assert namespace["_content_cache"] is server._content_cache
    assert namespace["_atom_cache"] is server._atom_cache
    assert namespace["_rate_lock"] is server._rate_lock

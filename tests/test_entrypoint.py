"""Module execution must use the same caches and throttle as extracted tools."""

import runpy
import sys
import warnings

import httpx
import pytest
from mcp.server import MCPServer

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed


def execute_module(monkeypatch):
    started = []
    monkeypatch.setattr(MCPServer, "run", lambda self, **kwargs: started.append(self))
    monkeypatch.setattr(sys, "argv", ["arxiv_mcp.server"])
    with warnings.catch_warnings():
        # The suite already imports the canonical module; real `python -m` does not.
        warnings.filterwarnings("ignore", message="'arxiv_mcp.server' found in sys.modules", category=RuntimeWarning)
        try:
            namespace = runpy.run_module("arxiv_mcp.server", run_name="__main__")
        except SystemExit as exc:
            assert exc.code in (None, 0)
            namespace = vars(server)
    return namespace["paper_content"].__globals__, started


@pytest.mark.asyncio
async def test_module_entrypoint_shares_batch_atom_cache_and_throttle(monkeypatch):
    namespace, started = execute_module(monkeypatch)
    calls = []

    async def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, text=_feed(_entry()))

    monkeypatch.setitem(namespace, "_get", get)
    monkeypatch.setattr(server, "_get", get)
    await namespace["_query_atom"]({"id_list": "2401.00001"}, page_size=1)
    result = await namespace["get_papers"](["2401.00001"])
    assert [p.id_arxiv for p in result.papers] == ["2401.00001"]
    assert calls == [server.URL_EXPORT]
    assert started == [server.mcp]
    assert namespace["_atom_cache"] is server._atom_cache
    assert namespace["_rate_lock"] is server._rate_lock
    assert namespace["_throttle"].__globals__ is server._throttle.__globals__

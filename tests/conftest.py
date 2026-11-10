"""Keep process-local response caches isolated between offline tests."""

import pytest

import arxiv_mcp.server as server


@pytest.fixture(autouse=True)
def clear_response_caches():
    names = ("_atom_cache", "_mention_cache", "_content_cache")
    for name in names:
        getattr(server, name, {}).clear()
    yield
    for name in names:
        getattr(server, name, {}).clear()

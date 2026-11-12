"""Keep process-local response caches isolated between offline tests."""

import pytest

import arxiv_mcp.content as content
import arxiv_mcp.server as server


@pytest.fixture(autouse=True)
def clear_response_caches():
    names = ("_atom_cache", "_mention_cache", "_content_cache", "_content_source")
    for name in names:
        getattr(server, name, {}).clear()
    yield
    for name in names:
        getattr(server, name, {}).clear()


@pytest.fixture(autouse=True)
def pdf_path_only(request, monkeypatch):
    """Existing tests exercise the PDF path; tests/test_html_first.py and test_content_source.py cover the HTML attempt."""
    if request.module.__name__.rsplit(".", 1)[-1] in {"test_html_first", "test_content_source"}:
        return

    async def no_html(_):
        raise ValueError("HTML disabled for PDF-path tests")

    monkeypatch.setattr(content, "_html_text", no_html)

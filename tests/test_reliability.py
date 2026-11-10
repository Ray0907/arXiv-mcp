"""Offline regression tests for safe, reliable paper retrieval."""

import httpx
import pytest

import arxiv_mcp.server as server


@pytest.mark.parametrize(
    ("value", "paper_id"),
    [
        ("1706.03762", "1706.03762"),
        (" arXiv:1706.03762v2 ", "1706.03762v2"),
        ("hep-th/9901001", "hep-th/9901001"),
        ("https://arxiv.org/abs/hep-th/9901001v1", "hep-th/9901001v1"),
        ("https://www.arxiv.org/pdf/1706.03762v2.pdf", "1706.03762v2"),
    ],
)
def test_jina_url_rebuilds_pdf_target(value, paper_id):
    assert server._jina_url(value) == f"https://r.jina.ai/https://arxiv.org/pdf/{paper_id}"


@pytest.mark.parametrize(
    "value",
    [
        "../../help",
        "x/../../../https://example.com",
        "https://arxiv.org/abs/../../help",
        "https://arxiv.org/abs/%2e%2e/%2e%2e/help",
        "https://arxiv.org/pdf/1706.03762%2f..%2f..%2fhelp",
        "https://arxiv.org/abs/1706.03762?redirect=https://example.com",
        "https://arxiv.org.evil.com/abs/1706.03762",
        "https://arxiv.org@evil.com/abs/1706.03762",
        "https://arxiv.org/list/cs/recent",
        "not-a-paper",
    ],
)
@pytest.mark.asyncio
async def test_invalid_content_input_never_opens_http(value, monkeypatch):
    def unexpected_client(**kwargs):
        pytest.fail("invalid content input reached HTTP")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    with pytest.raises(ValueError):
        await server.get_content(value)
    with pytest.raises(ValueError):
        await server.paper_content(value)

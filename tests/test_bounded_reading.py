"""Synthetic Markdown only; no live paper text is stored in tests."""

import re

import pytest

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed, atom_api, no_rate_limit  # noqa: F401


MARKDOWN = """Reader metadata
# Toy Paper
## Abstract
Synthetic abstract in the PDF.
## 1 Introduction
Intro only.
## 2 Methods
Methods body.
### 2.1 Details
Nested detail.
## 3 Results
Results only.
"""


@pytest.fixture
def cached_paper(monkeypatch):
    server._cache_put(server._content_cache, "2401.00001", MARKDOWN, 3600, 32)
    paper = server._parse_atom(_feed(_entry()))[0][0]

    async def metadata(_):
        return paper

    async def no_network(*args, **kwargs):
        pytest.fail("Cached reading must not fetch full text again")

    monkeypatch.setattr(server, "get_paper", metadata)
    monkeypatch.setattr(server, "_get", no_network)
    return paper


@pytest.mark.asyncio
async def test_read_default_is_outline_plus_api_abstract(cached_paper):
    result = await server.read_paper("2401.00001")
    assert "# Outline" in result
    assert "1 Introduction" in result
    assert "2.1 Details" in result
    assert "# Abstract\n" + cached_paper.abstract in result
    assert "Intro only." not in result
    assert "chunk:1" in result
    assert len(result) <= 12000


@pytest.mark.asyncio
@pytest.mark.parametrize("section", ["2 METHODS", "methods", "section:4"])
async def test_named_section_includes_children_but_not_next_peer(cached_paper, section):
    result = await server.read_paper("2401.00001", section=section)
    assert result.startswith("## 2 Methods")
    assert "Nested detail." in result
    assert "Results only." not in result
    assert "Intro only." not in result


@pytest.mark.asyncio
async def test_exact_heading_wins_over_partial_matches(cached_paper):
    text = "# Intro\nFirst.\n# Introduction\nSecond.\n"
    server._cache_put(server._content_cache, "2401.00001", text, 3600, 32)
    assert "First." in await server.read_paper("2401.00001", section="Intro")
    with pytest.raises(ValueError, match="Ambiguous"):
        await server.read_paper("2401.00001", section="Int")


@pytest.mark.asyncio
async def test_duplicate_headings_are_addressable_by_index(cached_paper):
    text = "# Same\nFirst.\n# Same\nSecond.\n"
    server._cache_put(server._content_cache, "2401.00001", text, 3600, 32)
    with pytest.raises(ValueError, match="Ambiguous"):
        await server.read_paper("2401.00001", section="Same")
    assert "Second." in await server.read_paper("2401.00001", section="section:2")


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "# Only a title\n"])
async def test_sparse_or_headingless_pdf_has_lossless_indexed_chunks(cached_paper, prefix):
    text = prefix + "Synthetic PDF text. αβγ\n" * 1500
    server._cache_put(server._content_cache, "2401.00001", text, 3600, 32)
    outline = await server.read_paper("2401.00001")
    assert "chunk:1" in outline
    chunks = []
    for i in range(1, (len(text) + 9999) // 10000 + 1):
        chunks.append(await server.read_paper("2401.00001", section=f"chunk:{i}"))
    assert "".join(chunks) == text
    assert all(len(chunk) <= 10000 for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("section", [None, "Long", "chunk:1"])
@pytest.mark.parametrize("limit", [256, 512, 12000])
async def test_character_cap_and_continuation_are_lossless(cached_paper, section, limit):
    text = "# Long\n" + "Toy text α. " * 1600
    cached_paper.abstract = "Synthetic summary. " * 900
    server._cache_put(server._content_cache, "2401.00001", text, 3600, 32)
    complete = await server.read_paper("2401.00001", section=section, max_chars=50000)
    offset, pieces = 0, []
    while True:
        result = await server.read_paper("2401.00001", section=section, max_chars=limit, offset=offset)
        assert len(result) <= limit
        if "[Truncated;" not in result:
            pieces.append(result)
            break
        body, marker = result.rsplit("\n\n[Truncated;", 1)
        pieces.append(body)
        next_offset = int(re.search(r"offset=(\d+)", marker).group(1))
        assert next_offset == offset + len(body)
        assert next_offset > offset
        offset = next_offset
    assert "".join(pieces) == complete


@pytest.mark.asyncio
@pytest.mark.parametrize("section", ["not a heading", "chunk:0", "chunk:99", "section:99"])
async def test_missing_section_is_explicit(cached_paper, section):
    with pytest.raises(ValueError, match="section|chunk"):
        await server.read_paper("2401.00001", section=section)


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"max_chars": 0}, {"max_chars": -1}, {"max_chars": 1}, {"max_chars": 255},
    {"offset": -1}, {"offset": 999999},
])
async def test_invalid_read_bounds(cached_paper, kwargs):
    with pytest.raises(ValueError):
        await server.read_paper("2401.00001", **kwargs)


@pytest.mark.asyncio
async def test_read_rejects_non_arxiv_url_without_fetch(cached_paper):
    with pytest.raises(ValueError, match="arxiv.org"):
        await server.read_paper("https://evil.example/abs/2401.00001")


@pytest.mark.asyncio
async def test_heading_preserves_literal_hashes(cached_paper):
    text = "# C#\nLanguage text.\n# Closing markers ###\nOther text.\n"
    server._cache_put(server._content_cache, "2401.00001", text, 3600, 32)
    result = await server.read_paper("2401.00001", section="C#")
    assert "Language text." in result
    assert "Other text." not in result
    assert "Other text." in await server.read_paper("2401.00001", section="Closing markers")


@pytest.mark.asyncio
async def test_setext_headings_and_fenced_code(cached_paper):
    text = "Title\n=====\n```markdown\n# Fake Heading\n```\nMethods\n-------\nReal text.\n"
    server._cache_put(server._content_cache, "2401.00001", text, 3600, 32)
    outline = await server.read_paper("2401.00001")
    assert "Fake Heading" not in outline
    result = await server.read_paper("2401.00001", section="Methods")
    assert "Real text." in result
    assert "Fake Heading" not in result


@pytest.mark.asyncio
async def test_read_reuses_resource_cache_and_aliases(atom_api):
    atom_api.body = MARKDOWN
    link = await server.get_content("2401.00001")
    await server.mcp.read_resource(link.uri)
    first = await server.read_paper("https://arxiv.org/pdf/2401.00001.pdf", section="Methods")
    second = await server.read_paper("arXiv:2401.00001", section="chunk:1")
    assert "Methods body." in first
    assert second == MARKDOWN
    assert len(atom_api.requests) == 1


@pytest.mark.asyncio
async def test_read_mcp_contract(cached_paper):
    result = await server.mcp.call_tool("read_paper", {"id_or_url": "2401.00001", "section": "Methods", "max_chars": 256})
    assert not result.is_error
    assert len(result.structured_content["result"]) <= 256
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert tools["read_paper"].input_schema["properties"]["max_chars"]["default"] == 12000

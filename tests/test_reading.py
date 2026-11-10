"""Offline metadata, citation and bounded-reading regressions (synthetic papers only)."""

import pytest

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed, atom_api  # noqa: F401


EXTRA_FIELDS = {"primary_category", "comment", "journal_ref", "doi", "version"}


def test_parse_optional_metadata():
    entry = _entry().replace(
        "</entry>",
        "<arxiv:comment> 12 pages\n, toy example </arxiv:comment>"
        "<arxiv:journal_ref>Example Journal 1 (2024)</arxiv:journal_ref>"
        "<arxiv:doi>10.0000/example</arxiv:doi></entry>",
    )
    paper = server._parse_atom(_feed(entry))[0][0]
    assert paper.primary_category == "cs.LG"
    assert paper.comment == "12 pages , toy example"
    assert paper.journal_ref == "Example Journal 1 (2024)"
    assert paper.doi == "10.0000/example"
    assert paper.version == 2
    assert paper.id_arxiv == "2401.00001"


def test_absent_optional_metadata_preserves_output():
    entry = _entry(abs_id="2401.00001").replace('<arxiv:primary_category term="cs.LG"/>', "")
    paper = server._parse_atom(_feed(entry))[0][0]
    assert all(getattr(paper, name) is None for name in EXTRA_FIELDS)
    assert not EXTRA_FIELDS.intersection(paper.model_dump())
    assert not EXTRA_FIELDS.intersection(paper.model_dump(mode="json"))
    assert set(paper.model_dump()) == {
        "id_arxiv", "title", "abstract", "authors", "categories", "url_abstract",
        "url_pdf", "date_published", "date_updated",
    }


@pytest.mark.asyncio
async def test_metadata_serializes_through_mcp(atom_api):
    atom_api.body = _feed(_entry())
    result = await server.mcp.call_tool("get_paper", {"id_or_url": "2401.00001"})
    assert result.structured_content["primary_category"] == "cs.LG"
    assert result.structured_content["version"] == 2
    assert "doi" not in result.structured_content

"""Offline metadata, citation and bounded-reading regressions (synthetic papers only)."""

import pytest

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed, atom_api, no_rate_limit  # noqa: F401


EXTRA_FIELDS = {"primary_category", "comment", "journal_ref", "doi", "version"}


@pytest.mark.asyncio
async def test_batch_lookup_reports_missing_and_keeps_request_order(atom_api):
    atom_api.body = _feed(_entry(abs_id="2401.00002v1"), _entry())
    result = await server.get_papers(["2401.00001", "2401.99999", "2401.00002"])
    assert [p.id_arxiv for p in result.papers] == ["2401.00001", "2401.00002"]
    assert result.missing_ids == ["2401.99999"]
    assert len(atom_api.requests) == 1
    assert atom_api.params() == {
        "id_list": "2401.00001,2401.99999,2401.00002", "start": "0", "max_results": "3",
    }


@pytest.mark.asyncio
async def test_batch_lookup_normalizes_aliases_and_preserves_versions(atom_api):
    atom_api.body = _feed(_entry(), _entry(abs_id="hep-th/9901001v4"))
    result = await server.get_papers([
        "https://arxiv.org/abs/2401.00001v2", "arXiv:2401.00001v2", "hep-th/9901001v1",
    ])
    assert atom_api.params()["id_list"] == "2401.00001v2,hep-th/9901001"
    assert [p.id_arxiv for p in result.papers] == ["2401.00001v2", "hep-th/9901001"]
    assert result.missing_ids == []


@pytest.mark.asyncio
async def test_batch_all_missing_is_not_an_error(atom_api):
    result = await server.get_papers(["2401.99999"])
    assert result.papers == []
    assert result.missing_ids == ["2401.99999"]


@pytest.mark.asyncio
async def test_batch_withdrawn_metadata_does_not_hide_missing_id(atom_api):
    atom_api.body = _feed(_entry().replace("</entry>", "<arxiv:comment>Withdrawn</arxiv:comment></entry>"))
    result = await server.get_papers(["2401.00001", "2401.99999"])
    assert result.papers[0].comment == "Withdrawn"
    assert result.missing_ids == ["2401.99999"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[], ["bad"], ["2401.00001", "bad"], ["2401.00001"] * 51])
async def test_batch_validates_before_http(atom_api, ids):
    with pytest.raises(ValueError):
        await server.get_papers(ids)
    assert atom_api.requests == []


@pytest.mark.asyncio
async def test_batch_maximum_and_mcp_output(atom_api):
    ids = [f"2401.{i:05}" for i in range(1, 51)]
    atom_api.body = _feed(*(_entry(abs_id=id_) for id_ in ids))
    result = await server.mcp.call_tool("get_papers", {"ids": ids})
    assert not result.is_error
    assert len(result.structured_content["papers"]) == 50
    assert result.structured_content["missing_ids"] == []
    assert atom_api.params()["max_results"] == "50"


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

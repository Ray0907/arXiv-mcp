import pytest
from arxiv_mcp.models import Paper, RecentPapers, SearchResult


def test_has_more_when_more_results():
	r = SearchResult(query="test", total_results=100, papers=[], page=1, page_size=25)
	assert r.has_more is True
	assert r.next_page == 2


def test_no_more_when_fewer_results():
	r = SearchResult(query="test", total_results=10, papers=[], page=1, page_size=25)
	assert r.has_more is False
	assert r.next_page is None


def test_boundary_exactly_full_page():
	r = SearchResult(query="test", total_results=50, papers=[], page=2, page_size=25)
	assert r.has_more is False
	assert r.next_page is None


def test_model_dump_includes_pagination():
	r = SearchResult(query="test", total_results=100, papers=[], page=1, page_size=25)
	d = r.model_dump()
	assert "has_more" in d
	assert "next_page" in d
	assert d["has_more"] is True
	assert d["next_page"] == 2


def test_recent_papers_model():
	p = Paper(
		id_arxiv="2301.00001",
		title="t",
		abstract="",
		url_abstract="https://arxiv.org/abs/2301.00001",
		url_pdf="https://arxiv.org/pdf/2301.00001.pdf",
	)
	r = RecentPapers(category="cs.AI", category_name="Artificial Intelligence", count=1, papers=[p])
	d = r.model_dump()
	assert d["count"] == 1
	assert d["papers"][0]["id_arxiv"] == "2301.00001"

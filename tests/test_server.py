"""Tests for arXiv MCP server — Feature 1: snake_case renaming."""
import asyncio
import inspect
import time

import httpx
import pytest
from arxiv_mcp.server import (
    extract_paper_id,
    clean_text,
)


def test_extract_paper_id_from_abs_url():
    assert extract_paper_id("https://arxiv.org/abs/2301.00001") == "2301.00001"


def test_extract_paper_id_from_pdf_url():
    assert extract_paper_id("https://arxiv.org/pdf/2301.00001") == "2301.00001"


def test_extract_paper_id_from_bare_id():
    assert extract_paper_id("2301.00001") == "2301.00001"


def test_extract_paper_id_invalid():
    assert extract_paper_id("not-an-id") is None


@pytest.mark.parametrize(
	"raw, expected",
	[
		("2301.00001v2", "2301.00001v2"),
		("https://arxiv.org/abs/2301.00001v3", "2301.00001v3"),
		("https://arxiv.org/pdf/2301.00001v1.pdf", "2301.00001v1"),
		("hep-th/9901001", "hep-th/9901001"),
		("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"),
		("math.GT/0309136", "math.GT/0309136"),
		("arXiv:2301.00001", "2301.00001"),
	],
)
def test_extract_paper_id_versions_and_legacy(raw, expected):
	assert extract_paper_id(raw) == expected


def test_clean_text_normalises_whitespace():
    assert clean_text("hello   world\nnewline") == "hello world newline"


def test_tools_registered():
    from arxiv_mcp.server import mcp
    import asyncio
    tools = asyncio.run(mcp.list_tools()) if asyncio.iscoroutinefunction(mcp.list_tools) else mcp.list_tools()
    names = {t.name for t in tools}
    expected = {"search", "search_advanced", "get_paper", "get_content", "get_recent", "list_categories"}
    assert expected.issubset(names), f"Missing tools: {expected - names}"


def test_search_is_async():
    from arxiv_mcp.server import search

    assert inspect.iscoroutinefunction(search)


def test_get_paper_is_async():
    from arxiv_mcp.server import get_paper

    assert inspect.iscoroutinefunction(get_paper)


def test_list_categories_precomputed():
    """Categories are pre-computed at module load, not inside the tool call."""
    from arxiv_mcp.models import Category
    from arxiv_mcp.server import _CATEGORIES_CACHE, list_categories
    import asyncio
    # Module-level constant should already be populated
    assert len(_CATEGORIES_CACHE) > 0
    assert all(isinstance(c, Category) for c in _CATEGORIES_CACHE)
    # Tool returns the same list
    result = asyncio.run(list_categories())
    assert result == _CATEGORIES_CACHE
    # Sorted by (group, code)
    codes_by_group: dict = {}
    for c in result:
        codes_by_group.setdefault(c.group, []).append(c.code)
    for g, codes in codes_by_group.items():
        assert codes == sorted(codes), f'Group {g} not sorted: {codes}'


@pytest.mark.asyncio
async def test_search_raises_on_http_failure(monkeypatch):
    from arxiv_mcp.server import search

    request = httpx.Request("GET", "https://arxiv.org/search/")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("Service Unavailable", request=request, response=response)

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            pass

        async def get(self, url, **kwargs):
            raise error

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    with pytest.raises(ValueError, match="503"):
        await search("transformers")


@pytest.mark.asyncio
async def test_search_advanced_requires_a_field():
    from arxiv_mcp.server import search_advanced

    with pytest.raises(ValueError, match="At least one search field"):
        await search_advanced()


@pytest.mark.asyncio
async def test_tools_have_output_schema():
    from arxiv_mcp.server import mcp

    tools = {t.name: t for t in await mcp.list_tools()}
    for name in ("search", "search_advanced", "get_paper", "get_recent", "list_categories"):
        assert tools[name].output_schema, f"{name} missing output_schema"
    assert "papers" in tools["search"].output_schema["properties"]
    # Non-object return types are wrapped under a "result" key by the SDK
    assert list(tools["list_categories"].output_schema["properties"]) == ["result"]


@pytest.mark.asyncio
async def test_list_categories_structured_content_wrapped():
    from arxiv_mcp.server import mcp

    result = await mcp.call_tool("list_categories", {})
    assert set(result.structured_content) == {"result"}
    assert result.structured_content["result"][0]["code"]


@pytest.mark.parametrize(
    ("id_or_url", "resource_uri"),
    [
        ("2301.00001", "arxiv://content/2301.00001"),
        (
            "https://arxiv.org/abs/2301.00001",
            "arxiv://content/https%3A%2F%2Farxiv.org%2Fabs%2F2301.00001",
        ),
    ],
)
@pytest.mark.asyncio
async def test_get_content_returns_jina_resource_link(monkeypatch, id_or_url, resource_uri):
    from mcp.types import ResourceLink
    from arxiv_mcp.server import mcp

    jina_url = "https://r.jina.ai/https://arxiv.org/pdf/2301.00001"
    requests = []

    class UnreadableStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("validation request body was read")
            yield b""  # pragma: no cover

    def respond(request):
        requests.append((request.method, str(request.url)))
        if len(requests) == 1:
            return httpx.Response(200, stream=UnreadableStream())
        return httpx.Response(200, text="full paper text")

    async_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=transport))

    result = await mcp.call_tool("get_content", {"id_or_url": id_or_url})

    assert requests == [("GET", jina_url)]
    assert result.structured_content is None
    assert len(result.content) == 1
    assert isinstance(result.content[0], ResourceLink)
    assert str(result.content[0].uri) == resource_uri
    assert result.content[0].mime_type == "text/markdown"

    resource = await mcp.read_resource(result.content[0].uri)
    assert resource[0].content == "full paper text"
    assert requests == [("GET", jina_url), ("GET", jina_url)]


@pytest.mark.asyncio
async def test_get_content_stream_raises_on_http_failure(monkeypatch):
    from arxiv_mcp.server import get_content

    async_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(404, request=request))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=transport))

    with pytest.raises(ValueError, match="404"):
        await get_content("2301.00001")


@pytest.mark.asyncio
async def test_get_content_rejects_non_arxiv_url():
    from arxiv_mcp.server import get_content

    with pytest.raises(ValueError, match='must point to arxiv.org'):
        await get_content('https://evil.com/something')


@pytest.mark.asyncio
async def test_get_content_rejects_evil_url_with_arxiv_id_in_path():
    from arxiv_mcp.server import get_content

    with pytest.raises(ValueError, match='must point to arxiv.org'):
        await get_content('https://evil.com/abs/2301.00001')


NS_FEED = (
	'xmlns="http://www.w3.org/2005/Atom" '
	'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" '
	'xmlns:arxiv="http://arxiv.org/schemas/atom"'
)


def _entry(
	abs_id="2401.00001v2",
	title="Sparse Lattice  Routing\n for Toy Models",
	summary="  We study lattices.\n  They route things.  ",
	authors=("Alice Example", "Bob Sample"),
	cats=("cs.LG", "stat.ML"),
	published="2024-01-02T03:04:05Z",
	updated="2024-02-03T04:05:06Z",
):
	author_xml = "".join(f"<author><name>{a}</name></author>" for a in authors)
	cat_xml = "".join(f'<category term="{c}" scheme="http://arxiv.org/schemas/atom"/>' for c in cats)
	return (
		f"<entry><id>http://arxiv.org/abs/{abs_id}</id>"
		f"<updated>{updated}</updated><published>{published}</published>"
		f"<title>{title}</title><summary>{summary}</summary>{author_xml}"
		f'<link href="http://arxiv.org/abs/{abs_id}" rel="alternate" type="text/html"/>'
		f'<arxiv:primary_category term="{cats[0]}"/>{cat_xml}</entry>'
	)


def _feed(*entries, total=None):
	total = len(entries) if total is None else total
	return (
		f'<?xml version="1.0" encoding="UTF-8"?><feed {NS_FEED}>'
		f"<opensearch:totalResults>{total}</opensearch:totalResults>"
		f"<opensearch:startIndex>0</opensearch:startIndex>"
		f"{''.join(entries)}</feed>"
	)


ERROR_FEED = _feed(
	"<entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_zzz</id>"
	"<title>Error</title><summary>incorrect id format for zzz</summary></entry>"
)


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
	import arxiv_mcp.server as server

	monkeypatch.setattr(server, "ARXIV_MIN_INTERVAL", 0.0)


@pytest.fixture
def atom_api(monkeypatch):
	"""Serve canned Atom bodies from a mock transport and record every request."""

	class Api:
		requests: list[httpx.Request] = []
		status = 200
		body = _feed()

		def params(self, index=-1):
			return dict(self.requests[index].url.params)

	api = Api()
	api.requests = []
	api.stamps = []

	def respond(request):
		api.requests.append(request)
		api.stamps.append(time.monotonic())
		return httpx.Response(api.status, text=api.body, request=request)

	async_client = httpx.AsyncClient
	transport = httpx.MockTransport(respond)
	monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: async_client(transport=transport, **kw))
	return api


def test_parse_atom_multi_entry():
	from arxiv_mcp.server import _parse_atom

	xml = _feed(
		_entry(),
		_entry(abs_id="hep-th/9901001v1", title="Legacy Strings", authors=("Carol Invented",), cats=("hep-th",)),
		total=2,
	)
	papers, total = _parse_atom(xml)

	assert total == 2
	assert [p.id_arxiv for p in papers] == ["2401.00001", "hep-th/9901001"]
	first = papers[0]
	assert first.title == "Sparse Lattice Routing for Toy Models"
	assert first.abstract == "We study lattices. They route things."
	assert first.authors == ["Alice Example", "Bob Sample"]
	assert first.categories == ["cs.LG", "stat.ML"]
	assert first.url_abstract == "https://arxiv.org/abs/2401.00001"
	assert first.url_pdf == "https://arxiv.org/pdf/2401.00001.pdf"
	assert first.date_published == "2024-01-02T03:04:05Z"
	assert papers[1].url_abstract == "https://arxiv.org/abs/hep-th/9901001"


def test_parse_atom_total_independent_of_page_size():
	from arxiv_mcp.server import _parse_atom

	papers, total = _parse_atom(_feed(_entry(), total=1234))
	assert len(papers) == 1
	assert total == 1234


def test_parse_atom_populates_date_updated():
	from arxiv_mcp.server import _parse_atom

	papers, _ = _parse_atom(_feed(_entry()))
	assert papers[0].date_updated == "2024-02-03T04:05:06Z"


def test_parse_atom_empty_feed():
	from arxiv_mcp.server import _parse_atom

	assert _parse_atom(_feed(total=0)) == ([], 0)


def test_parse_atom_error_entry_raises():
	from arxiv_mcp.server import _parse_atom

	with pytest.raises(ValueError, match="incorrect id format"):
		_parse_atom(ERROR_FEED)


def test_parse_atom_paper_titled_error_is_not_an_api_error():
	from arxiv_mcp.server import _parse_atom

	papers, _ = _parse_atom(_feed(_entry(title="Error")))
	assert papers[0].title == "Error"


def test_parse_atom_rejects_non_xml():
	from arxiv_mcp.server import _parse_atom

	with pytest.raises(ValueError, match="unparseable"):
		_parse_atom("<html>rate limited")


@pytest.mark.asyncio
async def test_search_builds_query_and_paging(atom_api):
	from arxiv_mcp.server import search

	atom_api.body = _feed(_entry(), total=90)
	result = await search("graph transformers", category="cs.LG", author="Alice Example", sort_by="date_desc", page=2, page_size=25)

	params = atom_api.params()
	assert params["search_query"] == 'all:graph AND all:transformers AND au:"Alice Example" AND cat:cs.LG'
	assert params["start"] == "25"
	assert params["max_results"] == "25"
	assert (params["sortBy"], params["sortOrder"]) == ("submittedDate", "descending")
	assert "export.arxiv.org/api/query" in str(atom_api.requests[0].url)
	assert result.total_results == 90
	assert result.has_more is True
	assert result.page == 2


@pytest.mark.asyncio
async def test_search_uses_phrase_when_query_has_stopwords(atom_api):
	from arxiv_mcp.server import search

	# The API drops stopwords from ANDed words, so "is" would make the query match nothing.
	await search("attention is all you need")
	assert atom_api.params()["search_query"] == 'all:"attention is all you need"'


@pytest.mark.asyncio
async def test_search_passes_field_syntax_through(atom_api):
	from arxiv_mcp.server import search

	await search("ti:attention AND au:Vaswani")
	assert atom_api.params()["search_query"] == "ti:attention AND au:Vaswani"


@pytest.mark.asyncio
async def test_get_paper_strips_version_for_legacy_ids(atom_api):
	from arxiv_mcp.server import get_paper

	# The API answers HTTP 500 / no entry for a versioned legacy ID, but works for the bare one.
	atom_api.body = _feed(_entry())
	await get_paper("hep-th/9901001v1")
	assert atom_api.params()["id_list"] == "hep-th/9901001"


@pytest.mark.asyncio
async def test_get_paper_keeps_version_for_new_style_ids(atom_api):
	from arxiv_mcp.server import get_paper

	atom_api.body = _feed(_entry())
	await get_paper("2301.00001v2")
	assert atom_api.params()["id_list"] == "2301.00001v2"


@pytest.mark.asyncio
async def test_search_sends_descriptive_user_agent(atom_api):
	from arxiv_mcp.server import search

	await search("anything")
	assert "arxiv-mcp" in atom_api.requests[0].headers["user-agent"]


@pytest.mark.asyncio
async def test_search_rejects_unknown_sort(atom_api):
	from arxiv_mcp.server import search

	with pytest.raises(ValueError, match="sort_by"):
		await search("x", sort_by="bogus")
	assert atom_api.requests == []


@pytest.mark.asyncio
async def test_search_advanced_builds_field_terms_and_date_range(atom_api):
	from arxiv_mcp.server import search_advanced

	await search_advanced(
		title="diffusion models",
		abstract="denoising",
		author="Doe",
		category="cs.CV",
		date_from="2024-01-05",
		date_to="2024-03-31",
		sort_by="date_asc",
	)

	params = atom_api.params()
	assert params["search_query"] == (
		'ti:diffusion AND ti:models AND abs:denoising AND au:Doe AND cat:cs.CV'
		" AND submittedDate:[202401050000 TO 202403312359]"
	)
	assert (params["sortBy"], params["sortOrder"]) == ("submittedDate", "ascending")


@pytest.mark.asyncio
async def test_search_advanced_open_ended_date_and_id(atom_api):
	from arxiv_mcp.server import search_advanced

	await search_advanced(id_arxiv="arXiv:2401.00001v2", date_from="2024-01-01")

	params = atom_api.params()
	assert params["id_list"] == "2401.00001v2"
	assert params["search_query"].startswith("submittedDate:[202401010000 TO ")


@pytest.mark.asyncio
async def test_search_advanced_rejects_bad_date(atom_api):
	from arxiv_mcp.server import search_advanced

	with pytest.raises(ValueError, match="YYYY-MM-DD"):
		await search_advanced(title="x", date_from="01/02/2024")


@pytest.mark.asyncio
async def test_search_http_429_raises_value_error(atom_api):
	from arxiv_mcp.server import search

	atom_api.status = 429
	with pytest.raises(ValueError, match="429"):
		await search("transformers")


@pytest.mark.asyncio
async def test_api_error_entry_surfaces_as_value_error(atom_api):
	from arxiv_mcp.server import search

	atom_api.body = ERROR_FEED
	with pytest.raises(ValueError, match="incorrect id format"):
		await search("ti:")


@pytest.mark.asyncio
async def test_get_paper_returns_full_record(atom_api):
	from arxiv_mcp.server import get_paper

	atom_api.body = _feed(_entry())
	paper = await get_paper("https://arxiv.org/abs/2401.00001")

	assert atom_api.params()["id_list"] == "2401.00001"
	assert paper.title.startswith("Sparse Lattice")
	assert paper.date_updated == "2024-02-03T04:05:06Z"


@pytest.mark.asyncio
async def test_get_paper_keeps_requested_version(atom_api):
	from arxiv_mcp.server import get_paper

	atom_api.body = _feed(_entry(abs_id="2401.00001v1"))
	paper = await get_paper("2401.00001v1")
	assert paper.id_arxiv == "2401.00001v1"


@pytest.mark.asyncio
async def test_get_paper_raises_when_id_list_matches_nothing(atom_api):
	from arxiv_mcp.server import get_paper

	atom_api.body = _feed(total=0)
	with pytest.raises(ValueError, match="No arXiv paper"):
		await get_paper("2401.99999")


@pytest.mark.asyncio
async def test_get_paper_rejects_unparseable_id(atom_api):
	from arxiv_mcp.server import get_paper

	with pytest.raises(ValueError, match="Could not extract"):
		await get_paper("not-an-id")
	assert atom_api.requests == []


@pytest.mark.asyncio
async def test_get_recent_uses_category_query_with_abstracts(atom_api):
	from arxiv_mcp.server import get_recent

	atom_api.body = _feed(_entry(), _entry(abs_id="2401.00002v1"), total=500)
	result = await get_recent("cs.AI", count=2)

	params = atom_api.params()
	assert params["search_query"] == "cat:cs.AI"
	assert (params["sortBy"], params["sortOrder"]) == ("submittedDate", "descending")
	assert params["max_results"] == "2"
	assert params["start"] == "0"
	assert result.category_name == "Artificial Intelligence"
	assert result.count == 2
	assert result.papers[0].abstract == "We study lattices. They route things."


@pytest.mark.asyncio
async def test_get_recent_caps_count_at_50(atom_api):
	from arxiv_mcp.server import get_recent

	await get_recent("cs.AI", count=500)
	assert atom_api.params()["max_results"] == "50"


def test_sort_options_use_api_values():
	from arxiv_mcp.models import SORT_OPTIONS

	assert "relevance" in SORT_OPTIONS
	for sort_by, sort_order in SORT_OPTIONS.values():
		assert sort_by in {"relevance", "submittedDate", "lastUpdatedDate"}
		assert sort_order in {"ascending", "descending"}


@pytest.mark.asyncio
async def test_requests_are_spaced_by_min_interval(atom_api, monkeypatch):
	import arxiv_mcp.server as server

	monkeypatch.setattr(server, "ARXIV_MIN_INTERVAL", 0.2)

	await asyncio.gather(server.search("one"), server.search("two"), server.search("three"))

	stamps = atom_api.stamps
	gaps = [b - a for a, b in zip(stamps, stamps[1:])]
	assert len(stamps) == 3
	assert all(gap >= 0.18 for gap in gaps), gaps

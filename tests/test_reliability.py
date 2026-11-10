"""Offline regression tests for safe, reliable paper retrieval."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest

import arxiv_mcp.server as server


@pytest.fixture(autouse=True)
def reset_throttle(monkeypatch):
    monkeypatch.setattr(server, "ARXIV_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(server, "_last_request", 0.0)
    monkeypatch.setattr(server, "_rate_lock", asyncio.Lock())


@pytest.fixture
def mock_http(monkeypatch):
    client_class = httpx.AsyncClient

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kwargs: client_class(transport=transport, **kwargs)
        )

    return install


async def fetch(endpoint):
    if endpoint == "atom":
        return await server._query_atom({"search_query": "all:mock"})
    return await server.paper_content("1706.03762")


EMPTY_FEED = '<feed xmlns="http://www.w3.org/2005/Atom" />'


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


@pytest.mark.parametrize("endpoint", ["atom", "content"])
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
@pytest.mark.asyncio
async def test_transport_failures_are_readable(endpoint, error, mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        raise error("mock failure", request=request)

    mock_http(respond)
    with pytest.raises(ValueError, match=r"(arXiv|Jina Reader).*Try again later"):
        await fetch(endpoint)
    assert len(calls) == 1


@pytest.mark.parametrize("endpoint", ["atom", "content"])
@pytest.mark.parametrize("status", [429, 503, 406])
@pytest.mark.asyncio
async def test_retryable_status_retries_one_get(endpoint, status, mock_http, monkeypatch):
    calls, sleeps = [], []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, headers={"Retry-After": "2"})
        return httpx.Response(200, text=EMPTY_FEED if endpoint == "atom" else "# Mock paper")

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    mock_http(respond)
    await fetch(endpoint)
    assert [request.method for request in calls] == ["GET", "GET"]
    assert sleeps == [2]


@pytest.mark.parametrize("status, attempts", [(404, 1), (400, 1), (500, 1), (429, 2), (503, 2), (406, 2)])
@pytest.mark.asyncio
async def test_http_failures_have_bounded_attempts(status, attempts, mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "0"})

    mock_http(respond)
    with pytest.raises(ValueError, match=f"Jina Reader.*HTTP {status}"):
        await fetch("content")
    assert len(calls) == attempts


@pytest.mark.parametrize("retry_after, expected", [("1", [1, 2]), ("5", [5])])
@pytest.mark.asyncio
async def test_retry_wait_and_throttle_overlap(retry_after, expected, mock_http, monkeypatch):
    now, starts, sleeps = [100.0], [], []
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(server, "ARXIV_MIN_INTERVAL", 3.0)

    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    def respond(request):
        starts.append(now[0])
        return httpx.Response(
            429 if len(starts) == 1 else 200,
            headers={"Retry-After": retry_after}, text=EMPTY_FEED,
        )

    monkeypatch.setattr(asyncio, "sleep", sleep)
    mock_http(respond)
    await fetch("atom")
    assert sleeps == expected
    assert starts[1] - starts[0] == max(3, int(retry_after))


@pytest.mark.parametrize("header", ["99999999", "date"])
@pytest.mark.asyncio
async def test_retry_after_is_capped_and_accepts_http_dates(header, mock_http, monkeypatch):
    calls, sleeps = [], []
    if header == "date":
        header = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)

    def respond(request):
        calls.append(request)
        return httpx.Response(
            503 if len(calls) == 1 else 200,
            headers={"Retry-After": header}, text="# Mock paper",
        )

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    mock_http(respond)
    await fetch("content")
    assert sleeps == [10]


@pytest.mark.parametrize("phase", ["http", "body", "throttle", "retry"])
@pytest.mark.asyncio
async def test_total_deadline_covers_all_waits(phase, mock_http, monkeypatch):
    monkeypatch.setattr(server, "TIMEOUT", 0.02)
    calls = []

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b"never reached"

    async def respond(request):
        calls.append(request)
        if phase == "http":
            await asyncio.Event().wait()
        if phase == "body":
            return httpx.Response(200, stream=SlowBody())
        return httpx.Response(429, headers={"Retry-After": "10"})

    if phase == "throttle":
        monkeypatch.setattr(server, "ARXIV_MIN_INTERVAL", 3.0)
        monkeypatch.setattr(server, "_last_request", server.time.monotonic())
    mock_http(respond)
    with pytest.raises(ValueError, match=r"arXiv.*time limit"):
        await asyncio.wait_for(fetch("atom"), timeout=0.3)
    assert len(calls) == (0 if phase == "throttle" else 1)


@pytest.mark.asyncio
async def test_atom_cache_uses_sorted_complete_request_params(mock_http):
    calls = []

    def respond(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, text=EMPTY_FEED)

    mock_http(respond)
    params = {"search_query": "all:mock", "sortBy": "relevance", "sortOrder": "descending"}
    await server._query_atom(params)
    await server._query_atom(dict(reversed(list(params.items()))))
    assert len(calls) == 1
    await server._query_atom(params, page=2)
    await server._query_atom(params, page_size=10)
    await server._query_atom({**params, "sortOrder": "ascending"})
    await server._query_atom({"id_list": "1706.03762v1"})
    await server._query_atom({"id_list": "1706.03762v2"})
    assert len(calls) == 6
    # Clamped pages and sizes describe the same outgoing request.
    await server._query_atom(params, page=0, page_size=100)
    await server._query_atom(params, page=1, page_size=50)
    assert len(calls) == 7


@pytest.mark.parametrize(
    "sort_by, order, fresh_at_61",
    [("relevance", "descending", True), ("submittedDate", "descending", False),
     ("lastUpdatedDate", "descending", False), ("submittedDate", "ascending", True)],
)
@pytest.mark.asyncio
async def test_atom_cache_ttl_is_shorter_for_recent_sorts(sort_by, order, fresh_at_61, mock_http, monkeypatch):
    now, calls = [100.0], []
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=EMPTY_FEED)

    mock_http(respond)
    params = {"search_query": "all:mock", "sortBy": sort_by, "sortOrder": order}
    await server._query_atom(params)
    now[0] += 61
    await server._query_atom(params)
    assert len(calls) == (1 if fresh_at_61 else 2)
    now[0] += 301
    await server._query_atom(params)
    assert len(calls) == (2 if fresh_at_61 else 3)


@pytest.mark.asyncio
async def test_atom_cache_is_bounded_and_evicts_oldest(mock_http, monkeypatch):
    monkeypatch.setattr(server, "ATOM_CACHE_SIZE", 2, raising=False)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=EMPTY_FEED)

    mock_http(respond)
    for query in ["one", "two", "three"]:
        await server._query_atom({"search_query": query})
    assert len(server._atom_cache) == 2
    await server._query_atom({"search_query": "one"})
    assert len(calls) == 4
    assert len(server._atom_cache) == 2


@pytest.mark.asyncio
async def test_atom_cache_does_not_share_mutable_results(mock_http):
    from tests.test_server import _entry, _feed

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=_feed(_entry()))

    mock_http(respond)
    params = {"search_query": "all:mock"}
    first = await server._query_atom(params)
    title = first.papers[0].title
    first.papers[0].title = "changed"
    first.papers.clear()
    second = await server._query_atom(params)
    assert second.papers[0].title == title
    second.papers[0].title = "changed again"
    assert (await server._query_atom(params)).papers[0].title == title
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["http", "xml", "transport"])
@pytest.mark.asyncio
async def test_atom_failures_are_not_cached(failure, mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            if failure == "transport":
                raise httpx.ConnectError("mock failure", request=request)
            return httpx.Response(404 if failure == "http" else 200, text="not XML")
        return httpx.Response(200, text=EMPTY_FEED)

    mock_http(respond)
    with pytest.raises(ValueError):
        await fetch("atom")
    await fetch("atom")
    await fetch("atom")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_mention_cache_is_bounded_normalized_and_expires(monkeypatch):
    now, calls = [100.0], []
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(server, "MENTION_CACHE_SIZE", 2, raising=False)
    monkeypatch.setattr(server, "MENTION_DEBOUNCE", 0.0)
    monkeypatch.setattr(server, "_mention_blocked_until", 0.0)

    async def search(query):
        calls.append(query)
        return server.SearchResult(query=query, total_results=0, papers=[])

    async def mention(query):
        return await server.search_mentions(server.OpenAIMentionSearchParams(query=query), None)

    monkeypatch.setattr(server, "search", search)
    await mention("Alpha")
    await mention(" alpha ")
    assert calls == ["Alpha"]
    await mention("Beta")
    await mention("Gamma")
    assert len(server._mention_cache) == 2
    await mention("Alpha")
    assert calls == ["Alpha", "Beta", "Gamma", "Alpha"]
    now[0] += 301
    await mention("Alpha")
    assert len(calls) == 5
    assert len(server._mention_cache) == 2


@pytest.mark.asyncio
async def test_get_content_is_local_only(monkeypatch):
    def unexpected_client(**kwargs):
        pytest.fail("get_content made an HTTP request")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    link = await server.get_content("hep-th/9901001v1")
    assert str(link.uri) == "arxiv://content/hep-th%2F9901001v1"
    assert link.mime_type == "text/markdown"


@pytest.mark.parametrize("paper_id", ["1706.03762", "hep-th/9901001v1"])
@pytest.mark.asyncio
async def test_resource_reads_fetch_once_and_keep_resource_link_flow(paper_id, mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="# Mock full paper\n\n## Mock section\nBody.")

    mock_http(respond)
    result = await server.mcp.call_tool("get_content", {"id_or_url": paper_id})
    assert calls == []
    assert result.structured_content is None
    link = result.content[0]
    first = await server.mcp.read_resource(link.uri)
    second = await server.mcp.read_resource(link.uri)
    assert first[0].content == second[0].content == "# Mock full paper\n\n## Mock section\nBody."
    assert len(calls) == 1
    assert str(calls[0].url) == f"https://r.jina.ai/https://arxiv.org/pdf/{paper_id}"


@pytest.mark.asyncio
async def test_content_cache_normalizes_aliases_but_keeps_versions_distinct(mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=f"# Mock paper {len(calls)}")

    mock_http(respond)
    first = await server.paper_content("1706.03762")
    assert await server.paper_content("https://www.arxiv.org/abs/1706.03762") == first
    assert await server.paper_content("arXiv:1706.03762") == first
    v1 = await server.paper_content("1706.03762v1")
    assert await server.paper_content("https://arxiv.org/pdf/1706.03762v1.pdf") == v1
    v2 = await server.paper_content("1706.03762v2")
    assert len({first, v1, v2}) == 3
    assert len(calls) == 3
    assert set(server._content_cache) == {"1706.03762", "1706.03762v1", "1706.03762v2"}


@pytest.mark.asyncio
async def test_content_cache_has_longer_ttl_for_versioned_ids(mock_http, monkeypatch):
    now, calls = [100.0], []
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=f"# Mock revision {len(calls)}")

    mock_http(respond)
    latest = await server.paper_content("1706.03762")
    pinned = await server.paper_content("1706.03762v1")
    now[0] += 3601
    assert await server.paper_content("1706.03762") != latest
    assert await server.paper_content("1706.03762v1") == pinned
    assert len(calls) == 3
    now[0] += 86401
    assert await server.paper_content("1706.03762v1") != pinned
    await server.paper_content("1706.03762")
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_content_cache_is_bounded(mock_http, monkeypatch):
    monkeypatch.setattr(server, "CONTENT_CACHE_SIZE", 2, raising=False)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="# Mock paper")

    mock_http(respond)
    for paper_id in ["1706.03762", "1706.03762v1", "1706.03762v2"]:
        await server.paper_content(paper_id)
    assert len(server._content_cache) == 2
    await server.paper_content("1706.03762")
    assert len(calls) == 4
    assert len(server._content_cache) == 2


@pytest.mark.parametrize("failure", ["http", "transport"])
@pytest.mark.asyncio
async def test_content_failures_are_not_cached(failure, mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            if failure == "transport":
                raise httpx.ReadTimeout("mock failure", request=request)
            return httpx.Response(404)
        return httpx.Response(200, text="# Mock recovered paper")

    mock_http(respond)
    with pytest.raises(ValueError):
        await server.paper_content("1706.03762")
    assert await server.paper_content("1706.03762") == "# Mock recovered paper"
    assert await server.paper_content("1706.03762") == "# Mock recovered paper"
    assert len(calls) == 2

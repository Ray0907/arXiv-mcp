"""Synthetic Semantic Scholar edges; never record live papers or credentials."""

import asyncio
import traceback
from types import SimpleNamespace

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import arxiv_mcp.server as server
from tests.test_reliability import mock_http  # noqa: F401


@pytest.mark.asyncio
async def test_graph_tools_available():
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert {"get_references", "get_citations"} <= names


@pytest.fixture
def graph(monkeypatch):
    from arxiv_mcp import graph

    graph._cache.clear()
    monkeypatch.setattr(graph, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(graph, "_last_request", 0.0)
    monkeypatch.setattr(graph, "_rate_lock", asyncio.Lock())
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    yield graph
    graph._cache.clear()


def edge(relation="references", arxiv="2401.00002"):
    return {"citedPaper" if relation == "references" else "citingPaper": {
        "paperId": "synthetic-id", "title": "Synthetic Neighbor", "year": 2024,
        "authors": [{"name": "Alice Example"}], "externalIds": {"ArXiv": arxiv},
    }}


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", ["references", "citations"])
async def test_graph_compact_output_and_shared_transport(graph, mock_http, monkeypatch, relation):
    calls, shared_calls = [], []
    original = server._get

    async def shared(*args, **kwargs):
        shared_calls.append(args[0])
        return await original(*args, **kwargs)

    async def no_arxiv_slot():
        pytest.fail("Semantic Scholar consumed the arXiv throttle")

    monkeypatch.setattr(server, "_get", shared)
    monkeypatch.setattr(server, "_throttle", no_arxiv_slot)
    monkeypatch.setattr(server, "_last_request", 123.0)

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"offset": 0, "next": 2, "data": [edge(relation), edge(relation, None)]})

    mock_http(respond)
    result = await getattr(server, f"get_{relation}")("https://arxiv.org/abs/1706.03762v2", limit=2)
    assert result.id_arxiv == "1706.03762"
    assert result.has_more is True
    assert result.papers[0].model_dump() == {
        "title": "Synthetic Neighbor", "id_arxiv": "2401.00002", "year": 2024, "authors": ["Alice Example"],
    }
    assert result.papers[1].id_arxiv is None
    assert len(calls) == len(shared_calls) == 1
    assert str(calls[0].url).startswith(f"{graph.URL_GRAPH}/paper/ARXIV:1706.03762/{relation}?")
    assert dict(calls[0].url.params) == {"fields": "title,externalIds,year,authors", "limit": "2"}
    assert "x-api-key" not in calls[0].headers
    assert server._last_request == 123.0


@pytest.mark.asyncio
async def test_graph_cache_aliases_isolation_expiry_and_size(graph, mock_http, monkeypatch):
    calls = []
    now = [100.0]
    monkeypatch.setattr(server, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(graph, "CACHE_SIZE", 2)

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [edge(request.url.path.rsplit("/", 1)[1])]})

    mock_http(respond)
    result = await server.get_references("1706.03762v1", limit=2)
    result.papers[0].authors.append("mutated")
    again = await server.get_references("arXiv:1706.03762", limit=2)
    assert again.papers[0].authors == ["Alice Example"]
    assert len(calls) == 1
    now[0] += graph.CACHE_TTL + 1
    await server.get_references("1706.03762", limit=2)
    assert len(calls) == 2
    await server.get_references("1706.03762", limit=3)
    await server.get_citations("1706.03762", limit=2)
    assert len(calls) == 4
    assert len(graph._cache) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", ["references", "citations"])
@pytest.mark.parametrize("limit", [0, -1, 51, 1.5, True])
async def test_graph_limits_validate_before_http(graph, mock_http, relation, limit):
    mock_http(lambda request: pytest.fail("invalid limit reached HTTP"))
    with pytest.raises(ValueError, match="limit.*1.*50"):
        await getattr(server, f"get_{relation}")("1706.03762", limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("paper_id", ["bad", "../../help", "https://evil.example/abs/1706.03762"])
async def test_graph_ids_validate_before_http(graph, mock_http, paper_id):
    mock_http(lambda request: pytest.fail("invalid ID reached HTTP"))
    with pytest.raises(ValueError, match="arXiv ID"):
        await server.get_references(paper_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,attempts,message", [
    (404, 1, "not found in Semantic Scholar"), (429, 2, "Semantic Scholar.*429.*rate limit"),
    (500, 1, "Semantic Scholar.*500"), (503, 2, "Semantic Scholar.*503"),
])
async def test_graph_http_errors_are_readable_bounded_and_not_cached(graph, mock_http, status, attempts, message):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "0"}, text="untrusted upstream error")

    mock_http(respond)
    with pytest.raises(ValueError, match=message):
        await asyncio.wait_for(server.get_references("1706.03762"), timeout=0.3)
    assert len(calls) == attempts
    assert not graph._cache


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
async def test_graph_transport_errors_do_not_leak_key(graph, mock_http, monkeypatch, caplog, error):
    secret = "synthetic-not-a-real-key"
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", secret)

    def respond(request):
        assert request.headers["x-api-key"] == secret
        assert secret not in str(request.url)
        raise error(f"sensitive upstream message {secret}", request=request)

    mock_http(respond)
    with pytest.raises(ValueError, match="Semantic Scholar.*Try again later") as caught:
        await server.get_references("1706.03762")
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert secret not in caplog.text
    assert not graph._cache


@pytest.mark.asyncio
async def test_graph_success_via_mcp_keeps_compact_contract(graph, mock_http):
    mock_http(lambda request: httpx.Response(200, json={"data": [edge()]}))
    result = await server.mcp.call_tool("get_references", {"id_or_url": "1706.03762", "limit": 1})
    assert not result.is_error
    assert result.structured_content == {
        "id_arxiv": "1706.03762", "has_more": False,
        "papers": [{"title": "Synthetic Neighbor", "id_arxiv": "2401.00002", "year": 2024, "authors": ["Alice Example"]}],
    }
    assert "abstract" not in str(result.content)


@pytest.mark.asyncio
async def test_graph_api_key_never_follows_cross_origin_redirect(graph, mock_http, monkeypatch):
    calls = []
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "synthetic-key")

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/collect"})

    mock_http(respond)
    with pytest.raises(ValueError, match="Semantic Scholar.*302"):
        await server.get_references("1706.03762")
    assert len(calls) == 1
    assert calls[0].url.host == "api.semanticscholar.org"


@pytest.mark.asyncio
async def test_graph_empty_null_edges_legacy_id_and_response_cap(graph, mock_http):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"citedPaper": None}, edge(), edge()]})

    mock_http(respond)
    result = await server.get_references("hep-th/9901001v2", limit=2)
    assert "/ARXIV:hep-th/9901001/references" in str(calls[0].url)
    assert result.id_arxiv == "hep-th/9901001"
    assert len(result.papers) == 1
    assert result.has_more is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], {}, {"data": None}, {"data": [{}]}, {"data": [{"citedPaper": {"title": None}}]}])
async def test_graph_malformed_responses_are_readable(graph, mock_http, payload):
    mock_http(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="Semantic Scholar.*invalid.*response"):
        await server.get_references("1706.03762")
    assert not graph._cache


@pytest.mark.asyncio
async def test_graph_empty_response_is_not_missing_paper(graph, mock_http):
    mock_http(lambda request: httpx.Response(200, json={"data": []}))
    result = await server.get_citations("1706.03762")
    assert result.papers == []
    assert result.has_more is False


@pytest.mark.asyncio
async def test_graph_tools_registered_and_missing_paper_error(graph, mock_http):
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    for name in ("get_references", "get_citations"):
        assert tools[name].annotations.read_only_hint
        assert tools[name].output_schema
    mock_http(lambda request: httpx.Response(404))
    with pytest.raises(ToolError, match="not found in Semantic Scholar"):
        await server.mcp.call_tool("get_references", {"id_or_url": "1706.03762"})


@pytest.mark.asyncio
async def test_graph_throttle_spaces_retries_and_calls_without_arxiv_slot(graph, mock_http, monkeypatch):
    now, starts = [100.0], []
    monkeypatch.setattr(graph, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(graph, "MIN_INTERVAL", 1.0)
    monkeypatch.setattr(server, "_last_request", 77.0)

    async def sleep(delay):
        now[0] += delay

    def respond(request):
        starts.append(now[0])
        return httpx.Response(503 if len(starts) == 1 else 200, headers={"Retry-After": "0"}, json={"data": []})

    monkeypatch.setattr(asyncio, "sleep", sleep)
    mock_http(respond)
    await server.get_references("1706.03762")
    await server.get_citations("1706.03762")
    assert starts == [100.0, 101.0, 102.0]
    assert server._last_request == 77.0


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["http", "body", "throttle", "retry"])
async def test_graph_deadline_covers_all_waits(graph, mock_http, monkeypatch, phase):
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
        monkeypatch.setattr(graph, "MIN_INTERVAL", 3.0)
        monkeypatch.setattr(graph, "_last_request", graph.time.monotonic())
    mock_http(respond)
    with pytest.raises(ValueError, match="Semantic Scholar.*time limit"):
        await asyncio.wait_for(server.get_references("1706.03762"), timeout=0.3)
    assert len(calls) == (0 if phase == "throttle" else 1)
    assert not graph._cache


@pytest.mark.asyncio
async def test_graph_bad_json_and_http_errors_never_echo_key(graph, mock_http, monkeypatch, caplog):
    secret = "synthetic-never-real-key"
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", secret)
    mock_http(lambda request: httpx.Response(401, text=secret))
    with pytest.raises(ValueError, match="Semantic Scholar.*401") as caught:
        await server.get_references("1706.03762")
    assert secret not in "".join(traceback.format_exception(caught.value))
    mock_http(lambda request: httpx.Response(200, text=secret))
    with pytest.raises(ValueError, match="Semantic Scholar.*invalid.*response") as caught:
        await server.get_references("1706.03762")
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert secret not in caplog.text

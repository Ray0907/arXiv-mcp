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

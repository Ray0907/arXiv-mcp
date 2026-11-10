"""Stateless recent-paper windows use inclusive UTC calendar dates."""

from datetime import datetime, timezone

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed, atom_api, no_rate_limit  # noqa: F401


@pytest.fixture
def utc_today(monkeypatch):
    class UTCDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls(2024, 3, 1, 0, 0, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(server, "datetime", UTCDateTime)


@pytest.mark.asyncio
@pytest.mark.parametrize("since", ["2024-02-29", "2024-03-01"])
async def test_since_reuses_advanced_date_query_with_inclusive_utc_bounds(atom_api, utc_today, since):
    atom_api.body = _feed(_entry(published=f"{since}T00:00:00Z"), total=1)
    recent = await server.get_recent("cs.LG", since=since, abstract_max_chars=0)
    assert atom_api.params() == {
        "search_query": f"cat:cs.LG AND submittedDate:[{since.replace('-', '')}0000 TO 202403012359]",
        "sortBy": "submittedDate", "sortOrder": "descending", "start": "0", "max_results": "10",
    }
    assert recent.count == 1
    assert recent.papers[0].abstract == ""
    assert recent.total_results == 1
    assert recent.has_more is False
    advanced = await server.search_advanced(
        category="cs.LG", date_from=since, date_to="2024-03-01", sort_by="date_desc", page_size=10,
    )
    assert len(atom_api.requests) == 1
    assert advanced.papers[0].abstract == "We study lattices. They route things."


@pytest.mark.asyncio
@pytest.mark.parametrize("since", [
    "", "yesterday", "3", "2024-2-29", "2024-02-30", "2023-02-29", "2024-03-01T00:00:00Z",
    "20240301", " 2024-02-29", "2024-03-01 ", "2024-03-02", "9999-12-31", 3, True,
])
async def test_since_rejects_malformed_or_future_dates_before_http(atom_api, utc_today, since):
    with pytest.raises(ValueError, match="since.*(YYYY-MM-DD|future)"):
        await server.get_recent(since=since)
    assert atom_api.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("requested,effective,total,more", [(2, 2, 5, True), (100, 50, 51, True), (0, 1, 1, False)])
async def test_since_count_is_bounded_and_discloses_truncation(atom_api, utc_today, requested, effective, total, more):
    atom_api.body = _feed(*[_entry(abs_id=f"2401.{i:05d}") for i in range(effective)], total=total)
    result = await server.get_recent(count=requested, since="2024-02-29")
    assert atom_api.params()["max_results"] == str(effective)
    assert result.count == effective
    assert result.total_results == total
    assert result.has_more is more
    assert result.model_dump()["has_more"] is more


@pytest.mark.asyncio
async def test_since_empty_window_and_legacy_query(atom_api, utc_today):
    result = await server.get_recent(since="2024-03-01")
    assert (result.count, result.total_results, result.has_more) == (0, 0, False)
    await server.get_recent()
    assert atom_api.params()["search_query"] == "cat:cs.AI"


@pytest.mark.asyncio
async def test_since_mcp_schema_and_validation(atom_api, utc_today):
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert "since" in tools["get_recent"].input_schema["properties"]
    with pytest.raises(ToolError, match="since.*future"):
        await server.mcp.call_tool("get_recent", {"since": "2024-03-02"})
    assert atom_api.requests == []

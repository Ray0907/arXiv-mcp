"""Exercise the Skills extension at the MCP request boundary."""

import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import anyio
import pytest
from mcp import ClientSession, types
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from pydantic import TypeAdapter

from arxiv_mcp.server import mcp

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src/arxiv_mcp/skill/arxiv/SKILL.md"
URI = "skill://arxiv/SKILL.md"
EXTENSION = "io.modelcontextprotocol/skills"
TOOLS = {
    "search_mentions", "search", "search_advanced", "get_paper", "get_papers",
    "export_bibtex", "read_paper", "get_content", "list_categories", "get_recent",
    "get_references", "get_citations",
}


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def session():
    server = mcp._lowlevel_server
    async with create_client_server_memory_streams() as (client, streams):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(server.run, *streams, server.create_initialization_options(), True)
            async with ClientSession(*client) as session:
                yield session
            tasks.cancel_scope.cancel()


async def request(session, method, **params):
    return await session.send_request(
        types.Request[dict, str](method=method, params=params), TypeAdapter(dict)
    )


@pytest.fixture
async def modern(session):
    discovery = await session.discover()
    assert session.protocol_version == "2026-07-28"
    return session, discovery


async def test_skills_capabilities(modern):
    _, discovery = modern
    assert discovery.capabilities.resources is not None
    assert discovery.capabilities.extensions[EXTENSION] == {}


async def test_skills_list_manifest(modern):
    session, _ = modern
    result = await request(session, "skills/list")
    assert result["resultType"] == "complete"
    assert type(result["ttlMs"]) is int and result["ttlMs"] >= 0
    assert result["cacheScope"] == "public"
    assert "nextCursor" not in result
    (skill,) = result["skills"]
    assert skill["uri"] == URI

    data = SKILL.read_bytes()
    opening, frontmatter, body = data.decode("utf-8").split("---\n", 2)
    assert opening == ""
    assert len(body.strip().splitlines()) < 60
    parsed = json.loads(frontmatter)
    assert parsed["name"] == SKILL.parent.name == "arxiv"
    assert isinstance(parsed["description"], str) and parsed["description"]
    assert skill["frontmatter"] == parsed
    assert skill["resources"] == [
        {"uri": URI, "digest": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data)}
    ]


async def test_skills_list_unknown_cursor(modern):
    session, _ = modern
    with pytest.raises(MCPError) as exc:
        await request(session, "skills/list", cursor="unknown")
    assert exc.value.code == -32602


async def test_skills_get_hit(modern):
    session, _ = modern
    listed = await request(session, "skills/list")
    result = await request(session, "skills/get", uri=URI)
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == listed["ttlMs"]
    assert result["cacheScope"] == listed["cacheScope"]
    assert result["skill"] == listed["skills"][0]


async def test_skills_get_unknown_uri(modern):
    session, _ = modern
    with pytest.raises(MCPError) as exc:
        await request(session, "skills/get", uri="skill://missing/SKILL.md")
    assert exc.value.code == -32602


async def test_read_skill_resource(modern):
    session, _ = modern
    (resource,) = (await session.read_resource(URI)).contents
    assert str(resource.uri) == URI
    assert resource.mime_type == "text/markdown"
    assert resource.text == SKILL.read_bytes().decode("utf-8")


async def test_skills_do_not_change_tools(modern):
    session, _ = modern
    assert {tool.name for tool in (await session.list_tools()).tools} == TOOLS


async def test_legacy_skills_methods_not_found_and_tools_still_work(session):
    init = await session.initialize()
    assert init.protocol_version == "2025-11-25"
    for method, params in (
        ("skills/list", {}), ("skills/list", {"cursor": 1}),
        ("skills/get", {"uri": URI}), ("skills/get", {}),
    ):
        with pytest.raises(MCPError) as exc:
            await request(session, method, **params)
        assert exc.value.code == -32601
    assert {tool.name for tool in (await session.list_tools()).tools} == TOOLS
    result = await session.call_tool("list_categories", {})
    assert not result.is_error
    assert result.structured_content["result"]


def test_wheel_contains_skill(tmp_path):
    subprocess.run(["uv", "build", "--out-dir", str(tmp_path)], cwd=ROOT, check=True)
    (wheel,) = tmp_path.glob("*.whl")
    with ZipFile(wheel) as archive:
        archive.printdir()
        assert archive.read("arxiv_mcp/skill/arxiv/SKILL.md") == SKILL.read_bytes()

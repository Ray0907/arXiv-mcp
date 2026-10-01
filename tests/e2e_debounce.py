"""E2E: a burst of per-keystroke mention queries must hit arXiv once (debounce).

Passes even if arXiv rate-limits us: it counts the server's outgoing requests,
not the results. Run: uv run python tests/e2e_debounce.py
"""
import asyncio, tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PREFIXES = ["fla", "flas", "flash", "flash ", "flash a", "flash at"]


async def main():
    params = StdioServerParameters(command="uv", args=["run", "arxiv-mcp"], cwd="/private/tmp/arXiv-mcp")
    with tempfile.TemporaryFile("w+") as errlog:
        async with stdio_client(params, errlog=errlog) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                name = next(t.name for t in tools.tools if t.meta and "openai/extensions" in t.meta)
                await asyncio.gather(*(s.call_tool(name, {"query": q}) for q in PREFIXES))
                # second burst right away: 429 cooldown or cache must keep it off arXiv
                await asyncio.gather(*(s.call_tool(name, {"query": q + "x"}) for q in PREFIXES))
        errlog.seek(0)
        hits = [l for l in errlog.read().splitlines() if "arxiv.org/search" in l]
    print(f"arXiv requests for {2 * len(PREFIXES)} keystroke calls: {len(hits)}")
    assert len(hits) <= 2, hits  # one per burst at most
    print("OK")


asyncio.run(main())

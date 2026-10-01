import asyncio, json, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "arxiv-mcp"], cwd="/private/tmp/arXiv-mcp")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("extensions:", getattr(init.capabilities, "extensions", None))
            tools = await s.list_tools()
            for t in tools.tools:
                print("tool:", t.name, t.meta or "")
            m = [t for t in tools.tools if t.meta and "openai/extensions" in t.meta][0]
            res = await s.call_tool(m.name, {"query": "attention is all you need"})
            sc = getattr(res,"structured_content",None) or getattr(res,"structuredContent",None) or {"raw": str(res)[:600]}
            print(json.dumps(sc, indent=1)[:900])
            assert sc["items"], "no mention items"
            short = await s.call_tool(m.name, {"query": "ab"})
            sc_short = getattr(short, "structured_content", None) or getattr(short, "structuredContent", None)
            assert sc_short["items"] == [], "short query must not search"
            t = time.perf_counter()
            again = await s.call_tool(m.name, {"query": " Attention Is All You Need "})
            dt = time.perf_counter() - t
            sc_again = getattr(again, "structured_content", None) or getattr(again, "structuredContent", None)
            assert sc_again == sc, "cached result must match (case/space-insensitive)"
            assert dt < 0.2, f"second call should hit cache, took {dt:.2f}s"
            print(f"short-query empty OK; cache hit {dt*1000:.0f}ms")
            print("OK")

asyncio.run(main())

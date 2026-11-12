import asyncio, json, re, time
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "arxiv-mcp"], cwd=str(Path(__file__).resolve().parent.parent))
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
            outline = await s.call_tool("read_paper", {"id_or_url": "1706.03762", "max_chars": 4000})
            text = outline.content[0].text
            assert "Scaled Dot-Product Attention" in text, "outline should come from arXiv HTML headings"
            print("HTML outline OK:", text.count("- section:"), "sections")
            # A deep page of date-sorted results is a paper Jina has most likely never cached.
            cold = await s.call_tool("search", {"query": "learning", "sort_by": "date_desc", "page": 60, "page_size": 3})
            cold_ids = [p["id_arxiv"] for p in cold.structured_content["papers"]]
            numbered = 0
            for paper_id in cold_ids:
                text = (await s.call_tool("read_paper", {"id_or_url": paper_id, "max_chars": 6000})).content[0].text
                has_subsections = bool(re.search(r"- section:\d+: \d+\.\d+ ", text))
                numbered += has_subsections
                print("cold", paper_id, "numbered subsections in outline:", has_subsections)
            assert numbered >= 2, "first read of cold papers should give HTML outlines with numbered subsections"
            print("OK")

asyncio.run(main())

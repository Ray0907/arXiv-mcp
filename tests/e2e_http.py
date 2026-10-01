"""Real Streamable HTTP check: uv run python tests/e2e_http.py."""

import asyncio
import socket
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check(server, host, port):
    for _ in range(100):
        assert server.returncode is None, f"HTTP server exited: {server.returncode}"
        try:
            _, writer = await asyncio.open_connection(host, port)
        except OSError:
            await asyncio.sleep(0.1)
        else:
            writer.close()
            await writer.wait_closed()
            break
    else:
        raise AssertionError("HTTP server did not listen within 10 seconds")

    async with streamable_http_client(f"http://{host}:{port}/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "arXiv-server", init.server_info
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"search", "search_mentions"} <= names, names
            mention_tool = next(tool for tool in tools.tools if tool.name == "search_mentions")
            assert "mentions/search" in mention_tool.meta["openai/extensions"], mention_tool
            print("tools:", ", ".join(sorted(names)))
            for name, key in (("search", "papers"), ("search_mentions", "items")):
                result = await session.call_tool(name, {"query": "attention is all you need"})
                assert not result.is_error, result
                assert result.structured_content, result
                assert result.structured_content[key], f"{name} returned no {key}"
                print(f"{name}: {len(result.structured_content[key])} {key}")
    print("HTTP /mcp OK")


async def main():
    host = "127.0.0.1"
    with socket.socket() as listener:
        listener.bind((host, 0))
        port = listener.getsockname()[1]
    server = await asyncio.create_subprocess_exec(
        "uv", "run", "arxiv-mcp", "--http", "--host", host, "--port", str(port),
        cwd=Path(__file__).resolve().parents[1],
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(check(server, host, port), timeout=90)
    finally:
        if server.returncode is None:
            server.terminate()
            try:
                await asyncio.wait_for(server.wait(), timeout=10)
            except asyncio.TimeoutError:
                server.kill()
                await server.wait()


if __name__ == "__main__":
    asyncio.run(main())

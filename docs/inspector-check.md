# MCP Inspector check and ChatGPT connection

## Official references

Read the saved official pages before making changes and checked the live packaging,
connection, tunnel, and Agent Plugins schema pages:

- [Build plugins](https://learn.chatgpt.com/plugins/build/plugins)
- [Build an MCP server](https://learn.chatgpt.com/plugins/build/mcp-server)
- [Connect and test](https://learn.chatgpt.com/plugins/deploy/connect-chatgpt)
- [Secure MCP Tunnel](https://learn.chatgpt.com/api/docs/guides/secure-mcp-tunnels)
- [Submit plugins](https://learn.chatgpt.com/plugins/deploy/submission)
- [Portable manifest schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)
- [Portable MCP schema](https://agent-plugins.org/schemas/1.0.0/mcp.schema.json)

## Inspector CLI: actual stdio check

Run from `/path/to/arXiv-mcp`. Both commands below exited **0**:

```sh
npx --yes @modelcontextprotocol/inspector --cli uv run arxiv-mcp --method tools/list
npx --yes @modelcontextprotocol/inspector --cli uv run arxiv-mcp --method tools/call \
  --tool-name search --tool-arg 'query=attention is all you need'
```

Selected actual `tools/list` output (schemas omitted for readability):

```json
{
  "tools": [
    {
      "name": "search_mentions",
      "_meta": {
        "openai/extensions": {
          "mentions/search": {}
        },
        "ui": {
          "visibility": ["app"]
        }
      }
    },
    {"name": "search"},
    {"name": "search_advanced"},
    {"name": "get_paper"},
    {"name": "get_content"},
    {"name": "list_categories"},
    {"name": "get_recent"}
  ]
}
```

Actual search HTTP log and selected structured output (paper bodies omitted):

```text
HTTP Request: GET https://export.arxiv.org/api/query?search_query=all%3A%22attention+is+all+you+need%22&sortBy=relevance&sortOrder=descending&start=0&max_results=25 "HTTP/1.1 200 OK"
```

```json
{
  "structuredContent": {
    "query": "all:\"attention is all you need\"",
    "total_results": 47,
    "page": 1,
    "page_size": 25,
    "has_more": true,
    "next_page": 2
  }
}
```

The actual `structuredContent.papers` contained **25 papers**; `isError` was
`false`. `query` echoes the API query: a query containing a stopword is sent as a
phrase, because the API drops stopwords from ANDed words. The first paper was
`2604.21816`, "Tool Attention Is All You Need: Dynamic Tool Gating and Lazy Schema
Loading", with `url_abstract` `https://arxiv.org/abs/2604.21816`.

The same call with `--tool-arg page_size=1` also exited **0** and returned 1 paper
(`max_results=1`); the API accepts any page size up to the tool's cap of 50. Results
depend on live arXiv data. `uv` also printed its existing
`tool.uv.dev-dependencies` deprecation warning.

## Connect in ChatGPT developer mode (user-run, not verified here)

ChatGPT cannot directly launch a local stdio process from the web. Use a Secure
MCP Tunnel for private development, or expose the HTTP transport through HTTPS.
Developer mode and tunnel availability depend on account/workspace permissions.

### Recommended: Secure MCP Tunnel with the current stdio server

1. Sign in to the target ChatGPT workspace. If required, ask its administrator
   for developer-mode access.
2. Open **Settings → Security and login → Developer mode** and enable it.
3. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels).
   Create a tunnel and associate it with the target ChatGPT workspace and
   Platform organization. Creating/editing requires Tunnels **Read + Manage**;
   using it requires **Read + Use**. Copy its `tunnel_id`.
4. Download `tunnel-client` from those settings or the
   [official latest release](https://github.com/openai/tunnel-client/releases/latest).
   On the machine running this repo, configure and run it using the official
   stdio profile pattern (replace the tunnel ID and securely provide your runtime
   key; do not commit credentials):

   ```sh
   cd /path/to/arXiv-mcp
   uv sync
   tunnel-client help quickstart
   export CONTROL_PLANE_API_KEY="<your runtime API key>"
   tunnel-client init \
     --sample sample_mcp_stdio_local \
     --profile arxiv-stdio \
     --tunnel-id '<your tunnel_id>' \
     --mcp-command "uv --directory /path/to/arXiv-mcp run arxiv-mcp"
   tunnel-client doctor --profile arxiv-stdio --explain
   tunnel-client run --profile arxiv-stdio
   ```

   Keep the client running. Its host needs outbound HTTPS to OpenAI and access
   to `uv` and this repo; no public inbound listener is needed.
5. Open [ChatGPT Plugins](https://chatgpt.com/plugins), select the **plus** button,
   and enter name `arXiv` and description `Search and retrieve arXiv papers`.
6. Under **Connection**, choose **Tunnel**, select your tunnel or paste its ID,
   and create the connection. Review the discovered tools, including `search`
   and `search_mentions` with its OpenAI mentions metadata.
7. Start a new conversation and enable the connection from the tools menu.
   Ask `Search arXiv for attention is all you need`, inspect the selected tool
   and result, and try the composer `@` mention/typeahead. Follow up with a
   returned paper ID. Try an unrelated request that should not use arXiv.
8. After metadata changes, restart the server/tunnel as necessary, open the
   connection, select **Refresh**, and test again in a new conversation.

### Alternative: HTTP through a public HTTPS endpoint

1. Start the local server:

   ```sh
   uv run arxiv-mcp --http --host 127.0.0.1 --port 8000
   ```

2. Put a trusted HTTPS forwarding service or reverse proxy in front of
   `http://127.0.0.1:8000/mcp`. ChatGPT cannot reach your `localhost`; use the full
   externally reachable `https://<your-host>/mcp` URL. Preserve streaming,
   session headers, and the MCP HTTP methods. Do not expose it broadly without
   appropriate access controls. The SDK's loopback DNS-rebinding protection is
   retained; public proxy Host/Origin settings require deliberate deployment
   configuration, not disabling that protection.
3. In developer mode, create the connection at **ChatGPT Plugins → plus**,
   entering the HTTPS URL under **Connection** instead of choosing Tunnel.
   This server has no user-account OAuth flow. Review metadata and run the same
   prompts and refresh steps above.

Neither ChatGPT account wiring, tunnel operation, HTTPS deployment, plugin
installation, nor public submission was performed here. A Secure MCP Tunnel
is for private/developer testing, not public submission; public plugins need a
stable public HTTPS MCP endpoint and the submission/review requirements.

## Packaging notes

The official portable layout uses root `plugin.json` and **`mcp.json`** with
Agent Plugins schemas. `.mcp.json` belongs to the documented compatibility
layout; it is also supplied here as requested, but is not the portable
configuration's discovery filename. Both launch the existing stdio command.
Skills are optional, so no empty or speculative `skills/` directory is needed.

## Transport and regression verification

The CLI keeps stdio as the default. `--http` uses the installed MCP SDK's
built-in Streamable HTTP server at `/mcp`; `--host` defaults to `127.0.0.1`
and `--port` defaults to `8000`. No transport dependency was added.

```sh
uv run python tests/e2e_http.py
uv run python tests/e2e_stdio.py
uv run pytest -q
```

Actual HTTP E2E output (server access logs omitted), exit **0**:

```text
tools: get_content, get_paper, get_recent, list_categories, search, search_advanced, search_mentions
search: 25 papers
search_mentions: 10 items
HTTP /mcp OK
```

The E2E starts a real subprocess with `--http --host 127.0.0.1 --port <free-port>`,
initializes a real SDK Streamable HTTP client at `/mcp`, checks tool metadata,
calls `search` and `search_mentions` against live arXiv, and terminates the
server in cleanup. Before implementation it exited **1** with
`AssertionError: HTTP server exited: 0`, proving the old stdio-only entry point
could not serve HTTP. An initial over-strict capability assertion also failed:
`initialize` reports `extensions=None` on both transports in this environment.
The E2E verifies the actual `search_mentions` tool metadata and successful
calls instead; the existing OpenAI extension implementation was not changed.
ChatGPT's composer behavior still requires account-side testing.

Actual existing stdio E2E output ends in `OK`, exit **0**. Actual pytest output,
exit **0**:

```text
.......................                                                  [100%]
23 passed, 1 warning in 0.32s
```

The pytest warning is the existing `asyncio.iscoroutinefunction` deprecation in
`tests/test_server.py`. The official Draft 2020-12 JSON schemas accepted
`plugin.json` and `mcp.json`; `.mcp.json` has identical server wiring. The
`uv.lock` checksum was unchanged during the HTTP implementation and checks.
No unit tests were added and no commit was made.

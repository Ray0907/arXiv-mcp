# Impl Plan: arXiv-mcp SDK v2 升級 + Structured Output

已於乾淨 venv 實測 `mcp==2.0.0`，原「待確認」項目全數有結論，直接寫入各 Phase。

## Phase 1 — SDK 升級（已實測確認）
- `pyproject.toml`: `mcp>=1.5.0` → `mcp>=2.0.0`（requires-python `>=3.10`，與本專案相容，無衝突）
- `pyproject.toml`: `version = "0.2.0"` → `0.4.0`（目前已落後 README changelog v0.3.0，此次一併補齊）
- `src/arxiv_mcp/server.py`:
  - `from mcp.server.fastmcp import FastMCP` → `from mcp.server import MCPServer`（v2 已移除 `mcp.server.fastmcp` 模組，實測 import 失敗）
  - `mcp = FastMCP("arXiv-server")` → `mcp = MCPServer("arXiv-server")`
  - `@mcp.tool(annotations={...})` 簽名不變，實測可用；`mcp.run(transport="stdio")` 簽名不變
- `uv sync` 更新 lock
- `uv run pytest` 抓其餘相容性 break

## Phase 2 — Structured Output
錯誤處理定案：**一律 raise exception**，不用 union 回傳。實測結果：`-> Model | dict` 雖可產生 anyOf outputSchema，但 error dict 會以 `is_error=False` 回傳（client 看起來是成功）；raise 則由 SDK 轉成標準 `ToolError` / MCP error。故 spike 取消。

- `server.py` 各 tool 回傳型別改為直接回 model，移除手動 `.model_dump()`：
  - `search()` → `-> SearchResult`
  - `search_advanced()` → `-> SearchResult`
  - `get_paper()` → `-> Paper`
  - `get_content()` 維持 `-> str`
  - `get_recent()`：新增 `RecentPapers` model 到 `models.py`，改 `-> RecentPapers`
  - `list_categories()`：改用既有 `Category` model，`-> list[Category]`。注意：非 object 回傳型別會被 SDK 包成 `{"result": [...]}`（spec 要求 structuredContent 為 object），屬 breaking shape change，README 需註明
- error path 全面改 raise（共三處，不只 `_http_error_response`）：
  - `_http_error_response`（server.py:27）：改為 raise，訊息保留原文案；刪除此 helper 或改為建 exception 的 helper
  - `search_advanced` 的 `{"error": "At least one search field is required"}`（server.py:240）：改 raise `ValueError`
  - `get_content` 的 error 字串回傳（server.py:377）：改 raise，與整體 raise 政策一致
- README「HTTP errors return dict」政策移除，改為「errors raise standard MCP errors」

## Phase 3 — 測試更新
- `tests/test_server.py`：
  - `test_search_returns_error_on_http_failure` 目前斷言 `result["error"]`，改為斷言 raise（`pytest.raises`）
  - 其餘依賴裸 dict 形狀的斷言（如 `result["papers"]`）改為 model instance 斷言
- `tests/test_models.py`：補 `RecentPapers` 測試
- 新增 outputSchema 測試：注意 v2 Python 端屬性是 snake_case `tool.output_schema`（實測 `outputSchema` 會 AttributeError），wire JSON 才是 `outputSchema`；測試斷言用 `output_schema`
- 新增 `list_categories` 測試：確認 structured content 為 `{"result": [...]}` 包裝形狀

## Phase 4 — 文件
- README Changelog 加 v0.4.0：
  - SDK v2 升級（`FastMCP` → `MCPServer`）
  - structured output breaking change：各 tool 回傳含 outputSchema；`list_categories` 包成 `{"result": [...]}`
  - error 行為 breaking change：dict/字串 error 改為標準 MCP error（raise）
- 確認 Claude Desktop / Claude Code config 範例在 v2 下啟動指令沒變（`run(transport="stdio")` 簽名已實測不變，預期無需改）

## 已解決的原風險項
- ~~FastMCP 改名細節僅來自網頁搜尋~~ → 已實測：`mcp.server.fastmcp` 移除，改用 `mcp.server.MCPServer`
- ~~error dict 與 model union 回傳共存方式未定~~ → 已實測：union 可行但 `is_error=False` 語意錯誤，定案改 raise

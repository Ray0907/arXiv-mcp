# Changelog

## Unreleased

- Add stateless `get_recent(since="YYYY-MM-DD")` using inclusive UTC submission-date
  bounds and the shared advanced-search cache. Reject invalid/future dates; expose
  `total_results` and `has_more` so count-limited windows are not silently truncated.

- Add optional `abstract_max_chars` on `search`, `search_advanced`, and `get_recent`:
  `0` removes abstract text, positive values truncate it, and omitted/`null` keeps full
  abstracts. Result-count defaults and full cached metadata are unchanged.

- Add `read_paper` for outlines plus abstracts, named sections and 10,000-character fallback
  chunks, sharing the full-text cache. Cap responses (default 12,000 characters including
  the marker; minimum 256) and provide lossless continuation via `offset`.

- Add metadata-only `export_bibtex(ids)`, with stable cite keys, version deduplication,
  escaped fields, DOI/journal references and explicit missing IDs.

- Add `get_papers(ids)` for one-request batches of up to 50 IDs, with explicit missing IDs.

- Include optional primary category, comment, journal reference, DOI and feed version in paper metadata;
  omit these fields when unavailable.

- Read full paper text from canonical arXiv PDF URLs through Jina, not abstract pages.
- Reject malformed paper IDs and traversal/encoded-path URLs before making content requests.
- Report transport failures clearly; retry GETs once on HTTP 429/503/406 with capped `Retry-After`
  and total deadlines, preserving arXiv request spacing without duplicate throttle waits.
- Bound Atom and mention caches to 128 entries each, with TTL expiry and shorter freshness windows
  for newest-first searches. Keep paginated/versioned lookups distinct and cached results isolated.
- Make `get_content` local-only; fetch once on resource read and cache up to 32 full texts by ID
  (1 hour unversioned, 24 hours versioned). Preserve `arxiv://` links and readable resource errors.

## v0.5.0

**Breaking Changes:**
- `search`, `search_advanced`, `get_paper` and `get_recent` now call the official arXiv API
  (`export.arxiv.org/api/query`) instead of scraping HTML; `beautifulsoup4` is no longer a dependency
- Dates are ISO timestamps (`2017-06-12T17:57:34Z`), not `12 June, 2017`
- An unknown `sort_by` raises instead of being ignored
- `search_advanced` `id_arxiv` restricts the result to that ID instead of matching a pattern

**Improvements:**
- `date_updated` is filled in, and `get_recent` results include abstracts
- `search_advanced` date range now works
- `get_paper` and ID parsing accept versioned (`2301.00001v2`), legacy (`hep-th/9901001`) and `arXiv:`-prefixed IDs
- Requests are spaced 3 seconds apart per process and send a descriptive `User-Agent`, as the arXiv API terms ask
- Multi-word queries AND their words; a query containing a stopword is sent as a phrase because the API
  drops stopwords from ANDed words

## v0.4.0

**Breaking Changes:**
- Upgraded to MCP Python SDK v2 (`mcp>=2.0.0`); server now uses `MCPServer` (formerly `FastMCP`)
- Structured output: all tools declare an `outputSchema` and return typed structured content
  (`search`/`search_advanced` return `SearchResult`, `get_paper` returns `Paper`, `get_recent` returns `RecentPapers`)
- `list_categories` structured content is wrapped as `{"result": [...]}` because the MCP spec requires
  `structuredContent` to be a JSON object
- Errors no longer return `{"error": "..."}` dicts or error strings; all failures (HTTP errors, invalid
  arXiv ID, missing search fields) now raise and surface as standard MCP tool errors

**Improvements:**
- New `RecentPapers` model for `get_recent` responses

## v0.3.0

**Breaking Changes:**
- Renamed all tools to snake_case: `search_advanced`, `get_paper`, `get_content`, `get_recent`, `list_categories`
  (existing client configurations referencing camelCase names must be updated)

**Security:**
- Fixed SSRF bypass in `get_content`: non-arxiv.org URLs containing a valid arXiv ID in the path (e.g. `https://evil.com/abs/2301.00001`) are now correctly rejected

**Improvements:**
- All tools are now `async def` using `httpx.AsyncClient`
- HTTP errors return `{"error": "..."}` dicts instead of raising exceptions, so the LLM can read and retry
- All tools annotated with `readOnlyHint: true` and `openWorldHint: true`
- `SearchResult` now includes `has_more: bool` and `next_page: int | null` for easier pagination
- `list_categories` pre-computes the category list at import time instead of on every call

## v0.2.0

**Breaking Changes:**
- Renamed entry point from `arxiv-server.py` to `arxiv-mcp` command
- Renamed `get` tool to `getContent` for clarity

**New Features:**
- `searchAdvanced` - Advanced search with title, abstract, date range filters
- `getPaper` - Get detailed paper metadata (authors, categories, dates, PDF URL)
- `getRecent` - Browse recent papers by category
- `listCategories` - List 33 common arXiv categories
- Pagination support (`page`, `page_size` parameters)
- Sort options (`relevance`, `date_desc`, `date_asc`)
- Filter by author and category in basic search

**Improvements:**
- Migrated to `pyproject.toml` with uv for dependency management
- Replaced `requests` with `httpx` (async-ready)
- Added Pydantic models for type-safe data structures
- Reduced dependencies from 33 to 4 core packages
- Added proper timeout handling (30s)
- Modular project structure (`src/arxiv_mcp/`)

## v0.1.0

- Initial release
- Basic `search` and `get` tools

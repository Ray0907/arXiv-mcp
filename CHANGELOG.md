# Changelog

## Unreleased

**Improvements:**
- Full text now tries the arXiv HTML rendering through Jina first, which gives `read_paper` a fuller
  heading outline; stubs, error pages and failures fall back to the PDF path with its existing
  deadline, retry and error messages (the HTML attempt adds its own 30-second budget);
  the chosen source is remembered per paper ID so refetches never switch text mid-read

**Documentation:**
- README: `uvx --from git+https://github.com/Ray0907/arXiv-mcp arxiv-mcp` install without cloning,
  and a security note that paper text is untrusted content

## v0.6.0

**Breaking Changes:**
- `get_content` validates the ID locally and no longer contacts Jina; a missing paper or upstream
  failure now surfaces when the `arxiv://content/...` resource is read
- Malformed paper IDs and non-arXiv or traversal URLs are rejected before any content request

**New Tools:**
- `read_paper`: outline plus abstract by default, named sections or 10,000-character chunks,
  capped output (default 12,000 characters) with `offset` continuation
- `get_papers`: up to 50 IDs in one request, reporting `missing_ids`
- `export_bibtex`: BibTeX built from arXiv metadata only, with stable keys, version dedupe and escaping
- `get_references` / `get_citations`: compact citation graph via Semantic Scholar; optional
  `SEMANTIC_SCHOLAR_API_KEY` is sent only as a request header

**Improvements:**
- Full text now comes from the arXiv PDF through Jina; previously only the abstract page was read
- `get_recent` accepts `since="YYYY-MM-DD"` (UTC) and returns `total_results` and `has_more`
- `search`, `search_advanced` and `get_recent` accept `abstract_max_chars` to shorten or drop abstracts
- Papers include primary category, comment, journal reference, DOI and version when available
- Transport errors are reported clearly; HTTP 429/503/406 are retried once with capped `Retry-After`
  and a total deadline per call
- Query results (128 entries, 1–5 minutes) and full texts (32 papers, 1–24 hours) are cached

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

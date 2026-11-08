# arXiv MCP Server

A Model Context Protocol (MCP) server that provides arXiv paper search and retrieval capabilities. This server enables LLMs to search for academic papers on arXiv and get titles, abstracts, authors, and content from the official arXiv API.

## Features

- Search papers by query, author, category, and date
- Advanced search with specific field filters
- Get detailed paper metadata (title, abstract, authors, categories)
- Retrieve full paper content through server-backed MCP resource links without embedding large papers in tool results
- Browse recent papers by category
- List all arXiv categories
- Pagination support for search results

## Available Tools

### `search`
Search arXiv for papers matching a query.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `query` | string | Yes | Search query (e.g., 'LLM', 'transformer') |
| `category` | string | No | Filter by category (e.g., 'cs.AI', 'cs.LG') |
| `author` | string | No | Filter by author name |
| `sort_by` | string | No | Sort order: 'relevance', 'date_desc', 'date_asc', 'updated_desc', 'updated_asc' |
| `page` | int | No | Page number (default: 1) |
| `page_size` | int | No | Results per page, max 50 (default: 25) |

### `search_advanced`
Advanced search with specific field filters.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `title` | string | No | Search in paper titles |
| `abstract` | string | No | Search in abstracts |
| `author` | string | No | Search by author name |
| `category` | string | No | Filter by category |
| `id_arxiv` | string | No | Restrict to one arXiv ID; combines with the other filters |
| `date_from` | string | No | Start of submission date range (YYYY-MM-DD) |
| `date_to` | string | No | End of submission date range (YYYY-MM-DD) |
| `sort_by` | string | No | Same options as `search` |
| `page` | int | No | Page number |
| `page_size` | int | No | Results per page |

### `get_paper`
Get detailed information about a specific arXiv paper.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `id_or_url` | string | Yes | arXiv ID (e.g., '2301.00001') or full URL |

### `get_content`
Validate an arXiv paper through a streamed Jina Reader request, then return an `arxiv://` MCP resource link. Clients read the link through `resources/read`; the paper text is fetched only then and is never embedded in the tool result. A server-backed custom URI is used because MCP does not require every client to fetch external `https://` resource links directly.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `id_or_url` | string | Yes | arXiv ID or full URL |

### `get_recent`
Get recent papers from a specific arXiv category.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `category` | string | No | Category code (default: 'cs.AI') |
| `count` | int | No | Number of papers, max 50 (default: 10) |

### `list_categories`
List all common arXiv categories with their codes and names.

## Search Behavior

- Results come from the official arXiv API (`export.arxiv.org/api/query`). Requests are spaced 3 seconds
  apart per server process, as the API terms ask.
- The words of a query are ANDed. A query containing a stopword (`is`, `the`, `for`, ...) is sent as an exact
  phrase instead, because the API drops stopwords from ANDed words and would return nothing.
- A query that already uses arXiv field syntax (`ti:`, `au:`, `abs:`, `cat:`, `all:`) is passed through as is.
- Titles and abstracts keep their raw LaTeX (`$\alpha$`). Search by plain words (`alpha divergence`); LaTeX
  markup in a query does not match.
- Versioned IDs (`2301.00001v2`) are looked up as given. The API rejects versioned legacy IDs
  (`hep-th/9901001v1`), so the version is dropped for those.
- Dates in results are ISO timestamps, e.g. `2017-06-12T17:57:34Z`.

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/Ray0907/arXiv-mcp.git
cd arXiv-mcp

# Install with uv
uv sync
```

### Using pip

```bash
# Clone the repository
git clone https://github.com/Ray0907/arXiv-mcp.git
cd arXiv-mcp

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install
pip install -e .
```

## Configuration

### Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "arxiv": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/arXiv-mcp",
        "run",
        "arxiv-mcp"
      ]
    }
  }
}
```

### Claude Code

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "arxiv": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/arXiv-mcp",
        "run",
        "arxiv-mcp"
      ]
    }
  }
}
```

## Usage Examples

### Search for papers about LLMs

```
Search for recent papers about "large language models"
```

### Find papers by a specific author

```
Search for papers by "Yann LeCun" in the machine learning category
```

### Get paper details

```
Get the details of arXiv paper 2301.00001
```

### Browse recent papers

```
Show me the 10 most recent papers in cs.AI
```

## Development

### Run tests

```bash
uv run pytest
```

### Run the server locally

```bash
uv run arxiv-mcp
```

## Common arXiv Categories

| Code | Name |
|------|------|
| cs.AI | Artificial Intelligence |
| cs.CL | Computation and Language |
| cs.CV | Computer Vision and Pattern Recognition |
| cs.LG | Machine Learning |
| cs.NE | Neural and Evolutionary Computing |
| stat.ML | Machine Learning (Statistics) |

Use `list_categories` tool to get the full list.

## Changelog

### Unreleased

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

### v0.4.0

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

### v0.3.0

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

### v0.2.0

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

### v0.1.0

- Initial release
- Basic `search` and `get` tools

## License

MIT License - see [LICENSE](LICENSE) for details.

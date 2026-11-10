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
| `id_or_url` | string | Yes | Valid arXiv ID or arxiv.org abstract/PDF URL; Jina reads the canonical PDF, not the abstract page |

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
- arXiv and Jina transport failures surface as readable errors. GET requests retry once on HTTP
  429, 503 or 406, using `Retry-After` (seconds or HTTP date, capped at 10 seconds; default 1 second).
  Total deadlines include rate-limit and retry waits: 30 seconds for arXiv, 60 seconds for Jina.
- Per-process FIFO caches keep up to 128 Atom responses and 128 mention queries. Atom responses
  expire after 5 minutes (1 minute for `date_desc` and `updated_desc`); mentions expire after 5 minutes.
  Atom cache keys include all outgoing parameters, including page, page size and sort order.

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

### pi

```bash
pi mcp add arxiv -- uv --directory /path/to/arXiv-mcp run arxiv-mcp
pi mcp list
```

`pi mcp list` should show `arxiv: connected, 7 tools`. Tools are exposed through code mode by default; add
`--exposure direct` to `pi mcp add` to expose each tool directly. A project-level server (`-l`) is ignored
until you trust the project in pi.

### Antigravity CLI (agy)

```bash
agy mcp add arxiv -- uv --directory /path/to/arXiv-mcp run arxiv-mcp
agy mcp list
```

`agy mcp list` only shows that the server is enabled; start a session and call a tool to confirm. In
non-interactive mode (`agy -p`), MCP calls are denied until allowed, for example with an `mcp(*)` entry under
`permissions.allow` in `settings.json`.

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

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT License - see [LICENSE](LICENSE) for details.

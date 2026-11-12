"""arXiv MCP Server - Main server implementation."""

if __name__ == "__main__":
	# Delegate before creating caches or registering tools under a second module name.
	from arxiv_mcp.server import main
	main()
	raise SystemExit

import argparse
import asyncio
import re
import time
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, TypeVar

import httpx
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, ResourceLink
from openai_mcp_extensions import (
	OpenAIExtensions,
	OpenAIMentionSearchParams,
	OpenAIMentionSearchResult,
)

from .metadata import _parse_atom, clean_text, export_bibtex, get_papers
from .reading import read_paper
from .content import _content_cache, _content_source, paper_content  # noqa: F401
from .discovery import get_recent
from . import graph
from .graph import get_references, get_citations
from .models import (
	ARXIV_CATEGORIES,
	SORT_OPTIONS,
	Category,
	Paper,
	SearchResult,
)

openai_extensions = OpenAIExtensions()


MENTION_MIN_CHARS = 3  # ChatGPT sends one query per keystroke
MENTION_TTL = 300.0
MENTION_CACHE_SIZE = 128
MENTION_TIMEOUT = 8.0
MENTION_DEBOUNCE = 0.5  # keystrokes arrive as separate calls; only the newest one searches
MENTION_COOLDOWN = 15.0  # pause after an arXiv error (429), instead of hammering it
_mention_seq = 0
_mention_blocked_until = 0.0
_mention_cache: dict[str, tuple[float, list[ResourceLink]]] = {}

_CacheKey = TypeVar("_CacheKey")
_CacheValue = TypeVar("_CacheValue")


def _cache_get(cache: dict[_CacheKey, tuple[float, _CacheValue]], key: _CacheKey) -> Optional[_CacheValue]:
	hit = cache.get(key)
	if hit is not None:
		if time.monotonic() < hit[0]:
			return hit[1]
		del cache[key]
	return None


def _cache_put(
	cache: dict[_CacheKey, tuple[float, _CacheValue]], key: _CacheKey,
	value: _CacheValue, ttl: float, max_size: int,
) -> None:
	cache.pop(key, None)
	cache[key] = (time.monotonic() + ttl, value)
	while len(cache) > max_size:
		del cache[next(iter(cache))]


# Must be registered before MCPServer is constructed.
@openai_extensions.mentions.search
async def search_mentions(params: OpenAIMentionSearchParams, context) -> OpenAIMentionSearchResult:
	"""ChatGPT composer @-mention: typeahead over arXiv search."""
	global _mention_seq, _mention_blocked_until
	query = params.query.strip()
	if len(query) < MENTION_MIN_CHARS:
		return OpenAIMentionSearchResult(items=[])
	key = query.lower()
	hit = _cache_get(_mention_cache, key)
	if hit is not None:
		return OpenAIMentionSearchResult(items=hit)
	_mention_seq += 1
	seq = _mention_seq
	await asyncio.sleep(MENTION_DEBOUNCE)
	if seq != _mention_seq or time.monotonic() < _mention_blocked_until:
		return OpenAIMentionSearchResult(items=[])  # superseded by a newer keystroke, or cooling down
	try:
		result = await asyncio.wait_for(search(query), MENTION_TIMEOUT)
	except (asyncio.TimeoutError, ValueError):
		_mention_blocked_until = time.monotonic() + MENTION_COOLDOWN
		return OpenAIMentionSearchResult(items=[])  # not cached
	items = [
		ResourceLink(
			name=paper.title,
			uri=f"arxiv://content/{urllib.parse.quote(paper.id_arxiv, safe='')}",
			mimeType="text/markdown",
		)
		for paper in result.papers[:10]
	]
	_cache_put(_mention_cache, key, items, MENTION_TTL, MENTION_CACHE_SIZE)
	return OpenAIMentionSearchResult(items=items)


mcp = MCPServer("arXiv-server", extensions=[openai_extensions])

URL_BASE = "https://arxiv.org"
URL_EXPORT = "https://export.arxiv.org/api/query"
URL_JINA = "https://r.jina.ai"
_ARXIV_URL_PREFIXES = (f"{URL_BASE}/", "https://www.arxiv.org/")
TIMEOUT = 30.0
MAX_RETRY_AFTER = 10.0


# New style 2301.00001, legacy hep-th/9901001 or math.GT/0309136; optional vN; bare, arXiv:-prefixed, or in an abs/pdf URL.
_ARXIV_ID_RE = re.compile(
	r"^(?:arxiv:|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)?"
	r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)"
	r"(?:\.pdf)?/?$",
	re.IGNORECASE,
)


def _service_name(url: str) -> str:
	if url.startswith(graph.URL_GRAPH + "/"):
		return "Semantic Scholar"
	return "arXiv" if url == URL_EXPORT or url.startswith(URL_EXPORT + "?") else "Jina Reader"


def _http_error(exc: httpx.HTTPStatusError) -> ValueError:
	code = exc.response.status_code
	service = _service_name(str(exc.request.url))
	if service == "Semantic Scholar":
		if code == 404:
			return ValueError("Paper not found in Semantic Scholar (HTTP 404); it may still exist on arXiv.")
		if code == 429:
			return ValueError("Semantic Scholar returned HTTP 429: shared rate limit reached. Try again later or set SEMANTIC_SCHOLAR_API_KEY.")
	return ValueError(f"{service} returned HTTP {code}. Try adjusting your query or try again later.")


def extract_paper_id(url: str) -> Optional[str]:
	"""Extract arXiv paper ID from URL or return ID if already in ID format."""
	match = _ARXIV_ID_RE.search(url.strip())
	return match.group("id") if match else None


ARXIV_MIN_INTERVAL = 3.0  # arXiv API terms: at most one request per 3 seconds
USER_AGENT = "arxiv-mcp (+https://github.com/Ray0907/arXiv-mcp)"
_rate_lock = asyncio.Lock()
_last_request = 0.0

_VERSION_RE = re.compile(r"v\d+$")
MAX_PAGE_SIZE = 50
ATOM_TTL = 300.0
ATOM_RECENT_TTL = 60.0
ATOM_CACHE_SIZE = 128
_atom_cache: dict[tuple[tuple[str, str], ...], tuple[float, SearchResult]] = {}

# search_advanced / search argument -> (API field prefix, always a phrase)
_FIELD_PREFIXES = {"title": ("ti", False), "abstract": ("abs", False), "author": ("au", True), "category": ("cat", False)}
_STOPWORDS = frozenset(
	"a an and are as at be but by for if in into is it no not of on or such that the their then there these they this to was will with".split()
)
_FIELD_SYNTAX_RE = re.compile(r"\b(?:all|ti|au|abs|co|jr|cat|rn):", re.IGNORECASE)


async def _throttle() -> None:
	global _last_request
	async with _rate_lock:
		wait = _last_request + ARXIV_MIN_INTERVAL - time.monotonic()
		if wait > 0:
			await asyncio.sleep(wait)
		_last_request = time.monotonic()


def _retry_delay(response: httpx.Response) -> float:
	value = response.headers.get("Retry-After", "1")
	try:
		delay = int(value)
	except ValueError:
		try:
			delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
		except (ValueError, TypeError, OverflowError):
			delay = 1
	return max(0, min(delay, MAX_RETRY_AFTER))


async def _get(
	url: str, *, params: Optional[dict[str, str]] = None, timeout: float,
	headers: Optional[dict[str, str]] = None,
) -> httpx.Response:
	"""GET only; the deadline includes throttle, body reads and one status retry."""
	service = _service_name(url)

	async def request() -> httpx.Response:
		async with httpx.AsyncClient(
			timeout=timeout, headers={"User-Agent": USER_AGENT, **(headers or {})},
			follow_redirects=service != "Semantic Scholar",  # Never forward x-api-key to a redirect.
		) as client:
			for attempt in range(2):
				if url == URL_EXPORT:
					await _throttle()
				elif service == "Semantic Scholar":
					await graph._throttle()
				response = await client.get(url, params=params)
				if attempt == 0 and response.status_code in {429, 503, 406}:
					await asyncio.sleep(_retry_delay(response))
					continue
				response.raise_for_status()
				return response

	try:
		return await asyncio.wait_for(request(), timeout=timeout)
	except httpx.HTTPStatusError as exc:
		raise _http_error(exc) from None
	except httpx.TransportError as exc:
		reason = "request timed out" if isinstance(exc, httpx.TimeoutException) else "could not be reached"
		raise ValueError(f"{service} {reason}. Try again later.") from None
	except asyncio.TimeoutError as exc:
		raise ValueError(f"{service} request exceeded its {timeout:g}-second time limit. Try again later.") from None


def _compact_result(result: SearchResult, abstract_max_chars: Optional[int]) -> SearchResult:
	if abstract_max_chars is not None:
		for paper in result.papers:
			paper.abstract = paper.abstract[:abstract_max_chars]
	return result


async def _query_atom(
	params: dict[str, str], page: int = 1, page_size: int = 25, *,
	abstract_max_chars: Optional[int] = None,
) -> SearchResult:
	"""Call the arXiv Atom API; cache full metadata, then project caller-owned results."""
	if abstract_max_chars is not None and abstract_max_chars < 0:
		raise ValueError("abstract_max_chars must be non-negative (0 removes abstract text)")
	page = max(page, 1)
	page_size = max(1, min(page_size, MAX_PAGE_SIZE))
	request_params = {**params, "start": str((page - 1) * page_size), "max_results": str(page_size)}
	key = tuple(sorted(request_params.items()))
	hit = _cache_get(_atom_cache, key)
	if hit is not None:
		return _compact_result(hit.model_copy(deep=True), abstract_max_chars)

	response = await _get(URL_EXPORT, params=request_params, timeout=TIMEOUT)
	papers, total = _parse_atom(response.text)
	result = SearchResult(
		query=params.get("search_query") or params.get("id_list", ""),
		total_results=total,
		papers=papers,
		page=page,
		page_size=page_size,
	)
	recent = params.get("sortBy") in {"submittedDate", "lastUpdatedDate"} and params.get("sortOrder") == "descending"
	_cache_put(_atom_cache, key, result.model_copy(deep=True), ATOM_RECENT_TTL if recent else ATOM_TTL, ATOM_CACHE_SIZE)
	return _compact_result(result, abstract_max_chars)


def _sort_params(sort_by: str) -> dict[str, str]:
	if sort_by not in SORT_OPTIONS:
		raise ValueError(f"Unknown sort_by '{sort_by}'. Use one of: {', '.join(SORT_OPTIONS)}")
	api_sort_by, api_sort_order = SORT_OPTIONS[sort_by]
	return {"sortBy": api_sort_by, "sortOrder": api_sort_order}


def _term(prefix: str, value: str, phrase: bool = False) -> str:
	"""Words are ANDed for recall. The API drops stopwords from ANDed words ('is' makes the query match nothing), so a value with one becomes a phrase."""
	words = value.replace('"', " ").split()
	if len(words) <= 1:
		return f"{prefix}:{words[0]}" if words else ""
	if phrase or any(word.lower() in _STOPWORDS for word in words):
		return f'{prefix}:"{" ".join(words)}"'
	return " AND ".join(f"{prefix}:{word}" for word in words)


def _field_terms(**values: Optional[str]) -> list[str]:
	terms = (_term(prefix, values[name], phrase) for name, (prefix, phrase) in _FIELD_PREFIXES.items() if values.get(name))
	return [term for term in terms if term]


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search(
	query: str,
	category: Optional[str] = None,
	author: Optional[str] = None,
	sort_by: str = "relevance",
	page: int = 1,
	page_size: int = 25,
	abstract_max_chars: Optional[int] = None,
) -> SearchResult:
	"""
	Search arXiv for papers matching the query.

	Args:
		abstract_max_chars: Abstract character cap; None keeps full text, 0 returns an empty abstract
		query: Search query for arXiv papers (e.g., 'LLM', 'transformer architecture')
		category: Filter by arXiv category (e.g., 'cs.AI', 'cs.LG', 'stat.ML')
		author: Filter by author name
		sort_by: Sort order - 'relevance', 'date_desc', 'date_asc', 'updated_desc', 'updated_asc'
		page: Page number (default: 1)
		page_size: Results per page, max 50 (default: 25)

	Returns:
		Search results with papers containing title, abstract, authors, and URLs
	"""
	sort = _sort_params(sort_by)
	query = query.strip()
	# A query that already uses API field syntax (ti:, au:, ...) is passed through untouched.
	text_term = query if _FIELD_SYNTAX_RE.search(query) else _term("all", query)
	terms = ([text_term] if text_term else []) + _field_terms(author=author, category=category)
	if not terms:
		raise ValueError("A query, author or category is required")

	return await _query_atom(
		{"search_query": " AND ".join(terms), **sort}, page, page_size,
		abstract_max_chars=abstract_max_chars,
	)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_advanced(
	title: Optional[str] = None,
	abstract: Optional[str] = None,
	author: Optional[str] = None,
	category: Optional[str] = None,
	id_arxiv: Optional[str] = None,
	date_from: Optional[str] = None,
	date_to: Optional[str] = None,
	sort_by: str = "relevance",
	page: int = 1,
	page_size: int = 25,
	abstract_max_chars: Optional[int] = None,
) -> SearchResult:
	"""
	Advanced search with specific field filters.

	Args:
		abstract_max_chars: Abstract character cap; None keeps full text, 0 returns an empty abstract
		title: Search in paper titles
		abstract: Search in abstracts
		author: Search by author name
		category: Filter by arXiv category (e.g., 'cs.AI', 'cs.LG')
		id_arxiv: Restrict to an arXiv ID (e.g., '2301.00001'); combines with the other filters
		date_from: Start of submission date range (YYYY-MM-DD format)
		date_to: End of submission date range (YYYY-MM-DD format)
		sort_by: Sort order - 'relevance', 'date_desc', 'date_asc', 'updated_desc', 'updated_asc'
		page: Page number (default: 1)
		page_size: Results per page, max 50 (default: 25)

	Returns:
		Search results with papers containing title, abstract, authors, and URLs
	"""
	sort = _sort_params(sort_by)
	terms = _field_terms(title=title, abstract=abstract, author=author, category=category)

	if date_from or date_to:
		# The API needs both bounds; arXiv's first submissions date from 1991.
		day_from = _api_day(date_from) if date_from else "19910101"
		day_to = _api_day(date_to) if date_to else datetime.now(timezone.utc).strftime("%Y%m%d")
		terms.append(f"submittedDate:[{day_from}0000 TO {day_to}2359]")

	params = dict(sort)
	if id_arxiv:
		params["id_list"] = _api_id(extract_paper_id(id_arxiv) or id_arxiv.strip())
	if not terms and "id_list" not in params:
		raise ValueError("At least one search field is required")
	if terms:
		params["search_query"] = " AND ".join(terms)

	return await _query_atom(params, page, page_size, abstract_max_chars=abstract_max_chars)


def _api_id(id_arxiv: str) -> str:
	"""The API fails on a versioned legacy ID (hep-th/9901001v1), so only new-style IDs keep their version."""
	return _VERSION_RE.sub("", id_arxiv) if "/" in id_arxiv else id_arxiv


def _api_day(value: str) -> str:
	try:
		return datetime.strptime(value.strip(), "%Y-%m-%d").strftime("%Y%m%d")
	except ValueError:
		raise ValueError(f"Dates must use YYYY-MM-DD format, got: {value}") from None


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_paper(id_or_url: str) -> Paper:
	"""
	Get detailed information about a specific arXiv paper.

	Args:
		id_or_url: arXiv paper ID (e.g., '2301.00001') or full arXiv URL

	Returns:
		Paper details including title, abstract, authors, categories, and URLs
	"""
	id_arxiv = extract_paper_id(id_or_url)
	if not id_arxiv:
		raise ValueError(f"Could not extract arXiv ID from: {id_or_url}")

	result = await _query_atom({"id_list": _api_id(id_arxiv)})
	if not result.papers:
		raise ValueError(f"No arXiv paper found for: {id_arxiv}")

	paper = result.papers[0]
	# The feed id is versionless in our model; a pinned request keeps its version.
	if _api_id(id_arxiv) == id_arxiv and _VERSION_RE.search(id_arxiv):
		paper = paper.model_copy(update={"id_arxiv": id_arxiv})
	return paper


mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})(get_papers)
mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})(export_bibtex)
mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})(read_paper)


def _content_id(id_or_url: str) -> str:
	id_or_url = id_or_url.strip()
	if id_or_url.startswith(('https://', 'http://')):
		if not any(id_or_url.startswith(prefix) for prefix in _ARXIV_URL_PREFIXES):
			raise ValueError(f'URL must point to arxiv.org, got: {id_or_url}')
	id_arxiv = extract_paper_id(id_or_url)
	if not id_arxiv:
		raise ValueError(f"Could not extract arXiv ID from: {id_or_url}")
	return id_arxiv


@mcp.resource(
	"arxiv://content/{id_or_url}",
	name="arXiv paper content",
	mime_type="text/markdown",
)
async def read_paper_content(id_or_url: str) -> str:
	"""Read the full text of an arXiv paper through Jina Reader."""
	try:
		return await paper_content(id_or_url)
	except ValueError as exc:
		# The SDK masks ordinary resource exceptions, including readable upstream errors.
		raise MCPError(INTERNAL_ERROR, str(exc)) from exc


@mcp.tool(
	annotations={"readOnlyHint": True, "openWorldHint": True},
	structured_output=False,
)
async def get_content(id_or_url: str) -> ResourceLink:
	"""
	Return a full-text resource link after local ID validation, without HTTP.
	Read the resource to fetch text through Jina Reader; upstream errors surface on read.

	Args:
		id_or_url: arXiv paper ID (e.g., '2301.00001') or full arXiv URL

	Returns:
		Resource link to the paper's full text in markdown format
	"""
	_content_id(id_or_url)
	return ResourceLink(
		name="arXiv paper content",
		uri=f"arxiv://content/{urllib.parse.quote(id_or_url, safe='')}",
		mimeType="text/markdown",
	)


def _build_categories() -> list[Category]:
	categories = []
	for code, name in ARXIV_CATEGORIES.items():
		if code.startswith("cs."):
			group = "Computer Science"
		elif code.startswith("stat."):
			group = "Statistics"
		elif code.startswith("math."):
			group = "Mathematics"
		elif code.startswith("eess."):
			group = "Electrical Engineering"
		elif code.startswith("q-bio."):
			group = "Quantitative Biology"
		elif code.startswith("q-fin."):
			group = "Quantitative Finance"
		else:
			group = "Physics"
		categories.append(Category(code=code, name=name, group=group))
	return sorted(categories, key=lambda x: (x.group, x.code))


_CATEGORIES_CACHE: list[Category] = _build_categories()


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def list_categories() -> list[Category]:
	"""
	List all common arXiv categories.

	Returns:
		List of arXiv categories with code, name, and group
	"""
	return _CATEGORIES_CACHE


mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})(get_recent)
mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})(get_references)
mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})(get_citations)


def main():
	"""Run the arXiv MCP server over stdio (default) or Streamable HTTP."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--http", action="store_true", help="Serve Streamable HTTP at /mcp")
	parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default: 127.0.0.1)")
	parser.add_argument("--port", type=int, default=8000, help="HTTP bind port (default: 8000)")
	args = parser.parse_args()
	if args.http:
		mcp.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path="/mcp")
	else:
		mcp.run(transport="stdio")

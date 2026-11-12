"""Full-text sourcing: arXiv HTML first, PDF fallback, one source per paper ID."""

import httpx

from .reading import _split_sections

CONTENT_TTL = 3600.0
CONTENT_VERSION_TTL = 86400.0
CONTENT_CACHE_SIZE = 32
_content_cache: dict[str, tuple[float, str]] = {}


def _jina_url(id_or_url: str, kind: str = "pdf") -> str:
	from . import server

	return f"{server.URL_JINA}/{server.URL_BASE}/{kind}/{server._content_id(id_or_url)}"


HTML_MIN_CHARS = 2000
HTML_MIN_SECTIONS = 2
CONTENT_SOURCE_SIZE = 1024
# Paper ID -> "html" | "pdf". Outlives _content_cache so a refetch never changes the text under a caller's selectors.
_content_source: dict[str, str] = {}


async def _html_text(id_arxiv: str) -> str:
	"""Jina can answer HTTP 200 with an image caption or an arXiv error page, so judge the content."""
	from . import server

	try:
		text = (await server._get(_jina_url(id_arxiv, "html"), timeout=server.TIMEOUT)).text
	except httpx.HTTPError:  # _get leaves DecodingError and TooManyRedirects unwrapped
		raise ValueError("Jina Reader could not read the arXiv HTML page. Try again later.") from None
	if len(text) < HTML_MIN_CHARS or len(_split_sections(text)) < HTML_MIN_SECTIONS:
		raise ValueError("The arXiv HTML page is no longer usable for this paper. Try again later.")
	return text


async def _fetch_content(id_arxiv: str, source: str) -> str:
	from . import server

	if source == "html":
		return await _html_text(id_arxiv)
	return (await server._get(_jina_url(id_arxiv), timeout=server.TIMEOUT * 2)).text


def _pin_source(id_arxiv: str, source: str) -> str:
	"""Keep the first source recorded for an ID; evict the least recently read ID beyond the bound."""
	if id_arxiv not in _content_source and len(_content_source) >= CONTENT_SOURCE_SIZE:
		del _content_source[next(iter(_content_source))]
	return _content_source.setdefault(id_arxiv, source)


async def paper_content(id_or_url: str) -> str:
	"""Read and cache full text by canonical ID, keeping pinned revisions separate.

	The first successful read picks arXiv HTML (real headings) or the PDF fallback, and
	later refetches use that same source or fail, so section:N and offset stay valid.
	"""
	from . import server

	id_arxiv = server._content_id(id_or_url)
	if id_arxiv in _content_source:
		_content_source[id_arxiv] = _content_source.pop(id_arxiv)  # LRU: a hot paper keeps its pin
	hit = server._cache_get(_content_cache, id_arxiv)
	if hit is not None:
		return hit
	source = _content_source.get(id_arxiv)
	if source is None:
		try:
			text, source = await _html_text(id_arxiv), "html"
		except ValueError:
			text, source = await _fetch_content(id_arxiv, "pdf"), "pdf"
		pinned = _pin_source(id_arxiv, source)  # a concurrent first read may have pinned the other source
		if pinned != source:
			text = server._cache_get(_content_cache, id_arxiv) or await _fetch_content(id_arxiv, pinned)
	else:
		text = await _fetch_content(id_arxiv, source)
	ttl = CONTENT_VERSION_TTL if server._VERSION_RE.search(id_arxiv) else CONTENT_TTL
	server._cache_put(_content_cache, id_arxiv, text, ttl, CONTENT_CACHE_SIZE)
	return text

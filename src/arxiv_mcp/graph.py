"""Bounded Semantic Scholar discovery, independent of the arXiv request slot."""

import asyncio
import os
import time

from .models import RelatedPaper, RelatedPapers

URL_GRAPH = "https://api.semanticscholar.org/graph/v1"
MIN_INTERVAL = 1.0  # Per process; unauthenticated callers also share the upstream global limit.
CACHE_TTL = 300.0
CACHE_SIZE = 128
_rate_lock = asyncio.Lock()
_last_request = 0.0
_cache: dict[tuple[str, str, int], tuple[float, RelatedPapers]] = {}


async def _throttle() -> None:
	global _last_request
	async with _rate_lock:
		wait = _last_request + MIN_INTERVAL - time.monotonic()
		if wait > 0:
			await asyncio.sleep(wait)
		_last_request = time.monotonic()


async def _related(id_or_url: str, relation: str, limit: int) -> RelatedPapers:
	from . import server

	id_arxiv = server.extract_paper_id(id_or_url)
	if not id_arxiv:
		raise ValueError("Could not extract arXiv ID; provide an arXiv ID or arxiv.org abs/pdf URL")
	id_arxiv = server._VERSION_RE.sub("", id_arxiv)
	if type(limit) is not int or not 1 <= limit <= 50:
		raise ValueError("limit must be an integer from 1 to 50")
	key = (id_arxiv, relation, limit)
	hit = server._cache_get(_cache, key)
	if hit is not None:
		return hit.model_copy(deep=True)

	api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
	response = await server._get(
		f"{URL_GRAPH}/paper/ARXIV:{id_arxiv}/{relation}",
		params={"fields": "title,externalIds,year,authors", "limit": str(limit)},
		timeout=server.TIMEOUT, headers={"x-api-key": api_key} if api_key else None,
	)
	try:
		payload = response.json()
		if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
			raise ValueError
		papers = []
		for edge in payload["data"][:limit]:
			paper = edge["citedPaper" if relation == "references" else "citingPaper"]
			if paper is None:
				continue  # Semantic Scholar can leave unresolved edges without paper metadata.
			raw_id = (paper.get("externalIds") or {}).get("ArXiv")
			papers.append(RelatedPaper(
				title=paper["title"], id_arxiv=server.extract_paper_id(raw_id) if raw_id else None,
				year=paper.get("year"), authors=[a["name"] for a in (paper.get("authors") or [])],
			))
		result = RelatedPapers(
			id_arxiv=id_arxiv, papers=papers,
			has_more=payload.get("next") is not None or len(payload["data"]) > limit,
		)
	except (ValueError, TypeError, KeyError, AttributeError):
		raise ValueError("Semantic Scholar returned an invalid graph response. Try again later.") from None
	server._cache_put(_cache, key, result.model_copy(deep=True), CACHE_TTL, CACHE_SIZE)
	return result


async def get_references(id_or_url: str, limit: int = 10) -> RelatedPapers:
	"""Get papers cited by an arXiv paper using Semantic Scholar (not revision-specific).

	Args:
		id_or_url: arXiv ID or arxiv.org abs/pdf URL
		limit: Maximum edges to inspect, 1–50 (default: 10); unresolved edges are skipped

	Returns:
		Compact papers (title, optional arXiv ID/year, authors) and has_more.
		Coverage is incomplete; HTTP 404 means absent from Semantic Scholar, not arXiv.
	"""
	return await _related(id_or_url, "references", limit)


async def get_citations(id_or_url: str, limit: int = 10) -> RelatedPapers:
	"""Get papers citing an arXiv paper using Semantic Scholar (not revision-specific).

	Args:
		id_or_url: arXiv ID or arxiv.org abs/pdf URL
		limit: Maximum edges to inspect, 1–50 (default: 10); unresolved edges are skipped

	Returns:
		Compact papers (title, optional arXiv ID/year, authors) and has_more.
		Coverage is incomplete; HTTP 404 means absent from Semantic Scholar, not arXiv.
	"""
	return await _related(id_or_url, "citations", limit)

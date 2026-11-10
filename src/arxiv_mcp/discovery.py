"""Stateless discovery using the shared arXiv search and caches."""

import re
from typing import Optional

from .models import ARXIV_CATEGORIES, RecentPapers


async def get_recent(
	category: str = "cs.AI", count: int = 10, abstract_max_chars: Optional[int] = None,
	since: Optional[str] = None,
) -> RecentPapers:
	"""Get newest submissions, optionally since an inclusive UTC date (no saved state).

	Args:
		category: arXiv category code (default: 'cs.AI')
		count: Maximum papers returned, clamped to 1–50 (default: 10)
		abstract_max_chars: Abstract character cap; None keeps full text, 0 returns an empty abstract
		since: Inclusive YYYY-MM-DD submission date, through today in UTC; no future dates

	Returns:
		Recent papers with total_results and has_more to disclose count-limited windows.
		For more results use search_advanced with category, date_from=since,
		sort_by='date_desc', and page/page_size.
	"""
	from . import server

	if since is not None:
		try:
			if not isinstance(since, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", since):
				raise ValueError
			day_from = server._api_day(since)
		except ValueError:
			raise ValueError("since must be a valid date in YYYY-MM-DD format") from None
		today = server.datetime.now(server.timezone.utc).date().isoformat()
		if day_from > today.replace("-", ""):
			raise ValueError("since must not be a future date (UTC)")
		result = await server.search_advanced(
			category=category, date_from=since, date_to=today, sort_by="date_desc",
			page_size=count, abstract_max_chars=abstract_max_chars,
		)
	else:
		result = await server._query_atom(
			{"search_query": f"cat:{category}", **server._sort_params("date_desc")}, page_size=count,
			abstract_max_chars=abstract_max_chars,
		)
	return RecentPapers(
		category=category, category_name=ARXIV_CATEGORIES.get(category, category),
		count=len(result.papers), papers=result.papers,
		total_results=result.total_results, has_more=result.has_more,
	)

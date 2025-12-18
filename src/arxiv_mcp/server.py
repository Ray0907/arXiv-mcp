"""arXiv MCP Server - Main server implementation."""

import re
import urllib.parse
from functools import lru_cache
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

from .models import (
	ARXIV_CATEGORIES,
	SORT_OPTIONS,
	Paper,
	SearchResult,
)

mcp = FastMCP("arXiv-server")

URL_BASE = "https://arxiv.org"
URL_EXPORT = "https://export.arxiv.org"
URL_JINA = "https://r.jina.ai"
TIMEOUT = 30.0


def extractPaperId(url: str) -> Optional[str]:
	"""Extract arXiv paper ID from URL or return ID if already in ID format."""
	patterns = [
		r"arxiv\.org/abs/(\d+\.\d+)",
		r"arxiv\.org/pdf/(\d+\.\d+)",
		r"^(\d+\.\d+)$",
	]
	for pattern in patterns:
		match = re.search(pattern, url)
		if match:
			return match.group(1)
	return None


def cleanText(text: str) -> str:
	"""Clean and normalize text content."""
	text = text.replace("\n", " ")
	text = " ".join(text.split())
	return text.strip()


def parseSearchResults(html: str, query: str, page: int, page_size: int) -> SearchResult:
	"""Parse arXiv search results HTML into structured data."""
	soup = BeautifulSoup(html, "html.parser")
	items = soup.select(".arxiv-result")

	# Try to extract total results count
	total_text = soup.select_one(".title.is-clearfix")
	total_results = 0
	if total_text:
		match = re.search(r"of ([\d,]+) results", total_text.text)
		if match:
			total_results = int(match.group(1).replace(",", ""))

	papers = []
	for item in items:
		try:
			# Extract title
			title_elem = item.select_one(".title")
			title = cleanText(title_elem.text) if title_elem else "Unknown Title"

			# Extract abstract
			abstract_elem = item.select_one(".abstract-full")
			if not abstract_elem:
				abstract_elem = item.select_one(".abstract")
			abstract = cleanText(abstract_elem.text) if abstract_elem else ""
			# Remove "Less" or "More" button text
			abstract = re.sub(r"\s*(Less|More)\s*$", "", abstract)
			abstract = re.sub(r"^Abstract:\s*", "", abstract)

			# Extract URL and ID
			url_elem = item.select_one(".list-title > span > a")
			url_abstract = url_elem.get("href") if url_elem else ""
			id_arxiv = extractPaperId(url_abstract) or ""

			# Extract authors
			authors = []
			authors_elem = item.select(".authors a")
			for author in authors_elem:
				authors.append(author.text.strip())

			# Extract categories
			categories = []
			tags = item.select(".tag.is-small")
			for tag in tags:
				cat_text = tag.text.strip()
				if cat_text and not cat_text.startswith("doi:"):
					categories.append(cat_text)

			# Extract dates
			date_elem = item.select_one(".is-size-7")
			date_published = None
			date_updated = None
			if date_elem:
				date_text = date_elem.text
				submitted_match = re.search(r"Submitted\s+(\d+\s+\w+,?\s+\d+)", date_text)
				if submitted_match:
					date_published = submitted_match.group(1)

			paper = Paper(
				id_arxiv=id_arxiv,
				title=title,
				abstract=abstract,
				authors=authors,
				categories=categories,
				url_abstract=url_abstract,
				url_pdf=f"https://arxiv.org/pdf/{id_arxiv}.pdf" if id_arxiv else "",
				date_published=date_published,
				date_updated=date_updated,
			)
			papers.append(paper)
		except Exception:
			# Skip papers that fail to parse
			continue

	return SearchResult(
		query=query,
		total_results=total_results,
		papers=papers,
		page=page,
		page_size=page_size,
	)


@mcp.tool()
def search(
	query: str,
	category: Optional[str] = None,
	author: Optional[str] = None,
	sort_by: str = "relevance",
	page: int = 1,
	page_size: int = 25,
) -> dict:
	"""
	Search arXiv for papers matching the query.

	Args:
		query: Search query for arXiv papers (e.g., 'LLM', 'transformer architecture')
		category: Filter by arXiv category (e.g., 'cs.AI', 'cs.LG', 'stat.ML')
		author: Filter by author name
		sort_by: Sort order - 'relevance', 'date_desc', 'date_asc'
		page: Page number (default: 1)
		page_size: Results per page, max 50 (default: 25)

	Returns:
		Search results with papers containing title, abstract, authors, and URLs
	"""
	page_size = min(page_size, 50)
	start = (page - 1) * page_size

	# Build search query
	search_terms = []
	if query:
		search_terms.append(query)
	if author:
		search_terms.append(f"au:{author}")
	if category:
		search_terms.append(f"cat:{category}")

	full_query = " AND ".join(search_terms) if len(search_terms) > 1 else (search_terms[0] if search_terms else "")
	encoded_query = urllib.parse.quote_plus(full_query)

	sort_order = SORT_OPTIONS.get(sort_by, "")
	url = (
		f"{URL_BASE}/search/?query={encoded_query}"
		f"&searchtype=all&abstracts=show"
		f"&order={sort_order}&size={page_size}&start={start}"
	)

	with httpx.Client(timeout=TIMEOUT) as client:
		response = client.get(url)
		response.raise_for_status()

	result = parseSearchResults(response.text, full_query, page, page_size)
	return result.model_dump()


@mcp.tool()
def searchAdvanced(
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
) -> dict:
	"""
	Advanced search with specific field filters.

	Args:
		title: Search in paper titles
		abstract: Search in abstracts
		author: Search by author name
		category: Filter by arXiv category (e.g., 'cs.AI', 'cs.LG')
		id_arxiv: Search by arXiv ID pattern
		date_from: Start date filter (YYYY-MM-DD format)
		date_to: End date filter (YYYY-MM-DD format)
		sort_by: Sort order - 'relevance', 'date_desc', 'date_asc'
		page: Page number (default: 1)
		page_size: Results per page, max 50 (default: 25)

	Returns:
		Search results with papers containing title, abstract, authors, and URLs
	"""
	page_size = min(page_size, 50)
	start = (page - 1) * page_size

	# Build advanced query parts
	query_parts = []
	if title:
		query_parts.append(f"ti:{title}")
	if abstract:
		query_parts.append(f"abs:{abstract}")
	if author:
		query_parts.append(f"au:{author}")
	if category:
		query_parts.append(f"cat:{category}")
	if id_arxiv:
		query_parts.append(f"id:{id_arxiv}")

	if not query_parts:
		return {"error": "At least one search field is required"}

	full_query = " AND ".join(query_parts)
	encoded_query = urllib.parse.quote_plus(full_query)

	sort_order = SORT_OPTIONS.get(sort_by, "")

	# Build URL with date filters if provided
	url = (
		f"{URL_BASE}/search/advanced?terms-0-operator=AND"
		f"&terms-0-term={encoded_query}&terms-0-field=all"
		f"&classification-physics_archives=all"
		f"&classification-include_cross_list=include"
		f"&abstracts=show&size={page_size}&start={start}"
		f"&order={sort_order}"
	)

	if date_from:
		url += f"&date-from_date={date_from}"
	if date_to:
		url += f"&date-to_date={date_to}"

	with httpx.Client(timeout=TIMEOUT) as client:
		response = client.get(url)
		response.raise_for_status()

	result = parseSearchResults(response.text, full_query, page, page_size)
	return result.model_dump()


@mcp.tool()
def getPaper(id_or_url: str) -> dict:
	"""
	Get detailed information about a specific arXiv paper.

	Args:
		id_or_url: arXiv paper ID (e.g., '2301.00001') or full arXiv URL

	Returns:
		Paper details including title, abstract, authors, categories, and URLs
	"""
	id_arxiv = extractPaperId(id_or_url)
	if not id_arxiv:
		return {"error": f"Could not extract arXiv ID from: {id_or_url}"}

	url_abstract = f"{URL_BASE}/abs/{id_arxiv}"

	with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
		response = client.get(url_abstract)
		response.raise_for_status()

	soup = BeautifulSoup(response.text, "html.parser")

	# Extract title
	title_elem = soup.select_one(".title.mathjax")
	title = cleanText(title_elem.text.replace("Title:", "")) if title_elem else "Unknown"

	# Extract abstract
	abstract_elem = soup.select_one(".abstract.mathjax")
	abstract = cleanText(abstract_elem.text.replace("Abstract:", "")) if abstract_elem else ""

	# Extract authors
	authors = []
	authors_div = soup.select_one(".authors")
	if authors_div:
		for a in authors_div.select("a"):
			authors.append(a.text.strip())

	# Extract categories
	categories = []
	subj_elem = soup.select_one(".tablecell.subjects")
	if subj_elem:
		for span in subj_elem.select("span.primary-subject"):
			cat_match = re.search(r"\(([^)]+)\)", span.text)
			if cat_match:
				categories.append(cat_match.group(1))
		# Also get secondary subjects
		subj_text = subj_elem.text
		cat_matches = re.findall(r"\(([a-z-]+\.[A-Z]+)\)", subj_text)
		for cat in cat_matches:
			if cat not in categories:
				categories.append(cat)

	# Extract dates
	date_submitted = None
	date_history = soup.select_one(".dateline")
	if date_history:
		date_match = re.search(r"Submitted.*?(\d+\s+\w+\s+\d+)", date_history.text)
		if date_match:
			date_submitted = date_match.group(1)

	paper = Paper(
		id_arxiv=id_arxiv,
		title=title,
		abstract=abstract,
		authors=authors,
		categories=categories,
		url_abstract=url_abstract,
		url_pdf=f"{URL_BASE}/pdf/{id_arxiv}.pdf",
		date_published=date_submitted,
	)

	return paper.model_dump()


@mcp.tool()
def getContent(id_or_url: str) -> str:
	"""
	Get the full text content of an arXiv paper using Jina Reader.

	Args:
		id_or_url: arXiv paper ID (e.g., '2301.00001') or full arXiv URL

	Returns:
		Full text content of the paper in markdown format
	"""
	id_arxiv = extractPaperId(id_or_url)
	if not id_arxiv:
		# Try using the URL directly
		url_target = id_or_url if id_or_url.startswith("http") else f"{URL_BASE}/abs/{id_or_url}"
	else:
		url_target = f"{URL_BASE}/abs/{id_arxiv}"

	jina_url = f"{URL_JINA}/{url_target}"

	with httpx.Client(timeout=TIMEOUT * 2) as client:
		response = client.get(jina_url)
		response.raise_for_status()

	return response.text


@mcp.tool()
@lru_cache(maxsize=1)
def listCategories() -> list[dict]:
	"""
	List all common arXiv categories.

	Returns:
		List of arXiv categories with code, name, and group
	"""
	categories = []
	for code, name in ARXIV_CATEGORIES.items():
		# Determine group from code prefix
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

		categories.append({"code": code, "name": name, "group": group})

	return sorted(categories, key=lambda x: (x["group"], x["code"]))


@mcp.tool()
def getRecent(category: str = "cs.AI", count: int = 10) -> dict:
	"""
	Get recent papers from a specific arXiv category.

	Args:
		category: arXiv category code (default: 'cs.AI')
		count: Number of papers to retrieve (max 50, default: 10)

	Returns:
		Recent papers from the specified category
	"""
	count = min(count, 50)
	url = f"{URL_BASE}/list/{category}/recent?skip=0&show={count}"

	with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
		response = client.get(url)
		response.raise_for_status()

	soup = BeautifulSoup(response.text, "html.parser")

	papers = []
	entries = soup.select("dl#articles dt, dl#articles dd")

	# Process dt/dd pairs
	i = 0
	while i < len(entries) - 1:
		if entries[i].name == "dt" and entries[i + 1].name == "dd":
			dt = entries[i]
			dd = entries[i + 1]

			# Extract ID from dt
			id_link = dt.select_one("a[href*='/abs/']")
			id_arxiv = ""
			if id_link:
				href = id_link.get("href", "")
				id_match = re.search(r"/abs/(\d+\.\d+)", href)
				if id_match:
					id_arxiv = id_match.group(1)

			# Extract title
			title_elem = dd.select_one(".list-title")
			title = cleanText(title_elem.text.replace("Title:", "")) if title_elem else ""

			# Extract authors
			authors = []
			authors_elem = dd.select_one(".list-authors")
			if authors_elem:
				for a in authors_elem.select("a"):
					authors.append(a.text.strip())

			# Extract subjects
			categories = []
			subj_elem = dd.select_one(".list-subjects")
			if subj_elem:
				subj_text = subj_elem.text
				cat_matches = re.findall(r"([a-z-]+\.[A-Z]+)", subj_text)
				categories = list(set(cat_matches))

			if id_arxiv:
				paper = Paper(
					id_arxiv=id_arxiv,
					title=title,
					abstract="",  # Not available in list view
					authors=authors,
					categories=categories,
					url_abstract=f"{URL_BASE}/abs/{id_arxiv}",
					url_pdf=f"{URL_BASE}/pdf/{id_arxiv}.pdf",
				)
				papers.append(paper.model_dump())

			i += 2
		else:
			i += 1

	return {
		"category": category,
		"category_name": ARXIV_CATEGORIES.get(category, category),
		"count": len(papers),
		"papers": papers,
	}


def main():
	"""Run the arXiv MCP server."""
	mcp.run(transport="stdio")


if __name__ == "__main__":
	main()

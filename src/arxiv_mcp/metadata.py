"""Batch metadata tools, sharing the server's Atom transport and cache."""

from .models import PaperBatch


async def get_papers(ids: list[str]) -> PaperBatch:
	"""Look up 1–50 arXiv IDs/URLs in one API request; report missing IDs separately.

	Exact duplicate IDs are collapsed. Legacy revisions use the latest metadata,
	as with get_paper. Invalid IDs fail locally before any request.
	"""
	from .server import MAX_PAGE_SIZE, _VERSION_RE, _api_id, _query_atom, extract_paper_id

	if not 1 <= len(ids) <= MAX_PAGE_SIZE:
		raise ValueError(f"Supply 1–{MAX_PAGE_SIZE} IDs per batch.")
	requested = []
	for raw in ids:
		id_arxiv = extract_paper_id(raw)
		if not id_arxiv:
			raise ValueError(f"Could not extract arXiv ID from: {raw}")
		requested.append(_api_id(id_arxiv))
	requested = list(dict.fromkeys(requested))
	result = await _query_atom({"id_list": ",".join(requested)}, page_size=len(requested))
	papers, missing = [], []
	for id_arxiv in requested:
		base = _VERSION_RE.sub("", id_arxiv)
		version = _VERSION_RE.search(id_arxiv)
		paper = next((p for p in result.papers if p.id_arxiv == base and (
			not version or p.version == int(version.group()[1:])
		)), None)
		if paper is None:
			missing.append(id_arxiv)
		else:
			papers.append(paper.model_copy(update={"id_arxiv": id_arxiv}))
	return PaperBatch(papers=papers, missing_ids=missing)

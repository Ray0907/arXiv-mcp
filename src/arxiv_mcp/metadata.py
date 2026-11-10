"""Atom metadata and citation tools, sharing the server's transport and cache."""

import re
import xml.etree.ElementTree as ET
from typing import Optional

from .models import BibtexExport, Paper, PaperBatch


def clean_text(text: str) -> str:
	"""Clean and normalize text content."""
	text = text.replace("\n", " ")
	text = " ".join(text.split())
	return text.strip()


_NS = {
	"atom": "http://www.w3.org/2005/Atom",
	"opensearch": "http://a9.com/-/spec/opensearch/1.1/",
	"arxiv": "http://arxiv.org/schemas/atom",
}

def _text(node: Optional[ET.Element]) -> str:
	return clean_text(node.text or "") if node is not None else ""


def _parse_atom(xml_text: str) -> tuple[list[Paper], int]:
	"""Parse an arXiv API Atom feed into papers and the opensearch total."""
	from .server import URL_BASE, _VERSION_RE, extract_paper_id
	try:
		root = ET.fromstring(xml_text)
	except ET.ParseError as exc:
		raise ValueError("arXiv returned an unparseable response. Try again later.") from exc

	total = int(_text(root.find("opensearch:totalResults", _NS)) or 0)
	papers = []
	for entry in root.findall("atom:entry", _NS):
		raw_id = _text(entry.find("atom:id", _NS))
		# Invalid requests come back as HTTP 200 with one entry titled "Error".
		if _text(entry.find("atom:title", _NS)) == "Error" and "/api/errors" in raw_id:
			raise ValueError(f"arXiv API error: {_text(entry.find('atom:summary', _NS))}")

		id_arxiv = _VERSION_RE.sub("", extract_paper_id(raw_id) or raw_id)
		version = _VERSION_RE.search(raw_id)
		primary = entry.find("arxiv:primary_category", _NS)
		categories = [c.get("term", "") for c in entry.findall("atom:category", _NS)]
		papers.append(
			Paper(
				id_arxiv=id_arxiv,
				title=_text(entry.find("atom:title", _NS)),
				abstract=_text(entry.find("atom:summary", _NS)),
				authors=[_text(n) for n in entry.findall("atom:author/atom:name", _NS)],
				categories=[c for c in categories if c],
				url_abstract=f"{URL_BASE}/abs/{id_arxiv}",
				url_pdf=f"{URL_BASE}/pdf/{id_arxiv}.pdf",
				date_published=_text(entry.find("atom:published", _NS)) or None,
				date_updated=_text(entry.find("atom:updated", _NS)) or None,
				primary_category=primary.get("term") or None if primary is not None else None,
				comment=_text(entry.find("arxiv:comment", _NS)) or None,
				journal_ref=_text(entry.find("arxiv:journal_ref", _NS)) or None,
				doi=_text(entry.find("arxiv:doi", _NS)) or None,
				version=int(version.group()[1:]) if version else None,
			)
		)
	return papers, total


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


_BIBTEX_ESCAPES = str.maketrans({
	"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&",
	"%": r"\%", "_": r"\_", "$": r"\$", "#": r"\#",
	"~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
})


def _bibtex_text(value: str) -> str:
	depth = 0
	for char in value:
		if char == "{":
			depth += 1
		elif char == "}":
			depth -= 1
		if depth < 0:
			break
	escapes = _BIBTEX_ESCAPES
	if depth:
		# BibTeX counts even escaped braces; retain balanced output, neutralize unbalanced input.
		escapes = escapes | str.maketrans({"{": r"\textbraceleft{}", "}": r"\textbraceright{}"})
	return value.translate(escapes)


def _bibtex_author(name: str) -> str:
	return re.sub(r"(?<!\S)and(?!\S)", lambda m: "{" + m[0] + "}", _bibtex_text(name), flags=re.IGNORECASE)


async def export_bibtex(ids: list[str]) -> BibtexExport:
	"""Export UTF-8 BibTeX from API metadata for 1–50 IDs/URLs, never generated text.

	Versions are deduplicated and use latest metadata. Keys are arxiv:<base ID>.
	The unparsed journal reference is preserved in note; missing IDs are explicit.
	"""
	from .server import MAX_PAGE_SIZE, _VERSION_RE, extract_paper_id

	if not 1 <= len(ids) <= MAX_PAGE_SIZE:
		raise ValueError(f"Supply 1–{MAX_PAGE_SIZE} IDs per batch.")
	canonical = []
	for raw in ids:
		id_arxiv = extract_paper_id(raw)
		if not id_arxiv:
			raise ValueError(f"Could not extract arXiv ID from: {raw}")
		canonical.append(_VERSION_RE.sub("", id_arxiv))
	result = await get_papers(list(dict.fromkeys(canonical)))
	entries = []
	for paper in result.papers:
		fields = {
			"title": _bibtex_text(paper.title),
			"author": " and ".join(_bibtex_author(a) for a in paper.authors),
			"year": (paper.date_published or "")[:4],
			"eprint": _bibtex_text(paper.id_arxiv),
			"archivePrefix": "arXiv",
			"primaryClass": _bibtex_text(paper.primary_category or ""),
			"doi": _bibtex_text(paper.doi or ""),
			"note": _bibtex_text(paper.journal_ref or ""),
			"url": _bibtex_text(paper.url_abstract),
		}
		body = ",\n".join(f"  {key} = {{{value}}}" for key, value in fields.items() if value)
		entries.append(f"@misc{{arxiv:{paper.id_arxiv},\n{body}\n}}")
	return BibtexExport(bibtex="\n\n".join(entries), missing_ids=result.missing_ids)

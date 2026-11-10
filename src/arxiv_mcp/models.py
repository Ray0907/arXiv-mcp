"""Data models for arXiv MCP server."""

from typing import Optional
from pydantic import BaseModel, Field, model_validator


class Paper(BaseModel):
	"""Represents an arXiv paper."""

	id_arxiv: str = Field(description="arXiv paper ID (e.g., '2301.00001')")
	title: str = Field(description="Paper title")
	abstract: str = Field(description="Paper abstract")
	authors: list[str] = Field(default_factory=list, description="List of authors")
	categories: list[str] = Field(default_factory=list, description="arXiv categories")
	url_abstract: str = Field(description="URL to the abstract page")
	url_pdf: str = Field(description="URL to the PDF")
	date_published: Optional[str] = Field(default=None, description="Publication date")
	date_updated: Optional[str] = Field(default=None, description="Last updated date")
	primary_category: Optional[str] = Field(default=None, exclude_if=lambda v: v is None, description="Primary arXiv category")
	comment: Optional[str] = Field(default=None, exclude_if=lambda v: v is None, description="Author comment")
	journal_ref: Optional[str] = Field(default=None, exclude_if=lambda v: v is None, description="Journal reference as supplied by arXiv")
	doi: Optional[str] = Field(default=None, exclude_if=lambda v: v is None, description="DOI")
	version: Optional[int] = Field(default=None, exclude_if=lambda v: v is None, description="Version number from the feed ID")


class PaperBatch(BaseModel):
	"""Batch metadata with explicit IDs absent from the API response."""

	papers: list[Paper]
	missing_ids: list[str]


class BibtexExport(BaseModel):
	"""Metadata-only citations and IDs for which no citation could be made."""

	bibtex: str
	missing_ids: list[str]


class SearchResult(BaseModel):
	"""Search result containing papers and metadata."""

	query: str = Field(description="The search query used")
	total_results: int = Field(description="Total number of results found")
	papers: list[Paper] = Field(description="List of papers")
	page: int = Field(default=1, description="Current page number")
	page_size: int = Field(default=25, description="Number of results per page")
	has_more: bool = Field(default=False, description="Whether more results exist")
	next_page: Optional[int] = Field(
		default=None, description="Next page number if has_more is True"
	)

	@model_validator(mode="after")
	def compute_pagination(self) -> "SearchResult":
		end = self.page * self.page_size
		self.has_more = self.total_results > end
		self.next_page = self.page + 1 if self.has_more else None
		return self


class RecentPapers(BaseModel):
	"""Recent papers from a specific arXiv category."""

	category: str = Field(description="Category code (e.g., 'cs.AI')")
	category_name: str = Field(description="Full category name")
	count: int = Field(description="Number of papers returned")
	papers: list[Paper] = Field(description="List of recent papers")
	total_results: int = Field(default=0, description="Total matches in the category/date window")
	has_more: bool = Field(default=False, description="Whether the count limit omitted matching papers")


class RelatedPaper(BaseModel):
	"""Compact Semantic Scholar metadata; neighbors need not have an arXiv ID."""

	title: str
	id_arxiv: Optional[str] = None
	year: Optional[int] = None
	authors: list[str] = Field(default_factory=list)


class RelatedPapers(BaseModel):
	"""A bounded graph sample, not an exhaustive bibliography or citation count."""

	id_arxiv: str
	papers: list[RelatedPaper]
	has_more: bool = False


class Category(BaseModel):
	"""arXiv category information."""

	code: str = Field(description="Category code (e.g., 'cs.AI')")
	name: str = Field(description="Full category name")
	group: str = Field(description="Category group (e.g., 'Computer Science')")


# Common arXiv categories
ARXIV_CATEGORIES: dict[str, str] = {
	# Computer Science
	"cs.AI": "Artificial Intelligence",
	"cs.CL": "Computation and Language",
	"cs.CV": "Computer Vision and Pattern Recognition",
	"cs.LG": "Machine Learning",
	"cs.NE": "Neural and Evolutionary Computing",
	"cs.RO": "Robotics",
	"cs.SE": "Software Engineering",
	"cs.DS": "Data Structures and Algorithms",
	"cs.DB": "Databases",
	"cs.DC": "Distributed, Parallel, and Cluster Computing",
	"cs.CR": "Cryptography and Security",
	"cs.HC": "Human-Computer Interaction",
	"cs.IR": "Information Retrieval",
	"cs.IT": "Information Theory",
	"cs.MA": "Multiagent Systems",
	"cs.PL": "Programming Languages",
	# Statistics
	"stat.ML": "Machine Learning (Statistics)",
	"stat.TH": "Statistics Theory",
	"stat.ME": "Methodology",
	# Mathematics
	"math.OC": "Optimization and Control",
	"math.ST": "Statistics Theory",
	"math.PR": "Probability",
	"math.NA": "Numerical Analysis",
	# Physics
	"quant-ph": "Quantum Physics",
	"cond-mat": "Condensed Matter",
	"hep-th": "High Energy Physics - Theory",
	# Electrical Engineering
	"eess.SP": "Signal Processing",
	"eess.IV": "Image and Video Processing",
	"eess.AS": "Audio and Speech Processing",
	# Quantitative Biology
	"q-bio.NC": "Neurons and Cognition",
	"q-bio.QM": "Quantitative Methods",
	# Quantitative Finance
	"q-fin.ST": "Statistical Finance",
	"q-fin.CP": "Computational Finance",
}

# sort_by value -> (API sortBy, API sortOrder)
SORT_OPTIONS: dict[str, tuple[str, str]] = {
	"relevance": ("relevance", "descending"),
	"date_desc": ("submittedDate", "descending"),
	"date_asc": ("submittedDate", "ascending"),
	"updated_desc": ("lastUpdatedDate", "descending"),
	"updated_asc": ("lastUpdatedDate", "ascending"),
}

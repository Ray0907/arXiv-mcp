"""Data models for arXiv MCP server."""

from typing import Optional
from pydantic import BaseModel, Field


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


class SearchResult(BaseModel):
	"""Search result containing papers and metadata."""

	query: str = Field(description="The search query used")
	total_results: int = Field(description="Total number of results found")
	papers: list[Paper] = Field(description="List of papers")
	page: int = Field(default=1, description="Current page number")
	page_size: int = Field(default=25, description="Number of results per page")


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

SORT_OPTIONS: dict[str, str] = {
	"relevance": "",
	"date_desc": "-announced_date_first",
	"date_asc": "announced_date_first",
	"submissions_desc": "-submittedDate",
	"submissions_asc": "submittedDate",
}

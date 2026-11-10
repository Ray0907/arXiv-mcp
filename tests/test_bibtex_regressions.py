"""Citation edge cases using synthetic Atom data only."""

import pytest

import arxiv_mcp.server as server
from tests.test_server import _entry, _feed, atom_api, no_rate_limit  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authors, expected",
    [
        (("Research and Development Collaboration",), "Research {and} Development Collaboration"),
        (("Research AND Development Collaboration", "Alice Example"), "Research {AND} Development Collaboration and Alice Example"),
        (("Alice Example", "Bob Sample"), "Alice Example and Bob Sample"),
        (("Andra Example",), "Andra Example"),
    ],
)
async def test_bibtex_preserves_api_author_boundaries(atom_api, authors, expected):
    atom_api.body = _feed(_entry(authors=authors))
    result = await server.export_bibtex(["2401.00001"])
    assert f"author = {{{expected}}}" in result.bibtex


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "brace, escaped",
    [("{", r"\textbraceleft{}"), ("}", r"\textbraceright{}")],
)
async def test_bibtex_unmatched_braces_are_group_neutral(atom_api, brace, escaped):
    value = f"Unmatched {brace} brace"
    atom_api.body = _feed(_entry(title=value, authors=(value,)).replace(
        "</entry>", f"<arxiv:journal_ref>{value}</arxiv:journal_ref></entry>",
    ))
    result = await server.export_bibtex(["2401.00001"])
    for field in ("title", "author", "note"):
        assert f"{field} = {{Unmatched {escaped} brace}}" in result.bibtex

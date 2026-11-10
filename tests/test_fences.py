"""Synthetic Markdown fence regressions."""

import pytest

from arxiv_mcp.reading import _select_section, _split_sections


@pytest.mark.parametrize("fence", ["~~~", "```"])
def test_closing_fence_requires_only_trailing_whitespace(fence):
    text = f"{fence}text\n{fence}not-a-close\n# Fake\n{fence} \t\n# Results\nBody"
    spans = _split_sections(text)
    assert [title for title, _, _ in spans] == ["Results"]
    assert _select_section(text, spans, "Results") == "# Results\nBody"

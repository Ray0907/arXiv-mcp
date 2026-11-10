"""Bounded views over the shared full-text cache; no second content fetch path."""

import re
from typing import Optional

CHUNK_SIZE = 10000
_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _split_sections(text: str) -> list[tuple[str, int, int]]:
    """Return Markdown heading spans, including each heading's subsections."""
    headings = []
    offset, previous, fence = 0, None, ""
    # shortcut: unmarked PDF headings cannot be inferred reliably; use chunk:N instead.
    for line in text.splitlines(keepends=True):
        fence_match = _FENCE.match(line)
        if fence_match:
            token = fence_match.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[fence_match.end():].strip():
                fence = ""
            previous = None
        elif not fence:
            atx = _ATX.match(line)
            underline = _SETEXT.match(line)
            if atx:
                title = re.sub(r"[ \t]+#+[ \t]*$", "", atx.group(2)).strip()
                headings.append((title, offset, len(atx.group(1))))
                previous = None
            elif underline and previous:
                title, start = previous
                headings.append((title.strip(), start, 1 if underline.group(1)[0] == "=" else 2))
                previous = None
            else:
                previous = (line, offset) if line.strip() else None
        offset += len(line)

    ends = [len(text)] * len(headings)
    stack = []
    for index, (_, start, level) in enumerate(headings):
        while stack and headings[stack[-1]][2] >= level:
            ends[stack.pop()] = start
        stack.append(index)
    return [(title, start, ends[i]) for i, (title, start, _) in enumerate(headings)]


def _select_section(text: str, spans: list[tuple[str, int, int]], section: str) -> str:
    key = section.strip().casefold()
    indexed = re.fullmatch(r"(section|chunk):(\d+)", key)
    if indexed:
        kind, number = indexed.groups()
        index = int(number) - 1
        if kind == "chunk":
            if not 0 <= index < max(1, (len(text) + CHUNK_SIZE - 1) // CHUNK_SIZE):
                raise ValueError("No such chunk; use section=None for the outline.")
            return text[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
        if not 0 <= index < len(spans):
            raise ValueError("No such section; use section=None for the outline.")
        _, start, end = spans[index]
        return text[start:end]
    exact = [span for span in spans if span[0].casefold() == key]
    matches = exact or [span for span in spans if key and key in span[0].casefold()]
    if len(matches) > 1:
        raise ValueError("Ambiguous section; use section:N from the outline.")
    if not matches:
        raise ValueError("No matching section; use section=None for the outline or chunk:N.")
    _, start, end = matches[0]
    return text[start:end]


def _bounded(text: str, max_chars: int, offset: int) -> str:
    if offset > len(text):
        raise ValueError(f"offset exceeds this view's length ({len(text)} characters).")
    if len(text) - offset <= max_chars:
        return text[offset:]

    def marker(next_offset: int) -> str:
        return ("\n\n[Truncated; call read_paper with the same id_or_url, section and max_chars, "
                f"offset={next_offset}.]")

    # Reserve using the largest possible offset so digit changes cannot exceed the cap.
    end = offset + max_chars - len(marker(offset + max_chars))
    return text[offset:end] + marker(end)


async def read_paper(
    id_or_url: str, section: Optional[str] = None, max_chars: int = 12000, offset: int = 0,
) -> str:
    """Read an outline plus API abstract by default, or select a Markdown section.

    section matches a heading (case-insensitive, unique partial match), section:N,
    or chunk:N (1-based 10,000-character slices, even without useful headings).
    max_chars includes the continuation marker and must be at least 256. To
    continue a truncated view, keep the same arguments and use its offset value.
    Full text shares get_content's cache; only the outline needs API metadata.
    """
    from .server import _content_id, get_paper, paper_content

    if max_chars < 256:
        raise ValueError("max_chars must be at least 256 to fit a continuation marker.")
    if offset < 0:
        raise ValueError("offset must be nonnegative.")
    id_arxiv = _content_id(id_or_url)
    text = await paper_content(id_arxiv)
    spans = _split_sections(text)
    if section is None:
        paper = await get_paper(id_arxiv)
        outline = "\n".join(f"- section:{i}: {title}" for i, (title, _, _) in enumerate(spans, 1))
        chunks = max(1, (len(text) + CHUNK_SIZE - 1) // CHUNK_SIZE)
        text = (f"# Outline\n{outline or 'No Markdown headings found.'}\n"
                f"Chunks: chunk:1 through chunk:{chunks} ({CHUNK_SIZE} characters each).\n\n"
                f"# Abstract\n{paper.abstract}")
    else:
        text = _select_section(text, spans, section)
    return _bounded(text, max_chars, offset)

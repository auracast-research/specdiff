"""Extract a version published as PDF (Core 5.3 and older).

The PDF's outline lists every Volume, Part and numbered section with the page it starts
on. The text comes from PyMuPDF, block by block, without the running header and footer.
Body text is set in Arial 12; tables, their titles and figure titles in Arial 10. Text
inside figures is set in other fonts (ArialMT, ArialNarrow, ...) and often garbled, so it
is dropped: the HTML has nothing for it either, figures are images there.

Tables are rebuilt from the rectangles the PDF draws for their cells: rows between their
horizontal edges, cells between their vertical ones, cells joined by " | " as the HTML
extractor joins them."""

import itertools
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from specdiff import sources
from specdiff.model import Block, ExtractError, Part, Section, Spec
from specdiff.text import clean, clean_lines, key

# FrameMaker's fonts. Figures drawn in other tools bring their own (ArialMT, ...).
_TEXT_FONT = re.compile(
    r"^(Arial|CourierNew|Courier|LucidaConsole|TimesNewRoman|Symbol|Wingdings)"
    r"(,(Bold|Italic|BoldItalic))?$"
)
_MONO = ("Courier", "Lucida")
HEADER_BOTTOM = 80  # the running header ends above this y; the footer starts below:
FOOTER_TOP = 785
BODY_SIZE = 11  # body text is 12 pt, tables 10 pt
TITLE_SIZE = 13.5  # the title page and abstract of a Part (headings are found by their text)
# bullets, and the Symbol and Wingdings glyphs some lists use
_BULLETS = {"\u2022", "\u25e6", "\u25aa", "\u25a0", "\u2013", "-", "o"} | {
    "\uf0b7",
    "\uf0a7",
    "\uf0d8",
}
_LIST_NUMBER = re.compile(r"^(\(?(\d{1,2}|[a-z]|[ivx]{1,4})[.)])$")
# a bullet or list number set in the same span as the item's text: "a) The ..."
_INLINE_MARKER = re.compile(
    r"^([\u2022\u25e6\u25aa\u25a0\u2013]|\(?(?:\d{1,2}|[a-z]|[ivx]{1,4})\))\s+"
)
_CONTINUED = re.compile(r"\s*\((Sheet \d+ of \d+|[Cc]ontinued)\)\s*$")
_CAPTION = re.compile(r"^(Table|Figure|Equation)\s+[A-Z]?\d+(\.\d+)*\s*[:.]")
_VOLUME = re.compile(r"^Vol(?:ume)?\s*(\d+)\s*:\s*(.*)$")
_PART = re.compile(r"^Part\s+([A-Z])\s*:\s*(.*)$")
_SECTION = re.compile(r"^((?:Appendix\s+)?[A-Z]?\d*(?:\.\d+)*)\s+(.*)$")
_NUMBERED = re.compile(r"^(\d+(\.\d+)*|[A-Z](\.\d+)+|Appendix [A-Z])$")
_TERMINAL = re.compile(r"[.:;!?][\"'\u201d\u2019)\]]*$")
# Parts left out, as in the HTML: the master table of contents and the acknowledgments
SKIPPED_PARTS = {(0, "A"), (0, "C")}
UNUSED = "no longer used"


@dataclass
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    mono: bool
    marker: str = ""  # a bullet or list number, set apart from the text


@dataclass
class Chunk:
    """A PyMuPDF text block, without the text of figures."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    lines: list[Line]

    @property
    def size(self) -> float:
        weights = Counter()
        for line in self.lines:
            weights[round(line.size)] += len(line.text)
        return weights.most_common(1)[0][0]

    @property
    def mono(self) -> bool:
        return all(line.mono for line in self.lines)

    @property
    def first_text(self) -> str:
        return self.lines[0].text


@dataclass
class Entry:
    """An entry of the outline: a Volume, a Part or a section."""

    level: int
    title: str
    page: int  # 0-based
    kind: str  # "vol", "part", "section", "skip"
    number: str = ""
    name: str = ""
    chunks: list[Chunk] = field(default_factory=list)


class Context:
    """The document, the words it writes whole, and the rules drawn on each page."""

    def __init__(self, doc: pymupdf.Document, chunks: list[Chunk]) -> None:
        self.doc = doc
        self.vocabulary = _vocabulary(chunks)
        self._rules: dict[int, tuple[list, list]] = {}

    def rules(self, page: int) -> tuple[list[tuple[float, float, float]], list]:
        if page not in self._rules:
            self._rules[page] = _page_rules(self.doc[page])
        return self._rules[page]


def extract(label: str, *, refresh: bool = False) -> Spec:
    path = sources.fetch_pdf(label, refresh=refresh)
    doc = pymupdf.open(path)
    url = sources.pdf_url(label)
    entries = _outline(doc)
    chunks = [chunk for number in range(doc.page_count) for chunk in _chunks(doc[number], number)]
    context = Context(doc, chunks)
    _assign(entries, chunks)

    spec = Spec(version=label, format="pdf", source=url)
    vol = None
    part: Part | None = None
    skipping = False
    for entry in entries:
        if entry.kind == "vol":
            vol = int(entry.number)
            part = None
        elif entry.kind == "part" and vol is not None:
            skipping = (vol, entry.number) in SKIPPED_PARTS or UNUSED in entry.name.lower()
            part = None
            if not skipping:
                part = Part(vol, entry.number, entry.name, url)
                spec.parts.append(part)
                part.sections.append(
                    Section("", entry.name, 0, _blocks(entry, context), page=entry.page + 1)
                )
        elif entry.kind == "section" and part is not None and not skipping:
            depth = 1 if entry.number.startswith("Appendix") else entry.number.count(".") + 1
            part.sections.append(
                Section(
                    entry.number,
                    entry.name,
                    depth,
                    _blocks(entry, context),
                    page=entry.page + 1,
                )
            )
    for part in spec.parts:
        print(
            f"Core {label}: Vol {part.vol}, Part {part.letter}: {len(part.sections)} sections",
            file=sys.stderr,
        )
    if not spec.parts:
        msg = f"Core {label}: no Parts in the PDF outline"
        raise ExtractError(msg)
    return spec


def _outline(doc: pymupdf.Document) -> list[Entry]:
    entries = []
    for level, raw_title, page, *_ in doc.get_toc(simple=False):
        title = clean(raw_title)
        entry = Entry(level, title, page - 1, "skip")
        if level == 1 and (match := _VOLUME.match(title)):
            entry.kind, entry.number, entry.name = "vol", match[1], match[2]
        elif level == 2 and (match := _PART.match(title)):
            entry.kind, entry.number, entry.name = "part", match[1], match[2]
        elif level >= 3 and (match := _SECTION.match(title)) and _NUMBERED.match(match[1]):
            entry.kind, entry.number, entry.name = "section", match[1], match[2]
        entries.append(entry)
    if not any(entry.kind == "section" for entry in entries):
        msg = "the PDF outline has no numbered sections"
        raise ExtractError(msg)
    return entries


def _chunks(page: pymupdf.Page, number: int) -> list[Chunk]:
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
    chunks = []
    for block in page.get_text("dict", flags=flags)["blocks"]:
        lines = []
        for raw in block.get("lines", []):
            spans = [s for s in raw["spans"] if _TEXT_FONT.match(s["font"]) and s["text"].strip()]
            if not spans:
                continue
            y0 = min(s["bbox"][1] for s in spans)
            if y0 < HEADER_BOTTOM or y0 >= FOOTER_TOP:
                continue
            line = _line(number, spans)
            if line.text or line.marker:
                lines.append(line)
        if lines:
            chunks.append(
                Chunk(
                    number,
                    min(line.x0 for line in lines),
                    min(line.y0 for line in lines),
                    max(line.x1 for line in lines),
                    max(line.y1 for line in lines),
                    lines,
                )
            )
    chunks.sort(key=lambda chunk: (round(chunk.y0), chunk.x0))
    return chunks


def _line(page: int, spans: list[dict]) -> Line:
    marker = ""
    first = spans[0]["text"].strip()
    if len(spans) > 1 and (first in _BULLETS or _LIST_NUMBER.match(first)):
        gap = spans[1]["bbox"][0] - spans[0]["bbox"][2]
        if gap > 3:
            marker = first
            spans = spans[1:]
    text = clean("".join(s["text"] for s in spans))
    sizes = Counter()
    for span in spans:
        sizes[round(span["size"])] += len(span["text"])
    return Line(
        page=page,
        x0=min(s["bbox"][0] for s in spans),
        y0=min(s["bbox"][1] for s in spans),
        x1=max(s["bbox"][2] for s in spans),
        y1=max(s["bbox"][3] for s in spans),
        text=text,
        size=sizes.most_common(1)[0][0],
        mono=all(s["font"].startswith(_MONO) for s in spans),
        marker=marker,
    )


def _vocabulary(chunks: list[Chunk]) -> set[str]:
    """Words the PDF writes whole somewhere, to tell a line-end hyphen that splits a word
    ("Authenti-" "cated") from one that belongs to it ("man-in-the-" "middle")."""
    words = set()
    for chunk in chunks:
        for line in chunk.lines:
            words.update(w.lower() for w in re.findall(r"\w+(?:-\w+)*", line.text))
    return words


def _assign(entries: list[Entry], chunks: list[Chunk]) -> None:
    """Hand each chunk to the outline entry it follows. An entry starts at its heading,
    found on the page the outline gives (or the next); the heading itself is dropped."""
    starts: list[tuple[int, Entry]] = []
    cursor = 0
    for entry in entries:
        found = None
        for index in range(cursor, len(chunks)):
            chunk = chunks[index]
            if chunk.page > entry.page + 1:
                break
            if chunk.page >= entry.page and _is_heading(chunk, entry):
                found = index
                break
        if found is None:
            # no heading found (a title the outline words differently): start at the page
            found = next(
                (i for i in range(cursor, len(chunks)) if chunks[i].page >= entry.page),
                len(chunks),
            )
            starts.append((found, entry))
            cursor = found
        else:
            starts.append((found, entry))
            cursor = found + 1
    for position, (start, entry) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(chunks)
        own = chunks[start:end]
        if own and _is_heading(own[0], entry):
            own = own[1:]
        entry.chunks = own


def _is_heading(chunk: Chunk, entry: Entry) -> bool:
    text = key(" ".join(line.text for line in chunk.lines[:3]))
    if entry.kind == "section":
        expected = key(f"{entry.number} {entry.name}")
        number = key(entry.number)
        return text.startswith(number) and (
            text[:40] == expected[:40] or expected.startswith(text) or text.startswith(expected)
        )
    if entry.kind == "part":
        return text.startswith(key(f"Part {entry.number}"))
    if entry.kind == "vol":
        return text.startswith(key(f"Volume {entry.number}")) or text.startswith(
            key(f"Vol {entry.number}")
        )
    return key(entry.title)[:30] == text[:30]


# Blocks of a section


def _blocks(entry: Entry, context: Context) -> list[Block]:
    vocabulary = context.vocabulary
    blocks: list[Block] = []
    region: list[Chunk] = []  # small text: a table, or a figure if a figure title follows
    last_page = -1
    previous_mono = False

    def flush_region() -> None:
        if region:
            blocks.extend(_table_rows(region, context))
            region.clear()

    for chunk in entry.chunks:
        first_body_on_page = chunk.page != last_page
        last_page = chunk.page
        text = _join(chunk.lines, vocabulary)
        if not text:
            continue
        caption = _CAPTION.match(text)
        if caption and chunk.size <= BODY_SIZE:
            text = _CONTINUED.sub("", text)
            if caption[1] == "Figure":
                region.clear()
                blocks.append(Block("figure", text))
            else:
                flush_region()
                # a table over several pages repeats its title under each: keep the last
                blocks[:] = [b for b in blocks if not (b.kind == "caption" and b.text == text)]
                blocks.append(Block("caption", text))
            continue
        if chunk.mono:
            flush_region()
            lines = clean_lines("\n".join(line.text for line in chunk.lines))
            if blocks and blocks[-1].kind == "pre" and previous_mono:
                blocks[-1].text += "\n" + lines
            else:
                blocks.append(Block("pre", lines))
            previous_mono = True
            continue
        previous_mono = False
        if chunk.size < BODY_SIZE:
            region.append(chunk)
            continue
        if chunk.size >= TITLE_SIZE:
            continue
        flush_region()
        cells = _cells_on_one_line(chunk, vocabulary)
        if cells:
            blocks.append(Block("row", " | ".join(cells)))
            continue
        marker = chunk.lines[0].marker
        if not marker and (inline := _INLINE_MARKER.match(text)):
            marker = inline[1]
            text = text[inline.end() :]
        previous = blocks[-1] if blocks else None
        if (
            previous is not None
            and first_body_on_page
            and not marker
            and previous.kind in ("p", "li", "note")
            and not _TERMINAL.search(previous.text)
        ):
            previous.text = _join_text(previous.text, text, vocabulary)
            continue
        if marker:
            blocks.append(Block("li", text))
        elif text.startswith("Note:"):
            blocks.append(Block("note", text))
        else:
            blocks.append(Block("p", text))
    flush_region()
    return blocks


def _cells_on_one_line(chunk: Chunk, vocabulary: set[str]) -> list[str]:
    """A parameter heading, "Connection_Handle:" on the left and "Size: 2 octets" on the
    right of the same line: two cells, as in the HTML."""
    if len(chunk.lines) < 2:
        return []
    baseline = chunk.lines[0].y0
    first = [line for line in chunk.lines if abs(line.y0 - baseline) < 2]
    if len(first) < 2:
        return []
    first.sort(key=lambda line: line.x0)
    if first[1].x0 - first[0].x1 < 30:
        return []
    # lines below belong to the cell they sit under
    cells: list[list[Line]] = [[line] for line in first]
    for line in chunk.lines:
        if line in first:
            continue
        column = max(i for i, cell in enumerate(cells) if cell[0].x0 <= line.x0 + 2 or i == 0)
        cells[column].append(line)
    return [_join(cell, vocabulary) for cell in cells]


def _table_rows(region: list[Chunk], context: Context) -> list[Block]:
    """Rows of a table, page by page, from the rectangles of its cells; without them, one
    row per line."""
    pages: dict[int, list[Line]] = {}
    for chunk in region:
        pages.setdefault(chunk.page, []).extend(chunk.lines)
    return [row for page, lines in pages.items() for row in _rows_on_page(page, lines, context)]


def _rows_on_page(page: int, lines: list[Line], context: Context) -> list[Block]:
    """Lines in the same column belong to one cell while they follow each other closely
    with no rule between them; cells whose lines overlap vertically make one row (cells are
    centred vertically, and few tables rule off every row)."""
    x0 = min(line.x0 for line in lines) - 8
    x1 = max(line.x1 for line in lines) + 8
    y0 = min(line.y0 for line in lines) - 30
    y1 = max(line.y1 for line in lines) + 8
    horizontal, vertical = context.rules(page)
    columns = _merge(
        sorted(x for x, a, b in vertical if x0 - 2 <= x <= x1 and a < y1 and b > y0 + 25)
    )
    if len(columns) < 2:
        columns = _merge(sorted(line.x0 - 2 for line in lines), tolerance=8)
    rules = [(y, a, b) for y, a, b in horizontal if y0 <= y <= y1 and a < x1 and b > x0]

    def column(line: Line) -> int:
        return sum(edge <= line.x0 + 2 for edge in columns)

    def ruled_between(upper: Line, lower: Line) -> bool:
        return any(
            upper.y1 - 2 <= y <= lower.y0 + 2 and a <= lower.x0 + 2 and b >= lower.x0 + 2
            for y, a, b in rules
        )

    parent = list(range(len(lines)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    # the paragraphs of a cell are further apart than its lines; in a table that rules off
    # its rows they stay together
    gap = 8 if len(_merge(sorted(y for y, _, _ in rules))) > 2 else 3
    order = sorted(range(len(lines)), key=lambda i: (column(lines[i]), lines[i].y0, lines[i].x0))
    for i, j in itertools.pairwise(order):
        a, b = lines[i], lines[j]
        if column(a) == column(b) and b.y0 - a.y1 < gap and not ruled_between(a, b):
            union(i, j)
    for i, a in enumerate(lines):
        for j in range(i + 1, len(lines)):
            b = lines[j]
            if column(a) != column(b) and min(a.y1, b.y1) - max(a.y0, b.y0) > 1:
                union(i, j)

    groups: dict[int, list[Line]] = {}
    for i, line in enumerate(lines):
        groups.setdefault(find(i), []).append(line)
    rows = []
    for group in sorted(groups.values(), key=lambda g: min(line.y0 for line in g)):
        cells: dict[int, list[Line]] = {}
        for line in group:
            cells.setdefault(column(line), []).append(line)
        texts = [
            _join(sorted(cell, key=lambda ln: (round(ln.y0), ln.x0)), context.vocabulary)
            for _, cell in sorted(cells.items())
        ]
        if any(texts):
            rows.append(Block("row", " | ".join(text for text in texts if text)))
    return rows


def _merge(values: list[float], tolerance: float = 2.5) -> list[float]:
    merged: list[float] = []
    for value in values:
        if not merged or value - merged[-1] > tolerance:
            merged.append(value)
    return merged


def _page_rules(page: pymupdf.Page) -> tuple[list[tuple[float, float, float]], list]:
    """Horizontal edges (y, x from, x to) and vertical edges (x, y from, y to) of the
    rectangles and lines drawn on a page."""
    horizontal = []
    vertical = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "re":
                rect = item[1]
                if rect.width > 15:
                    horizontal += [(rect.y0, rect.x0, rect.x1), (rect.y1, rect.x0, rect.x1)]
                if rect.height > 5:
                    vertical += [(rect.x0, rect.y0, rect.y1), (rect.x1, rect.y0, rect.y1)]
            elif item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) < 1 and abs(a.x - b.x) > 15:
                    horizontal.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) < 1 and abs(a.y - b.y) > 5:
                    vertical.append((a.x, min(a.y, b.y), max(a.y, b.y)))
    return horizontal, vertical


def _join(lines: list[Line], vocabulary: set[str]) -> str:
    text = ""
    for line in lines:
        text = _join_text(text, line.text, vocabulary) if text else line.text
    return text


def _join_text(before: str, after: str, vocabulary: set[str]) -> str:
    """Two lines as one: a hyphen at the end of the first stays only if the word is
    hyphenated elsewhere, or not known without it; identifiers broken after "_" are
    joined without a space."""
    before = before.rstrip()
    after = after.lstrip()
    if not before or not after:
        return before + after
    if before.endswith("_-"):  # "HCI_LE_Set_-" "Scan_Enable"
        return before[:-1] + after
    if before.endswith("-") and not before.endswith("--") and after[0].islower():
        head = re.search(r"(\w+(?:-\w+)*)-$", before)
        tail = re.match(r"\w+", after)
        if head and tail:
            whole = (head[1] + tail[0]).lower()
            hyphenated = f"{head[1]}-{tail[0]}".lower()
            if whole in vocabulary and hyphenated not in vocabulary:
                return before[:-1] + after
        return before + after
    if before.endswith(("_", "/")):
        return before + after
    return f"{before} {after}"

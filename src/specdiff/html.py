"""Extract a version published as HTML (Core 5.4 and later): the index page lists the
Volumes and their Parts, one page each; a Part is DocBook output, nested <section>s with a
numbered title, paragraphs, lists, tables, figures, notes and equations."""

import re
import sys

from bs4 import BeautifulSoup, NavigableString, Tag

from specdiff import sources
from specdiff.model import CELL_SEPARATOR, LINE_SEPARATOR, Block, ExtractError, Part, Section, Spec
from specdiff.text import clean, clean_lines

_VOLUME = re.compile(r"^Volume (\d+)\.\s*(.*)$")
_PART = re.compile(r"^Part ([A-Z])\.\s*(.*)$")
_HEADING = re.compile(r"^h[1-6]$")
# Parts the diff leaves out: the consolidated table of contents repeats every other Part's
# headings, and the acknowledgments are lists of names.
SKIPPED_PARTS = {(0, "A"), (0, "C")}
UNUSED = "no longer used"


def extract(label: str, *, refresh: bool = False) -> Spec:
    index_url, index_path = sources.fetch_index(label, refresh=refresh)
    spec = Spec(version=label, format="html", source=index_url)
    for vol, letter, title, href in parts_of(index_path.read_text(encoding="utf-8")):
        if (vol, letter) in SKIPPED_PARTS or UNUSED in title.lower():
            continue
        path = sources.fetch_part(label, index_url, href, refresh=refresh)
        sections = parse_part(path.read_text(encoding="utf-8"))
        url = sources.part_url(index_url, href)
        spec.parts.append(Part(vol, letter, clean(title), url, sections))
        print(f"Core {label}: Vol {vol}, Part {letter}: {len(sections)} sections", file=sys.stderr)
    if not spec.parts:
        msg = f"Core {label}: no Parts found in the index"
        raise ExtractError(msg)
    return spec


def parts_of(index_html: str) -> list[tuple[int, str, str, str]]:
    """(volume, part letter, title, href) of each Part the index links to, in order."""
    soup = BeautifulSoup(index_html, "lxml")
    parts: list[tuple[int, str, str, str]] = []
    seen: set[str] = set()
    vol = None
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if "#" in href or not href.endswith(".html"):
            continue
        label = clean(link.get_text(" "))
        if volume := _VOLUME.match(label):
            vol = int(volume[1])
        elif (part := _PART.match(label)) and vol is not None and href not in seen:
            seen.add(href)
            parts.append((vol, part[1], part[2], href))
    return parts


def parse_part(html: str) -> list[Section]:
    """The sections of a Part page in document order, the Part's own text first."""
    soup = BeautifulSoup(html, "lxml")
    root = next((s for s in soup.find_all("section") if _number(s).startswith("Part ")), None)
    if root is None:
        msg = "no <section> titled 'Part X'"
        raise ExtractError(msg)
    sections = []
    for element in [root, *root.find_all("section")]:
        number = _number(element)
        heading = _heading(element)
        if heading is None:
            continue
        title_tag = heading.find(class_="formal-title")
        title = clean(title_tag.get_text()) if title_tag else ""
        own = "" if element is root else number
        anchor = element.get("id")
        sections.append(
            Section(
                number=own,
                title=title,
                depth=0 if element is root else own.count(".") + 1,
                blocks=list(_own_blocks(element)),
                anchor=anchor if isinstance(anchor, str) else "",
            )
        )
    return sections


def _heading(section: Tag) -> Tag | None:
    heading = section.find(_HEADING)
    if heading is None or heading.find_parent("section") is not section:
        return None
    return heading


def _number(section: Tag) -> str:
    heading = _heading(section)
    number = heading.find(class_="formal-number") if heading else None
    return clean(number.get_text()) if number else ""


def _own_blocks(section: Tag):
    for child in section.children:
        if isinstance(child, Tag) and child.name != "section":
            yield from blocks(child)


def blocks(element: Tag):
    """The blocks of text in `element`."""
    classes = set(element.get_attribute_list("class"))
    name = element.name
    # footnotes: the PDF sets them at the foot of the page, apart from the text
    if name in ("br", "hr", "img", "script", "style") or classes & {"titlepage", "footnotes"}:
        return
    if name == "p":
        if text := inline_text(element):
            yield Block("p", text)
    elif name in ("ul", "ol"):
        for item in element.find_all("li", recursive=False):
            yield from _list_item(item)
    elif "note" in classes:
        text = " ".join(inline_text(p) for p in element.find_all("p"))
        if text:
            yield Block("note", text)
    elif name == "table":
        yield from _rows(element)
    elif classes & {"table-title", "figure-title", "equation-title"}:
        if (text := inline_text(element)) and "figure-title" not in classes:
            yield Block("caption", text)
    elif "figure" in classes or _is_figure(element):
        title = element.find(class_="figure-title")
        if title is not None and (text := inline_text(title)):
            yield Block("figure", text)
    elif "literallayout" in classes or name == "pre":
        if text := preformatted_text(element):
            yield Block("pre", text)
    elif "equation" in classes:
        contents = element.find(class_="equation-contents") or element
        if text := inline_text(contents):
            yield Block("eq", text)
    elif name == "dl":
        for term in element.find_all("dt", recursive=False):
            definition = term.find_next_sibling("dd")
            text = clean(f"{inline_text(term)} {_joined(definition) if definition else ''}")
            if text:
                yield Block("p", text)
    else:
        for child in element.children:
            if isinstance(child, Tag):
                yield from blocks(child)
            elif isinstance(child, NavigableString) and (text := clean(str(child))):
                yield Block("p", text)


def _is_figure(element: Tag) -> bool:
    """A figure without the "figure" class (a few in Vol 6, Part B have class="")."""
    anchor = element.get("id")
    return isinstance(anchor, str) and "_figure-" in anchor


def _list_item(item: Tag):
    """A list item, then the items of the lists nested in it."""
    own = []
    nested = []
    for child in item.children:
        if isinstance(child, Tag) and (child.find(["ul", "ol"]) or child.name in ("ul", "ol")):
            nested.append(child)
        elif isinstance(child, Tag):
            own.append(_joined(child))
        elif text := clean(str(child)):
            own.append(text)
    if text := clean(" ".join(own)):
        yield Block("li", text)
    for child in nested:
        yield from blocks(child)


def _rows(table: Tag):
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        # the paragraphs of a cell stay apart: "0 = unused" and "1 = used" are two lines
        cells = [
            _joined(cell, LINE_SEPARATOR) for cell in row.find_all(["th", "td"], recursive=False)
        ]
        if any(cells):
            yield Block("row", CELL_SEPARATOR.join(cells))


def _joined(element: Tag, separator: str = " ") -> str:
    """Text of an element whose paragraphs are separate (a table cell, a list item)."""
    paragraphs = element.find_all("p")
    if not paragraphs:
        return inline_text(element)
    return clean(separator.join(text for p in paragraphs if (text := inline_text(p))))


def preformatted_text(element: Tag) -> str:
    """Text whose lines matter (sample data, code), one line per line."""
    pieces = []
    for node in element.descendants:
        if isinstance(node, NavigableString):
            pieces.append(str(node))
        elif isinstance(node, Tag) and node.name in ("br", "p", "div"):
            pieces.append("\n")
    return clean_lines("".join(pieces))


def inline_text(element: Tag) -> str:
    """Text as it reads, without the space BeautifulSoup would put between inline tags
    ("b<sub>0</sub>" is "b0")."""
    return clean("".join(element.strings))

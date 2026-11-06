"""One version of the specification, whatever it was published as: Parts, their sections in
document order, and the blocks of text each section holds before its first subsection."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# What a block is. Rows are table rows, their cells joined by " | " (and the paragraphs of a
# cell by " ¶ ", where the HTML has them); a figure is its title.
BLOCK_KINDS = ("p", "li", "note", "row", "caption", "figure", "pre", "eq")
CELL_SEPARATOR = " | "
LINE_SEPARATOR = " \u00b6 "
# The two as tokens: they structure a row and are never words of the text
SEPARATORS = frozenset({"|", "\u00b6"})


@dataclass
class Block:
    kind: str
    text: str


@dataclass
class Section:
    number: str  # "2.3.5.3", "A.1"; "" for the text of the Part before its first section
    title: str
    depth: int  # 0 for the Part's own text, 1 for "2", 2 for "2.3", ...
    blocks: list[Block] = field(default_factory=list)
    anchor: str = ""  # HTML: the id of the section, stable from 5.4 on; PDF: ""
    page: int = 0  # PDF: the page the section starts on (1-based); HTML: 0


@dataclass
class Part:
    vol: int
    letter: str
    title: str
    url: str  # the Part's HTML page, or the PDF
    sections: list[Section] = field(default_factory=list)

    @property
    def key(self) -> str:
        """ "3H" for Vol 3, Part H."""
        return f"{self.vol}{self.letter}"


@dataclass
class Spec:
    version: str
    format: str  # "html" or "pdf"
    source: str  # the index page or the PDF
    parts: list[Part] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, document: dict) -> "Spec":
        parts = [
            Part(
                **{k: v for k, v in part.items() if k != "sections"},
                sections=[
                    Section(
                        **{k: v for k, v in section.items() if k != "blocks"},
                        blocks=[Block(**block) for block in section["blocks"]],
                    )
                    for section in part["sections"]
                ],
            )
            for part in document["parts"]
        ]
        return cls(
            version=document["version"],
            format=document["format"],
            source=document["source"],
            parts=parts,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Spec":
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


class ExtractError(Exception):
    """The HTML or PDF does not look the way the extractor expects."""

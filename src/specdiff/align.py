"""Line two versions up: which section of the newer one continues which section of the
older one, and, inside a pair of sections, which sentence continues which.

Sections keep their HTML id from Core 5.4 on. Across the other steps (and for sections the
SIG gave a new id) a section is matched by its number and title, then by its title alone
(it was renumbered), then by its number and a similar text (it was retitled), and last by a
similar text alone (it moved within its Part)."""

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from specdiff.model import LINE_SEPARATOR, SEPARATORS, Block, Part, Section
from specdiff.text import drop_pdf_furniture, fold, key, sentences, token_spans

PROSE = ("p", "li", "note")
# difflib's opcodes: (tag, old start, old end, new start, new end)
type Opcodes = Sequence[tuple[str, int, int, int, int]]
TITLES = ("caption", "figure")
SIMILAR_UNITS = 0.5  # two sentences this similar are one sentence, changed
SIMILAR_LEFTOVERS = 0.4  # the same, for sentences of one section that also moved
SIMILAR_SECTIONS = 0.45  # two sections whose text is this similar are one section
SIMILAR_TITLES = 0.8  # a section that keeps its number and a title this close is retitled
LEFTOVER_DISTANCE = 0.15  # what moving across the whole section costs a reworded pair
UNUSED = "no longer used"


@dataclass
class Unit:
    """A sentence of a paragraph, list item or note; a whole row, title, code or equation."""

    block: int  # its block in the section
    kind: str
    text: str
    spans: list[tuple[int, int]]  # where its tokens are in `text`
    words: list[str]  # its tokens as compared: folded

    @property
    def norm(self) -> str:
        """What two sentences are compared by: the PDF and the HTML split some tables into
        cells and lines differently, so the separators don't count."""
        return " ".join(word for word in self.words if word not in SEPARATORS)

    @property
    def content(self) -> list[str]:
        """Its words, lowercased, without punctuation: what similarity is measured on."""
        return [word.lower() for word in self.words if _WORDY.search(word)]


_WORDY = re.compile(r"[^\W_]")  # a letter or a digit
LINE = LINE_SEPARATOR.strip()


def units(blocks: list[Block], *, pdf: bool = False) -> list[Unit]:
    result = []
    for index, block in enumerate(blocks):
        text = drop_pdf_furniture(block.text) if pdf else block.text
        if block.kind in PROSE:
            pieces = sentences(text)
        elif block.kind == "pre":
            pieces = text.split("\n")
        else:
            pieces = [text]
        for piece in pieces:
            spans = token_spans(piece)
            words = [fold(piece[start:end]) for start, end in spans]
            if words:
                result.append(Unit(index, block.kind, piece, spans, words))
    return result


# Sections


def match_parts(old: list[Part], new: list[Part]) -> list[tuple[Part | None, Part | None]]:
    """Parts by Volume and letter when their titles are alike, then by title across
    Volumes (Core 5.2 moved the HCI from Vol 2, Part E to Vol 4, Part E), then by Volume and
    letter whatever their titles."""
    matched: dict[str, Part] = {}  # new key -> old Part
    used: set[str] = set()
    by_key = {part.key: part for part in old}

    def pair(new_part: Part, old_part: Part) -> None:
        matched[new_part.key] = old_part
        used.add(old_part.key)

    for part in new:
        before = by_key.get(part.key)
        if before is not None and _related_titles(before.title, part.title):
            pair(part, before)
    for part in new:
        if part.key in matched:
            continue
        candidates = [
            (difflib.SequenceMatcher(None, key(o.title), key(part.title)).ratio(), o.key)
            for o in old
            if o.key not in used and _related_titles(o.title, part.title)
        ]
        if candidates:
            pair(part, by_key[max(candidates)[1]])
    for part in new:
        before = by_key.get(part.key)
        if part.key not in matched and before is not None and before.key not in used:
            pair(part, before)
    pairs: list[tuple[Part | None, Part | None]] = [(matched.get(p.key), p) for p in new]
    return pairs + [(part, None) for part in old if part.key not in used]


def _related_titles(a: str, b: str) -> bool:
    """ "Error Codes" and "Controller Error Codes", "Link Layer Specification" and "Link Layer
    (LL) Specification"."""
    a, b = key(a), key(b)
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def match_sections(
    old: list[Section], new: list[Section], old_units: list[list[Unit]], new_units: list[list[Unit]]
) -> dict[int, tuple[int, str]]:
    """For each new section that continues an old one: the old one's index, and how it was
    found ("id", "same", "renumbered", "retitled", "moved")."""
    matches: dict[int, tuple[int, str]] = {}
    taken: set[int] = set()

    def take(new_index: int, old_index: int, how: str) -> None:
        matches[new_index] = (old_index, how)
        taken.add(old_index)

    # 1. the HTML id
    by_anchor = {s.anchor: i for i, s in enumerate(old) if s.anchor}
    for j, section in enumerate(new):
        i = by_anchor.get(section.anchor) if section.anchor else None
        if i is not None and i not in taken:
            take(j, i, "id")

    # 2. number and title; 3. title alone, when only one section has it
    def free_new() -> list[int]:
        return [j for j in range(len(new)) if j not in matches]

    by_heading: dict[tuple[str, str], list[int]] = {}
    for i, section in enumerate(old):
        by_heading.setdefault((section.number, key(section.title)), []).append(i)
    for j in free_new():
        candidates = [
            i for i in by_heading.get((new[j].number, key(new[j].title)), []) if i not in taken
        ]
        if candidates:
            take(j, candidates[0], "same")

    old_titles: dict[str, list[int]] = {}
    for i, section in enumerate(old):
        if i not in taken:
            old_titles.setdefault(key(section.title), []).append(i)
    new_titles: dict[str, list[int]] = {}
    for j in free_new():
        new_titles.setdefault(key(new[j].title), []).append(j)
    for title, js in new_titles.items():
        is_ = old_titles.get(title, [])
        if len(js) == 1 and len(is_) == 1 and title:
            take(js[0], is_[0], "renumbered")

    # 4. number and a similar text; 5. a similar text alone
    old_shingles = [_shingles(u) for u in old_units]
    new_shingles = {j: _shingles(new_units[j]) for j in free_new()}
    by_number = {s.number: i for i, s in enumerate(old) if s.number}
    for j in free_new():
        i = by_number.get(new[j].number)
        if i is None or i in taken:
            continue
        similar = _jaccard(old_shingles[i], new_shingles[j]) >= SIMILAR_SECTIONS
        both_empty = not old_shingles[i] and not new_shingles[j]
        # the SIG keeps the number of a section it drops: "[This section is no longer used]"
        emptied = UNUSED in new[j].title.lower()
        title_ratio = _title_ratio(old[i].title, new[j].title)
        if (
            similar
            or emptied
            or title_ratio >= SIMILAR_TITLES
            or (both_empty and title_ratio >= 0.6)
        ):
            take(j, i, "retitled")
    candidates = []
    for j in free_new():
        if len(new_shingles[j]) < 8:
            continue
        for i in range(len(old)):
            if i not in taken and len(old_shingles[i]) >= 8:
                score = _jaccard(old_shingles[i], new_shingles[j])
                if score >= SIMILAR_SECTIONS:
                    candidates.append((score, j, i))
    for _, j, i in sorted(candidates, reverse=True):
        if j not in matches and i not in taken:
            take(j, i, "moved")
    return matches


def match_moved(old_units: list[list[Unit]], new_units: list[list[Unit]]) -> dict[int, int]:
    """Sections left over after each Part was matched with its old self, paired across
    Parts by their text (Core 7.0 moved the MSC notation from Vol 2, Part F and Vol 6,
    Part D into Vol 1, Part E): new index -> old index, most similar first."""
    old_shingles = [_shingles(u) for u in old_units]
    new_shingles = [_shingles(u) for u in new_units]
    candidates = [
        (score, j, i)
        for j, b in enumerate(new_shingles)
        if len(b) >= 8
        for i, a in enumerate(old_shingles)
        if len(a) >= 8 and (score := _jaccard(a, b)) >= SIMILAR_SECTIONS
    ]
    pairs: dict[int, int] = {}
    taken: set[int] = set()
    for _, j, i in sorted(candidates, reverse=True):
        if j not in pairs and i not in taken:
            pairs[j] = i
            taken.add(i)
    return pairs


def _shingles(section_units: list[Unit]) -> set[str]:
    words = [w.lower() for unit in section_units for w in unit.words if w.isalnum()]
    return {" ".join(words[i : i + 3]) for i in range(max(0, len(words) - 2))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _title_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, key(a), key(b)).ratio()


# Sentences of a pair of sections


def align_units(old: list[Unit], new: list[Unit]) -> list[tuple[int | None, int | None]]:
    """Pairs (old index, new index) in reading order: both for a sentence that stayed (the
    same or changed), one None for a sentence added or removed."""
    matcher = difflib.SequenceMatcher(
        None, [u.norm for u in old], [u.norm for u in new], autojunk=False
    )
    pairs: list[tuple[int | None, int | None]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs += [(i1 + k, j1 + k) for k in range(i2 - i1)]
        else:
            pairs += _pair_similar(old, new, range(i1, i2), range(j1, j2))
    return pairs


def _pair_similar(
    old: list[Unit], new: list[Unit], old_range: range, new_range: range
) -> list[tuple[int | None, int | None]]:
    """The best order-keeping pairing of similar sentences in a changed stretch, by dynamic
    programming over their similarity; the rest added or removed."""
    a = list(old_range)
    b = list(new_range)
    if not a or not b:
        return [(i, None) for i in a] + [(None, j) for j in b]
    if len(a) * len(b) > 40_000:  # a rewritten section: pair only near-identical sentences
        return _pair_greedy(old, new, a, b)
    bags = {("a", i): set(old[i].words) for i in a} | {("b", j): set(new[j].words) for j in b}
    score = [[0.0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for x in range(len(a) - 1, -1, -1):
        for y in range(len(b) - 1, -1, -1):
            best = max(score[x + 1][y], score[x][y + 1])
            similarity = _similarity(old[a[x]], new[b[y]], bags[("a", a[x])], bags[("b", b[y])])
            if similarity >= SIMILAR_UNITS:
                best = max(best, similarity + score[x + 1][y + 1])
            score[x][y] = best
    pairs: list[tuple[int | None, int | None]] = []
    x = y = 0
    while x < len(a) and y < len(b):
        similarity = _similarity(old[a[x]], new[b[y]], bags[("a", a[x])], bags[("b", b[y])])
        if similarity >= SIMILAR_UNITS and score[x][y] == similarity + score[x + 1][y + 1]:
            pairs.append((a[x], b[y]))
            x += 1
            y += 1
        elif score[x][y] == score[x + 1][y]:
            pairs.append((a[x], None))
            x += 1
        else:
            pairs.append((None, b[y]))
            y += 1
    pairs += [(i, None) for i in a[x:]] + [(None, j) for j in b[y:]]
    return pairs


def _pair_greedy(old: list[Unit], new: list[Unit], a: list[int], b: list[int]):
    pairs: list[tuple[int | None, int | None]] = []
    y = 0
    for i in a:
        found = None
        for k in range(y, min(len(b), y + 30)):
            if _similarity(old[i], new[b[k]], set(old[i].words), set(new[b[k]].words)) >= 0.8:
                found = k
                break
        if found is None:
            pairs.append((i, None))
            continue
        pairs += [(None, j) for j in b[y:found]]
        pairs.append((i, b[found]))
        y = found + 1
    pairs += [(None, j) for j in b[y:]]
    return pairs


def similarity(a: Unit, b: Unit) -> float:
    return _similarity(a, b, set(a.words), set(b.words))


def pair_leftovers(
    old: list[Unit], new: list[Unit], removed: list[int], added: list[int]
) -> dict[int, int]:
    """Sentences of a section removed in one place and added, reworded, in another (6.3
    moved the error conditions of HCI commands from prose into tables): new index -> old
    index, most similar first."""
    if not removed or not added or len(removed) * len(added) > 10_000:
        return {}

    def distance(i: int, j: int) -> float:
        return abs(i / max(1, len(old) - 1) - j / max(1, len(new) - 1))

    # the most similar first; of two alike, the one that moved less
    candidates = sorted(
        (
            (score - LEFTOVER_DISTANCE * distance(i, j), j, i)
            for i in removed
            for j in added
            if (score := similarity(old[i], new[j])) >= SIMILAR_LEFTOVERS
        ),
        reverse=True,
    )
    pairs: dict[int, int] = {}
    taken: set[int] = set()
    for _, j, i in candidates:
        if j not in pairs and i not in taken:
            pairs[j] = i
            taken.add(i)
    return pairs


_SIMILARITY_CACHE: dict[tuple[str, str], float] = {}


def _similarity(a: Unit, b: Unit, bag_a: set[str], bag_b: set[str]) -> float:
    """How alike two sentences read: their words, regardless of case and punctuation (two
    parameter names that share only a trailing comma are not alike). `bag_a` and `bag_b`
    are their words, for a quick check first."""
    # the formats disagree on what is a row, code or a paragraph; titles stay titles
    if (a.kind in TITLES) != (b.kind in TITLES):
        return 0.0
    union = len(bag_a | bag_b)
    if not union or len(bag_a & bag_b) / union < 0.25:
        return 0.0
    cache_key = (a.norm, b.norm)
    if cache_key not in _SIMILARITY_CACHE:
        if len(_SIMILARITY_CACHE) > 200_000:
            _SIMILARITY_CACHE.clear()
        plain_a, plain_b = a.content, b.content
        if not set(plain_a) & set(plain_b):
            _SIMILARITY_CACHE[cache_key] = 0.0
        else:
            matcher = difflib.SequenceMatcher(None, plain_a, plain_b, autojunk=False)
            _SIMILARITY_CACHE[cache_key] = matcher.ratio()
    return _SIMILARITY_CACHE[cache_key]


def token_opcodes(old: Unit, new: Unit) -> Opcodes:
    """The word-level differences of a changed sentence, as difflib opcodes over its tokens.

    A table row whose cells hold several lines on both sides ("0 = unused" and "1 = used")
    is compared line by line: its lines are paired first, as sentences are, so that words
    are only matched within a line and its counterpart. Only the HTML marks the lines of a
    cell, and the PDF splits some tables into cells differently, so rows without lines on
    both sides are compared word by word."""
    if LINE not in old.words or LINE not in new.words:
        return _opcodes(old.words, new.words)
    old_lines, new_lines = _lines(old.words), _lines(new.words)
    old_units = [_line_unit(old, start, end) for start, end in old_lines]
    new_units = [_line_unit(new, start, end) for start, end in new_lines]
    result: list[tuple[str, int, int, int, int]] = []
    for i, j in align_units(old_units, new_units):
        if i is not None and j is not None:
            (i1, i2), (j1, j2) = old_lines[i], new_lines[j]
            result += [
                (tag, a1 + i1, a2 + i1, b1 + j1, b2 + j1)
                for tag, a1, a2, b1, b2 in _opcodes(old.words[i1:i2], new.words[j1:j2])
            ]
        elif i is not None:
            i1, i2 = old_lines[i]
            at = result[-1][4] if result else 0
            result.append(("delete", i1, i2, at, at))
        elif j is not None:
            j1, j2 = new_lines[j]
            at = result[-1][2] if result else 0
            result.append(("insert", at, at, j1, j2))
    return _merge_opcodes(result)


def _opcodes(old: list[str], new: list[str]) -> Opcodes:
    return difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()


def _lines(words: list[str]) -> list[tuple[int, int]]:
    """Where each line of a row starts and ends, its trailing separator included."""
    lines = []
    start = 0
    for index, word in enumerate(words):
        if word in SEPARATORS:
            lines.append((start, index + 1))
            start = index + 1
    if start < len(words):
        lines.append((start, len(words)))
    return lines


def _line_unit(unit: Unit, start: int, end: int) -> Unit:
    return Unit(unit.block, "p", "", unit.spans[start:end], unit.words[start:end])


def _merge_opcodes(codes: list[tuple[str, int, int, int, int]]) -> Opcodes:
    """Opcodes in order, adjacent ones of a kind joined, every token covered once."""
    merged: list[tuple[str, int, int, int, int]] = []
    for code in codes:
        tag, i1, i2, j1, j2 = code
        if i1 == i2 and j1 == j2:
            continue
        if merged and merged[-1][0] != "equal" and tag != "equal":
            _, a1, _, b1, _ = merged[-1]
            merged[-1] = ("replace", a1, i2, b1, j2)
        elif merged and merged[-1][0] == tag == "equal":
            _, a1, _, b1, _ = merged[-1]
            merged[-1] = ("equal", a1, i2, b1, j2)
        else:
            merged.append(code)
    fixed: list[tuple[str, int, int, int, int]] = []
    for tag, i1, i2, j1, j2 in merged:
        if tag != "equal":
            tag = "replace" if i1 < i2 and j1 < j2 else "delete" if i1 < i2 else "insert"
        fixed.append((tag, i1, i2, j1, j2))
    return fixed

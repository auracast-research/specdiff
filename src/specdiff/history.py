"""The history of the specification across all versions, for the site.

Every section gets one id for its whole life (its lineage), however it is renumbered,
retitled or moved to another Part, and so does every sentence. For each version step the
sections that changed get a diff, sentence by sentence and word by word, with each change
classified; for each version each sentence knows, word by word, the version that wrote it
(its blame).

Writes data/history/: index.json (versions, steps, Parts, sections with a status per step),
steps/N.json (the changes of step N, ranked, and where each sweeping rule applied) and
parts/KEY.json (text, blame and diffs of the sections of one Part, loaded when a section is
opened; a big Part is split into parts/KEY-0.json, KEY-1.json, ...)."""

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from specdiff import classify, sources
from specdiff.align import (
    Opcodes,
    Unit,
    align_units,
    match_moved,
    match_parts,
    match_sections,
    pair_leftovers,
    token_opcodes,
    units,
)
from specdiff.classify import NAME, Edit, Rule, Signals
from specdiff.model import Part, Section, Spec
from specdiff.text import key

# Status of a section in a step, for the map
ABSENT, SAME, EDITORIAL, CHANGED, ADDED, REMOVED = range(6)
# Diff entries
EQUAL, DELETE, INSERT, CHANGE = range(4)
# A sentence added or removed that is not a change: it moved, or the extraction differs;
# or that moved within its section and was reworded (the added one carries the diff)
QUIET = {"moved": 1, "noise": 2}
REWORDED = 3
# Segment kinds of a changed sentence: kept, removed, added, removed or added editorially
KEEP, OUT, IN, OUT_EDITORIAL, IN_EDITORIAL = range(5)
SIGNAL_BITS = {"n": 1, "x": 2, "v": 4}
EXCERPT_CONTEXT = 12  # words of context around a change in an excerpt
EXCERPT_WORDS = 40  # words of a sentence added or removed whole, in an excerpt
PART_FILE_BYTES = 2_000_000  # a Part file bigger than this is split
CHUNK_BYTES = 1_000_000  # into files of about this size


@dataclass
class Located:
    """A section of one version, where it is."""

    part: Part
    index: int
    section: Section
    units: list[Unit]
    lineage: str = ""


@dataclass
class UnitChange:
    kind: str  # "add", "del", "mod"; "edit" (editorial), "moved", "noise" (extraction)
    signals: Signals = field(default_factory=Signals)
    score: int = 0
    old: Unit | None = None
    new: Unit | None = None
    segments: list = field(default_factory=list)  # for "mod" and "edit"
    sid: int = -1  # the sentence's id, for its whole life
    rules: set[int] = field(default_factory=set)  # the sweeping rules it follows


@dataclass
class SectionStep:
    """What happened to one lineage in one step."""

    status: int
    entries: list = field(default_factory=list)  # the diff, for the Part file
    changes: list[UnitChange] = field(default_factory=list)


# Ranking. An edit to a sentence that stays outranks a sentence added or removed whole with
# the same signal, and both outrank the sentences of whole new or removed sections, which
# are easy to find anyway: the point is the small change in an old section. Values count
# for the filter, not the rank: too many of them are numbers written another way.


def _edit_score(signals: Signals) -> int:
    return 2 + 6 * bool(signals.normative) + 6 * bool(signals.negation)


def _whole_score(signals: Signals, *, existing: bool) -> int:
    normative = bool(signals.normative)
    return 1 + 6 * normative if existing else 3 * normative


class History:
    def __init__(self, specs: list[Spec]) -> None:
        self.specs = specs
        self.located: list[dict[str, Located]] = []  # per version: lineage -> section
        self.order: list[list[str]] = []  # per version: lineages in document order
        self.steps: list[dict[str, SectionStep]] = []
        self.rules: list[list[Rule]] = []  # per step, most frequent first
        self.rule_sections: list[dict[int, set[str]]] = []  # per step: rule -> lineages
        self.blame: list[dict[str, list[list[int]]]] = []  # per version: lineage -> origins
        self.sids: list[dict[str, list[int]]] = []  # per version: lineage -> sentence ids
        self.part_of: dict[str, str] = {}  # lineage -> the Part it was last in
        self.part_moves: dict[str, dict[str, str]] = defaultdict(dict)  # new key -> {n: old}
        self.part_pairs: dict[int, dict[str, str]] = {}  # per version: Part -> the one before
        self._counters: dict[str, int] = defaultdict(int)
        self._sid = 0

    # Lineages

    def _new_lineage(self, part_key: str) -> str:
        self._counters[part_key] += 1
        return f"{part_key}.{self._counters[part_key]}"

    def _new_sids(self, count: int) -> list[int]:
        self._sid += count
        return list(range(self._sid - count, self._sid))

    def _locate(self, spec: Spec) -> list[Located]:
        pdf = spec.format == "pdf"
        return [
            Located(part, index, section, units(section.blocks, pdf=pdf))
            for part in spec.parts
            for index, section in enumerate(part.sections)
        ]

    def run(self) -> None:
        previous: list[Located] = []
        for number, spec in enumerate(self.specs):
            current = self._locate(spec)
            if number == 0:
                for located in current:
                    located.lineage = self._new_lineage(located.part.key)
                self._record(current)
                self.blame.append(
                    {loc.lineage: [[0] * len(u.words) for u in loc.units] for loc in current}
                )
                self.sids.append({loc.lineage: self._new_sids(len(loc.units)) for loc in current})
                previous = current
                continue
            self._link(previous, current)
            self._record(current)
            self._step(number)
            previous = current
            print(f"step {self.specs[number - 1].version} -> {spec.version}", file=sys.stderr)

    def _record(self, current: list[Located]) -> None:
        for loc in current:
            self.part_of[loc.lineage] = loc.part.key
        self.located.append({loc.lineage: loc for loc in current})
        self.order.append([loc.lineage for loc in current])

    def _link(self, previous: list[Located], current: list[Located]) -> None:
        """Give each section of `current` the lineage of the section it continues: in the
        Part that continues its Part, else, by its text, in any other Part."""
        old_by_part: dict[str, list[Located]] = defaultdict(list)
        for loc in previous:
            old_by_part[loc.part.key].append(loc)
        for locs in old_by_part.values():  # a Part that moved keeps its sections' lineages
            locs.sort(key=lambda loc: loc.index)
        new_by_part: dict[str, list[Located]] = defaultdict(list)
        for loc in current:
            new_by_part[loc.part.key].append(loc)
        old_parts = [locs[0].part for locs in old_by_part.values()]
        new_parts = [locs[0].part for locs in new_by_part.values()]
        continued: set[str] = set()
        leftovers: list[Located] = []
        pairs = self.part_pairs.setdefault(len(self.located), {})
        for old_part, new_part in match_parts(old_parts, new_parts):
            if new_part is None:
                continue
            if old_part is not None:
                pairs[new_part.key] = old_part.key
            news = new_by_part[new_part.key]
            olds = old_by_part.get(old_part.key, []) if old_part else []
            if old_part and old_part.key != new_part.key:
                self.part_moves[new_part.key][str(len(self.located))] = old_part.key
            matches = match_sections(
                [o.section for o in olds],
                [n.section for n in news],
                [o.units for o in olds],
                [n.units for n in news],
            )
            for j, loc in enumerate(news):
                if j in matches:
                    loc.lineage = olds[matches[j][0]].lineage
                    continued.add(loc.lineage)
                else:
                    leftovers.append(loc)
        # sections that moved to another Part
        gone = [loc for loc in previous if loc.lineage not in continued]
        moved = match_moved([loc.units for loc in gone], [loc.units for loc in leftovers])
        for j, loc in enumerate(leftovers):
            loc.lineage = gone[moved[j]].lineage if j in moved else self._new_lineage(loc.part.key)

    def _relink(self, number: int, rules: list[Rule]) -> list[str]:
        """After the sweeping rules of a step are known: a section whose title only changed
        by them ("… by Slave" becoming "… by Peripheral") continues the old one. Returns the
        lineages joined up."""
        old, new = self.located[number - 1], self.located[number]
        rewrites = [
            (re.escape(key(rule.old)), key(rule.new))
            for rule in rules
            if key(rule.old) and key(rule.new) and NAME not in f"{rule.old} {rule.new}"
        ]

        # in one pass, longest first: "slave device" before "slave", and "simple pairing"
        # becoming "secure simple pairing" doesn't rewrite its own result
        replacements = {pattern: replacement for pattern, replacement in reversed(rewrites)}
        alternatives = sorted(replacements, key=len, reverse=True)
        combined = re.compile(r"\b(?:" + "|".join(alternatives) + r")\b") if alternatives else None

        def rewritten(title: str) -> str:
            text = key(title)
            return combined.sub(lambda m: replacements[m.group(0)], text) if combined else text

        gone: dict[tuple[str, str], list[str]] = defaultdict(list)  # (part, title) -> lineages
        for lineage, loc in old.items():
            if lineage not in new:
                gone[(loc.part.key, rewritten(loc.section.title))].append(lineage)
        joined = []
        for lineage in [lineage for lineage in new if lineage not in old]:
            loc = new[lineage]
            candidates = gone.get((loc.part.key, key(loc.section.title)), [])
            same_number = [c for c in candidates if old[c].section.number == loc.section.number]
            match = same_number[0] if same_number else candidates[0] if len(candidates) == 1 else ""
            if not match or not key(loc.section.title):
                continue
            candidates.remove(match)
            del new[lineage]
            loc.lineage = match
            new[match] = loc
            order = self.order[number]
            order[order.index(lineage)] = match
            del self.part_of[lineage]
            self.part_of[match] = loc.part.key
            joined.append(match)
        return joined

    # One step

    def _step(self, number: int) -> None:
        old = self.located[number - 1]
        new = self.located[number]
        pairs: dict[str, list[tuple[int | None, int | None]]] = {}
        edits: list[tuple[str, Edit]] = []
        opcodes: dict[tuple[str, int, int], Opcodes] = {}

        def align(lineage: str, *, learn: bool) -> None:
            a, b = old[lineage], new[lineage]
            aligned = align_units(a.units, b.units)
            pairs[lineage] = aligned
            for i, j in aligned:
                if i is None or j is None or a.units[i].norm == b.units[j].norm:
                    continue
                codes = token_opcodes(a.units[i], b.units[j])
                opcodes[(lineage, i, j)] = codes
                if learn:
                    for edit in _edits(a.units[i], b.units[j], codes):
                        edit.kind = classify.editorial_kind(edit)
                        edits.append((lineage, edit))

        for lineage in sorted(old.keys() & new.keys()):
            align(lineage, learn=True)
        rules = classify.learn_rules(edits)
        self.rules.append(rules)
        rule_index: dict[tuple[str, str], int] = {}
        for index, rule in enumerate(rules):
            rule_index.setdefault((rule.old, rule.new), index)
        for lineage in self._relink(number, rules):
            align(lineage, learn=False)

        # sentences removed in one place and added in another
        removed: dict[str, list[tuple[str, int]]] = defaultdict(list)
        added: list[tuple[str, int]] = []
        for lineage, loc in old.items():
            gone = range(len(loc.units)) if lineage not in new else _removed(pairs[lineage])
            for i in gone:
                removed[loc.units[i].norm].append((lineage, i))
        for lineage, loc in new.items():
            came = range(len(loc.units)) if lineage not in old else _added(pairs[lineage])
            added += [(lineage, j) for j in came]
        moved_to: dict[tuple[str, int], tuple[str, int]] = {}
        moved_from: set[tuple[str, int]] = set()
        for lineage, j in added:
            sources_ = removed.get(new[lineage].units[j].norm)
            if sources_:
                # from its own section if it can be, else from wherever it was removed
                source = next((s for s in sources_ if s[0] == lineage), sources_[-1])
                sources_.remove(source)
                moved_to[(lineage, j)] = source
                moved_from.add(source)

        fc = self.specs[number - 1].format != self.specs[number].format
        steps: dict[str, SectionStep] = {}
        blame_old = self.blame[number - 1]
        sids_old = self.sids[number - 1]
        blame_new: dict[str, list[list[int]]] = {}
        sids_new: dict[str, list[int]] = {}
        used: dict[int, set[str]] = defaultdict(set)
        for lineage in sorted(old.keys() | new.keys()):
            if lineage not in new:
                loc = old[lineage]
                changes = []
                for i, unit in enumerate(loc.units):
                    change = _whole(
                        unit,
                        added=False,
                        moved=(lineage, i) in moved_from,
                        format_change=fc,
                        existing=False,
                    )
                    change.sid = sids_old[lineage][i]
                    changes.append(change)
                entries = [[DELETE, QUIET.get(c.kind, 0), _codes(c.signals)] for c in changes]
                steps[lineage] = SectionStep(REMOVED, entries, changes)
                continue
            loc = new[lineage]
            if lineage not in old:
                changes = []
                origins = []
                sentence_ids = []
                for j, unit in enumerate(loc.units):
                    source = moved_to.get((lineage, j))
                    change = _whole(
                        unit, added=True, moved=source is not None, format_change=fc, existing=False
                    )
                    if source:
                        origins.append(list(blame_old[source[0]][source[1]]))
                        sentence_ids.append(sids_old[source[0]][source[1]])
                    else:
                        origins.append([number] * len(unit.words))
                        sentence_ids += self._new_sids(1)
                    change.sid = sentence_ids[-1]
                    changes.append(change)
                blame_new[lineage] = origins
                sids_new[lineage] = sentence_ids
                entries = [[INSERT, QUIET.get(c.kind, 0), _codes(c.signals)] for c in changes]
                steps[lineage] = SectionStep(ADDED, entries, changes)
                continue
            steps[lineage], blame_new[lineage], sids_new[lineage] = self._compare(
                number,
                lineage,
                old[lineage],
                loc,
                pairs[lineage],
                opcodes,
                rule_index,
                moved_to,
                moved_from,
            )
            for change in steps[lineage].changes:
                for rule in change.rules:
                    used[rule].add(lineage)
        self.steps.append(steps)
        self.blame.append(blame_new)
        self.sids.append(sids_new)
        self.rule_sections.append(dict(used))

    def _compare(
        self,
        number: int,
        lineage: str,
        a: Located,
        b: Located,
        aligned: list[tuple[int | None, int | None]],
        opcodes: dict,
        rules: dict[tuple[str, str], int],
        moved_to: dict,
        moved_from: set,
    ) -> tuple[SectionStep, list[list[int]], list[int]]:
        old_origins = self.blame[number - 1][lineage]
        old_sids = self.sids[number - 1][lineage]
        fc = self.specs[number - 1].format != self.specs[number].format
        origins: list[list[int]] = [[] for _ in b.units]
        sids: list[int] = [-1] * len(b.units)
        entries: list = []
        changes: list[UnitChange] = []
        renamed = (
            a.section.title != b.section.title
            or a.section.number != b.section.number
            or self._moved_part(number, a, b)
        )
        old_words = {w.lower() for unit in a.units for w in unit.words}
        new_words = {w.lower() for unit in b.units for w in unit.words}

        def equal_run() -> None:
            if entries and entries[-1][0] == EQUAL:
                entries[-1][1] += 1
            else:
                entries.append([EQUAL, 1])

        reworded = pair_leftovers(
            a.units,
            b.units,
            [
                i
                for i, j in aligned
                if j is None and i is not None and (lineage, i) not in moved_from
            ],
            [j for i, j in aligned if i is None and j is not None and (lineage, j) not in moved_to],
        )
        # a pair that crosses no sentence that stayed was rewritten where it is: a change
        in_place = _in_place(aligned, reworded)
        if in_place:
            aligned = _realign(aligned, in_place, len(a.units), len(b.units))
            reworded = {j: i for j, i in reworded.items() if j not in in_place}
        reworded_from = set(reworded.values())

        for i, j in aligned:
            if i is not None and j is not None:
                old_unit, new_unit = a.units[i], b.units[j]
                sids[j] = old_sids[i]
                if old_unit.norm == new_unit.norm:
                    origins[j] = list(old_origins[i])
                    equal_run()
                    continue
                codes = opcodes.get((lineage, i, j)) or token_opcodes(old_unit, new_unit)
                change, origins[j] = _changed(
                    number, old_unit, new_unit, codes, rules, old_origins[i]
                )
                change.sid = sids[j]
                changes.append(change)
                entries.append(
                    [CHANGE, change.kind == "edit", _codes(change.signals), change.segments]
                )
            elif i is not None and i in reworded_from:
                entries.append([DELETE, REWORDED, ""])
            elif i is not None:
                change = _whole(
                    a.units[i],
                    added=False,
                    moved=(lineage, i) in moved_from,
                    format_change=fc,
                    existing=True,
                    other_words=new_words,
                )
                change.sid = old_sids[i]
                changes.append(change)
                entries.append([DELETE, QUIET.get(change.kind, 0), _codes(change.signals)])
            elif j is not None and j in reworded:
                source = reworded[j]
                codes = token_opcodes(a.units[source], b.units[j])
                change, origins[j] = _changed(
                    number, a.units[source], b.units[j], codes, rules, old_origins[source]
                )
                sids[j] = change.sid = old_sids[source]
                changes.append(change)
                entries.append(
                    [
                        INSERT,
                        REWORDED,
                        _codes(change.signals),
                        change.segments,
                        change.kind == "edit",
                        source,
                    ]
                )
            elif j is not None:
                source = moved_to.get((lineage, j))
                change = _whole(
                    b.units[j],
                    added=True,
                    moved=source is not None,
                    format_change=fc,
                    existing=True,
                    other_words=old_words,
                )
                if source:
                    origins[j] = list(self.blame[number - 1][source[0]][source[1]])
                    sids[j] = self.sids[number - 1][source[0]][source[1]]
                else:
                    origins[j] = [number] * len(b.units[j].words)
                    sids[j] = self._new_sids(1)[0]
                change.sid = sids[j]
                changes.append(change)
                entry: list = [INSERT, QUIET.get(change.kind, 0), _codes(change.signals)]
                if source and source[0] == lineage:
                    entry += [None, None, source[1]]  # moved within the section: from where
                entries.append(entry)
        if any(c.kind in ("add", "del", "mod") for c in changes):
            status = CHANGED
        elif changes or renamed:
            status = EDITORIAL
        else:
            status = SAME
        return SectionStep(status, entries if status != SAME else [], changes), origins, sids

    def _moved_part(self, number: int, a: Located, b: Located) -> bool:
        """The section left its Part for another one: not the Part's successor (Core 5.2 moved
        the whole HCI from Vol 2 to Vol 4, which moves none of its sections)."""
        return self.part_pairs.get(number, {}).get(b.part.key) != a.part.key

    # Output

    def write(self, out: Path) -> None:
        versions = [sources.version(spec.version) for spec in self.specs]
        lineages = self._ordered_lineages()
        by_part: dict[str, list[str]] = defaultdict(list)
        for lineage in lineages:
            by_part[self.part_of[lineage]].append(lineage)
        files: dict[str, dict] = {}
        chunk_of: dict[str, int] = {}
        chunks: dict[str, int] = {}
        for part_key, part_lineages in by_part.items():
            whole = self._part_file(part_key, part_lineages)
            if len(json.dumps(whole, ensure_ascii=False)) <= PART_FILE_BYTES:
                files[part_key] = whole
                continue
            groups = self._chunks(part_key, part_lineages)
            chunks[part_key] = len(groups)
            for index, group in enumerate(groups):
                files[f"{part_key}-{index}"] = self._part_file(part_key, group)
                chunk_of.update(dict.fromkeys(group, index))
        index = {
            "versions": [
                {
                    "label": spec.version,
                    "format": spec.format,
                    "date": version.date,
                    "source": spec.source,
                }
                for spec, version in zip(self.specs, versions, strict=True)
            ],
            "steps": [self.step_summary(n) for n in range(len(self.steps))],
            "parts": self._parts(chunks),
            "sections": [self._section_entry(lineage, chunk_of) for lineage in lineages],
        }
        _dump(out / "index.json", index)
        rank = {lineage: i for i, lineage in enumerate(lineages)}
        for n in range(len(self.steps)):
            rule_sections = [
                sorted(self.rule_sections[n].get(k, ()), key=rank.__getitem__)
                for k in range(len(self.rules[n]))
            ]
            _dump(
                out / "steps" / f"{n}.json",
                {"step": n, "items": self._items(n, lineages), "rules": rule_sections},
            )
        for old in (out / "parts").glob("*.json") if (out / "parts").exists() else []:
            old.unlink()
        for name, document in files.items():
            _dump(out / "parts" / f"{name}.json", document)

    def _chunks(self, part_key: str, lineages: list[str]) -> list[list[str]]:
        """The lineages of a big Part, in groups whose files are small enough to load at
        once."""
        groups: list[list[str]] = [[]]
        size = 0
        for lineage in lineages:
            own = len(json.dumps(self._part_file(part_key, [lineage]), ensure_ascii=False))
            if groups[-1] and size + own > CHUNK_BYTES:
                groups.append([])
                size = 0
            groups[-1].append(lineage)
            size += own
        return groups

    def _ordered_lineages(self) -> list[str]:
        """All lineages in reading order: the newest version's order, with the sections it
        no longer has slotted in after the section they followed when they last appeared."""
        placed: list[str] = list(self.order[-1])
        position: dict[str, float] = {lineage: i for i, lineage in enumerate(placed)}
        for order in reversed(self.order[:-1]):
            inserted: list[tuple[float, int, str]] = []
            anchor: float = -1
            for seq, lineage in enumerate(order):
                if lineage in position:
                    anchor = position[lineage]
                else:
                    inserted.append((anchor, seq, lineage))
            for anchor, seq, lineage in inserted:
                position[lineage] = anchor + (seq + 1) / (len(order) + 2)
            placed = sorted(position, key=position.__getitem__)
            position = {lineage: i for i, lineage in enumerate(placed)}
        part_rank = {}
        for spec in reversed(self.specs):
            for part in spec.parts:
                part_rank.setdefault(part.key, (part.vol, part.letter))
        return sorted(placed, key=lambda lin: (part_rank[self.part_of[lin]], position[lin]))

    def _parts(self, chunks: dict[str, int]) -> list[dict]:
        parts: dict[str, dict] = {}
        for n, spec in enumerate(self.specs):
            for part in spec.parts:
                entry = parts.setdefault(
                    part.key,
                    {
                        "key": part.key,
                        "vol": part.vol,
                        "letter": part.letter,
                        "titles": [None] * len(self.specs),
                        "urls": [None] * len(self.specs),
                    },
                )
                entry["titles"][n] = part.title
                entry["urls"][n] = part.url
        for key_, moves in self.part_moves.items():
            parts[key_]["from"] = moves
        for key_, count in chunks.items():
            parts[key_]["chunks"] = count
        return sorted(parts.values(), key=lambda p: (p["vol"], p["letter"]))

    def _section_entry(self, lineage: str, chunk_of: dict[str, int]) -> dict:
        present = [n for n, located in enumerate(self.located) if lineage in located]
        last = self.located[present[-1]][lineage].section
        entry: dict = {
            "id": lineage,
            "p": self.part_of[lineage],
            "n": last.number,
            "t": last.title,
            "d": last.depth,
            "v": [present[0], present[-1]],
        }
        if lineage in chunk_of:
            entry["f"] = chunk_of[lineage]
        numbers = {n: self.located[n][lineage].section.number for n in present}
        titles = {n: self.located[n][lineage].section.title for n in present}
        if len(set(numbers.values())) > 1:
            entry["no"] = {str(n): number for n, number in numbers.items() if number != last.number}
        if len(set(titles.values())) > 1:
            entry["to"] = {str(n): title for n, title in titles.items() if title != last.title}
        parts = {
            str(n): self.located[n][lineage].part.key
            for n in present
            if self.located[n][lineage].part.key != entry["p"]
        }
        if parts:
            entry["pp"] = parts
        anchors = {
            n: self.located[n][lineage].section.anchor
            for n in present
            if self.specs[n].format == "html"
        }
        if anchors:
            latest = anchors[max(anchors)]
            entry["a"] = latest
            other = {str(n): a for n, a in anchors.items() if a != latest}
            if other:
                entry["ao"] = other
        pages = {
            str(n): self.located[n][lineage].section.page
            for n in present
            if self.specs[n].format == "pdf"
        }
        if pages:
            entry["pg"] = pages
        statuses = []
        sizes = []
        signal_bits = []
        editorial_rules: dict[str, list[int]] = {}
        for n, step in enumerate(self.steps):
            section_step = step.get(lineage)
            if section_step is None:
                statuses.append(ABSENT)
                sizes.append(0)
                signal_bits.append(0)
                continue
            statuses.append(section_step.status)
            sizes.append(sum(c.kind in ("add", "del", "mod") for c in section_step.changes))
            bits = 0
            for change in section_step.changes:
                for code in _codes(change.signals):
                    bits |= SIGNAL_BITS[code]
            signal_bits.append(bits)
            if section_step.status == EDITORIAL:
                followed = set().union(*(c.rules for c in section_step.changes if c.kind == "edit"))
                if followed:
                    editorial_rules[str(n)] = sorted(followed)
        entry["s"] = statuses
        entry["m"] = sizes
        if any(signal_bits):
            entry["x"] = signal_bits
        if editorial_rules:
            # the sweeping rules its editorial-only steps rest on, for switching them off
            entry["er"] = editorial_rules
        return entry

    def step_summary(self, n: int) -> dict:
        counts = defaultdict(int)
        units = defaultdict(int)
        for section_step in self.steps[n].values():
            counts[section_step.status] += 1
            for change in section_step.changes:
                units[change.kind] += 1
        return {
            "from": n,
            "to": n + 1,
            "sections": {
                "added": counts[ADDED],
                "removed": counts[REMOVED],
                "changed": counts[CHANGED],
                "editorial": counts[EDITORIAL],
            },
            "sentences": dict(units),
            "rules": [
                [rule.old, rule.new, rule.count, rule.sections, *rule.example]
                for rule in self.rules[n]
            ],
        }

    def _items(self, n: int, lineages: list[str]) -> list[dict]:
        """The changes of step `n`, one per section that changed."""
        items = []
        rank = {lineage: i for i, lineage in enumerate(lineages)}
        old, new = self.located[n], self.located[n + 1]
        for lineage, section_step in self.steps[n].items():
            if section_step.status == SAME:
                continue
            changes = section_step.changes
            signals = Signals()
            for change in changes:
                signals.merge(change.signals)
            kind = {ADDED: "add", REMOVED: "del", CHANGED: "mod", EDITORIAL: "edit"}[
                section_step.status
            ]
            counted = {
                k: sum(c.kind == k for c in changes)
                for k in ("add", "del", "mod", "edit", "moved", "noise")
            }
            item: dict = {
                "id": lineage,
                "k": kind,
                "sc": max((c.score for c in changes), default=0),
                "c": list(counted.values()),
                "u": len(new[lineage].units) if lineage in new else 0,
                "o": rank[lineage],
            }
            if signals.codes():
                item["x"] = "".join(signals.codes())
                item["w"] = signals.describe()
            if kind in ("mod", "edit"):
                item["ex"] = _excerpt(changes)
            elif kind == "add":
                item["ex"] = _first(changes, "add")
            else:
                item["ex"] = _first(changes, "del")
            if not item["ex"]:
                del item["ex"]
            # the sentences, by id, for the net change of a range of steps
            for code, change_kind in (("na", "add"), ("nd", "del"), ("nm", "mod"), ("ne", "edit")):
                if found := [c.sid for c in changes if c.kind == change_kind]:
                    item[code] = found
            if moved := sorted({c.sid for c in changes if c.kind == "moved"}):
                item["nv"] = moved  # once each, though removed in one place and added in another
            if follows := [
                [c.sid, sorted(c.rules)] for c in changes if c.kind == "edit" and c.rules
            ]:
                item["rs"] = follows  # editorial sentences, by the sweeping rules they follow
            if lineage in old and lineage in new:
                a, b = old[lineage], new[lineage]
                before, after = _heading(a.section), _heading(b.section)
                if before != after or self._moved_part(n + 1, a, b):
                    item["tt"] = [before, after, a.part.key]
            item["q"] = _search_text(changes)
            items.append(item)
        items.sort(key=lambda item: item["o"])
        return items

    def _part_file(self, part_key: str, lineages: list[str]) -> dict:
        texts: dict[str, int] = {}

        def text_index(text: str) -> int:
            if text not in texts:
                texts[text] = len(texts)
            return texts[text]

        sections: dict[str, dict] = {}
        for lineage in lineages:
            versions: dict[str, dict] = {}
            previous_content = None
            for n, located in enumerate(self.located):
                loc = located.get(lineage)
                if loc is None:
                    previous_content = None
                    continue
                content = _content(loc, self.blame[n][lineage], text_index)
                if content != previous_content:
                    versions[str(n)] = content
                previous_content = content
            diffs = {}
            for n, step in enumerate(self.steps):
                section_step = step.get(lineage)
                if section_step is not None and section_step.status != SAME:
                    diffs[str(n)] = section_step.entries
            sections[lineage] = {"v": versions, "d": diffs}
        return {"key": part_key, "texts": list(texts), "sections": sections}


# Helpers


def _heading(section: Section) -> str:
    return f"{section.number} {section.title}".strip()


def _edits(old: Unit, new: Unit, codes: Opcodes) -> list[Edit]:
    return [_edit(old, new, i1, i2, j1, j2) for tag, i1, i2, j1, j2 in codes if tag != "equal"]


def _edit(old: Unit, new: Unit, i1: int, i2: int, j1: int, j2: int) -> Edit:
    return Edit(
        old.words[i1:i2],
        new.words[j1:j2],
        new.words[j1 - 1] if j1 else "",
        prefix=tuple(new.words[max(0, j1 - 5) : max(0, j1 - 1)]),
    )


def _removed(pairs: list[tuple[int | None, int | None]]) -> list[int]:
    return [i for i, j in pairs if j is None and i is not None]


def _added(pairs: list[tuple[int | None, int | None]]) -> list[int]:
    return [j for i, j in pairs if i is None and j is not None]


def _in_place(
    aligned: list[tuple[int | None, int | None]], reworded: dict[int, int]
) -> dict[int, int]:
    """The reworded pairs (new index -> old index) that cross no pair of sentences that
    stayed, nor each other: sentences rewritten where they are, not moved."""
    pairs = [(i, j) for i, j in aligned if i is not None and j is not None]
    found: dict[int, int] = {}
    for j, i in sorted(reworded.items()):
        kept = pairs + [(fi, fj) for fj, fi in found.items()]
        if not any((pi < i) != (pj < j) for pi, pj in kept):
            found[j] = i
    return found


def _realign(
    aligned: list[tuple[int | None, int | None]], extra: dict[int, int], old: int, new: int
) -> list[tuple[int | None, int | None]]:
    """`aligned` with the pairs of `extra` (new index -> old index) made pairs too."""
    pairs = sorted(
        [(i, j) for i, j in aligned if i is not None and j is not None]
        + [(i, j) for j, i in extra.items()],
        key=lambda pair: pair[1],
    )
    result: list[tuple[int | None, int | None]] = []
    next_i = next_j = 0
    for i, j in pairs:
        result += [(k, None) for k in range(next_i, i)]
        result += [(None, k) for k in range(next_j, j)]
        result.append((i, j))
        next_i, next_j = i + 1, j + 1
    result += [(k, None) for k in range(next_i, old)]
    result += [(None, k) for k in range(next_j, new)]
    return result


def _codes(signals: Signals) -> str:
    return "".join(signals.codes())


def _whole(
    unit: Unit,
    *,
    added: bool,
    moved: bool,
    format_change: bool,
    existing: bool,
    other_words: set[str] | None = None,
) -> UnitChange:
    """A sentence added or removed. Where the format changes (PDF to HTML) a scrap of text
    with hardly a word in it is the extraction, not the specification: an equation, a
    label from a figure. `existing` is whether its section is there before and after;
    `other_words` the words of the section on the other side of the step."""
    if moved or (format_change and _scrap(unit, other_words or set())):
        kind = "moved" if moved else "noise"
        return UnitChange(kind, old=None if added else unit, new=unit if added else None)
    signals = classify.whole_signals(unit.words, added=added)
    return UnitChange(
        "add" if added else "del",
        signals,
        _whole_score(signals, existing=existing),
        old=None if added else unit,
        new=unit if added else None,
    )


_HEX = re.compile(r"^0x[0-9a-f]+$", re.IGNORECASE)
# An equation the HTML sets as a paragraph: "Equation 3. CLK27-1k+1=CLK27-1k+TSCO"
_FORMULA = re.compile(r"^Equation \d|[^\s=]=[^\s=]")


def _scrap(unit: Unit, other_words: set[str]) -> bool:
    """An equation, which the PDF and the HTML render too differently to compare; or hardly a
    word: fewer than three words, names or hex values ("0x46 | Too Late" is three). Such a
    scrap is the extraction's if it is a figure's text, or if its words are all on the other
    side of the step too (the same table, cut up differently)."""
    if unit.kind == "eq" or (_FORMULA.search(unit.text) and len(unit.words) <= 40):
        return True
    wordy = sum(
        bool(_HEX.match(word)) or (len(word) >= 3 and any(c.isalpha() for c in word))
        for word in unit.words
    )
    if wordy >= 3:
        return False
    if unit.kind in ("figure", "caption"):
        return True
    content = {word.lower() for word in unit.words if classify.is_word(word)}
    return content <= other_words


def _changed(
    number: int,
    old: Unit,
    new: Unit,
    codes: Opcodes,
    rules: dict[tuple[str, str], int],
    old_origins: list[int],
) -> tuple[UnitChange, list[int]]:
    """A sentence that changed: its segments (kept, removed, added; editorial or not, with
    the sweeping rule an editorial one follows), its signals, and the version each of its
    words comes from."""
    segments: list[list] = []
    signals = Signals()
    substantive = False
    origins: list[int] = []
    followed: set[int] = set()
    removed_words: list[str] = []
    added_words: list[str] = []

    def piece(unit: Unit, start: int, end: int) -> str:
        if start >= end:
            return ""
        begin = unit.spans[start][0]
        stop = unit.spans[end][0] if end < len(unit.spans) else len(unit.text)
        return unit.text[begin:stop]

    def removed(start: int, end: int) -> str:
        """Removed text, with the space before it when the text around it lost that space
        ("piconet" + "are not supported" + "." would read "piconetare")."""
        text = piece(old, start, end)
        if not text:
            return ""
        spaced = start > 0 and old.text[old.spans[start][0] - 1].isspace()
        if spaced and segments and not segments[-1][1][-1:].isspace():
            return " " + text
        return text

    def add(kind: int, text: str, rule: int | None = None) -> None:
        if not text:
            return
        if (
            segments
            and segments[-1][0] == kind
            and segments[-1][2:] == ([rule] if rule is not None else [])
        ):
            segments[-1][1] += text
        else:
            segments.append([kind, text] if rule is None else [kind, text, rule])

    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal":
            add(KEEP, piece(new, j1, j2))
            origins += old_origins[i1:i2]
            continue
        edit = _edit(old, new, i1, i2, j1, j2)
        edit.kind = classify.editorial_kind(edit)
        rule = None
        if not edit.kind and (rule := classify.rule_of(edit, rules)) is not None:
            edit.kind = "sweeping"
            followed.add(rule)
        if edit.kind:
            add(OUT_EDITORIAL, removed(i1, i2), rule)
            add(IN_EDITORIAL, piece(new, j1, j2), rule)
            inherited = min(old_origins[i1:i2], default=origins[-1] if origins else number)
            origins += [inherited] * (j2 - j1)
        else:
            substantive = True
            context = new.words[max(0, j1 - 3) : j2 + 3]
            signals.merge(
                classify.signals(
                    edit.old, edit.new, context, before=edit.before, start=i1 == 0 and j1 == 0
                )
            )
            add(OUT, removed(i1, i2))
            add(IN, piece(new, j1, j2))
            origins += [number] * (j2 - j1)
            removed_words += edit.old
            added_words += edit.new
    classify.drop_reworded_negations(signals, removed_words, added_words)
    change = UnitChange(
        "mod" if substantive else "edit",
        signals,
        _edit_score(signals) if substantive else 0,
        old=old,
        new=new,
        segments=_tidy(segments),
        rules=followed,
    )
    return change, origins


def _tidy(segments: list[list]) -> list[list]:
    """Removed text doesn't end in a space where the text after it starts with one or with
    punctuation: "piconet~~ are not supported~~." rather than "piconet~~ are not supported ~~."."""
    for index, segment in enumerate(segments):
        if segment[0] in (OUT, OUT_EDITORIAL):
            following = segments[index + 1][1] if index + 1 < len(segments) else ""
            if not following or following[0].isspace() or following[0] in ".,;:)]":
                segment[1] = segment[1].rstrip()
    return [segment for segment in segments if segment[1]]


def _excerpt(changes: list[UnitChange]) -> list:
    """The most telling change of a section, trimmed: segments of a changed sentence, or
    [[IN, text]] for a sentence added, [[OUT, text]] for one removed."""
    ranked = sorted(
        (c for c in changes if c.kind not in QUIET),
        key=lambda c: (-c.score, c.kind == "edit"),
    )
    if not ranked:
        return []
    best = ranked[0]
    if best.kind == "add" and best.new:
        return [[IN, _shorten(best.new.text)]]
    if best.kind == "del" and best.old:
        return [[OUT, _shorten(best.old.text)]]
    return _trim(best.segments)


def _first(changes: list[UnitChange], kind: str) -> list:
    """The first sentence of a section added or removed, as an excerpt."""
    for change in changes:
        unit = change.new if kind == "add" else change.old
        if change.kind == kind and unit:
            return [[IN if kind == "add" else OUT, _shorten(unit.text)]]
    return []


def _shorten(text: str) -> str:
    words = text.split(" ")
    return text if len(words) <= EXCERPT_WORDS else " ".join(words[:EXCERPT_WORDS]) + " …"


def _trim(segments: list[list]) -> list[list]:
    """Long stretches of kept text shortened to a few words around the changes."""
    trimmed = []
    for index, (kind, text, *rest) in enumerate(segments):
        if kind != KEEP:
            trimmed.append([kind, text, *rest])
            continue
        words = text.split(" ")
        first, last = index == 0, index == len(segments) - 1
        keep = EXCERPT_CONTEXT
        if first and len(words) > keep:
            text = "… " + " ".join(words[-keep:])
        elif last and len(words) > keep:
            text = " ".join(words[:keep]) + " …"
        elif not first and not last and len(words) > 2 * keep:
            text = " ".join(words[:keep]) + " … " + " ".join(words[-keep:])
        trimmed.append([kind, text])
    return trimmed


_SEARCH_SPLIT = re.compile(r"[\W_]+")


def search_words(text: str) -> list[str]:
    """Words as the site's search splits them: letters and digits, lowercased. Must match
    `words` in site/static/app.js."""
    return [word for word in _SEARCH_SPLIT.split(text.lower()) if word]


def _search_text(changes: list[UnitChange]) -> str:
    """The words of the sentences a section's changes touch, once each, for the search."""
    found: set[str] = set()
    for change in changes:
        for unit in (change.old, change.new):
            if unit is not None:
                found.update(w for w in search_words(unit.text) if len(w) > 1)
    return " ".join(sorted(found))


def _content(loc: Located, origins: list[list[int]], text_index) -> dict:
    """A section of one version for the Part file: its blocks ([kind, number of
    sentences]) and its sentences ([text, blame]); the blame is a version number, or
    [[version, end], ...] by character for a sentence written in several versions."""
    blocks: list[list] = []
    for unit in loc.units:
        if blocks and blocks[-1][2] == unit.block:
            blocks[-1][1] += 1
        else:
            blocks.append([unit.kind, 1, unit.block])
    sentences = []
    for unit, unit_origins in zip(loc.units, origins, strict=True):
        sentences.append([text_index(unit.text), _runs(unit, unit_origins)])
    return {"b": [[kind, count] for kind, count, _ in blocks], "u": sentences}


def _runs(unit: Unit, origins: list[int]) -> int | list[list[int]]:
    if not origins:
        return 0
    if all(origin == origins[0] for origin in origins):
        return origins[0]
    runs: list[list[int]] = []
    for index, origin in enumerate(origins):
        end = unit.spans[index + 1][0] if index + 1 < len(unit.spans) else len(unit.text)
        if runs and runs[-1][0] == origin:
            runs[-1][1] = end
        else:
            runs.append([origin, end])
    return runs


def _dump(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), "utf-8")

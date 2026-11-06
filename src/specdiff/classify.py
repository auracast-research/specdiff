"""What kind of change a change is.

A word-level edit inside a sentence is editorial when it changes nothing a reader acts on:

- format: only case, punctuation, quotes or dashes differ, or a number is written another
  way ("11b" becomes "0b11")
- naming: the same name written another way ("a LE Set Scan Enable" becomes
  "an HCI_LE_Set_Scan_Enable")
- reference: a cross-reference renumbered ("Section 2.3.5" becomes "Section 2.3.6")
- sweeping: a rewrite the version applies everywhere ("master" becomes "central", "The
  HCI_Reset command" becomes "This"), learnt from the edits themselves: the same
  replacement in many sections of one version step

Anything else is substantive. Substantive edits carry signals: a normative keyword added,
removed or swapped (shall, should, may), a negation, a value."""

import re
from collections import Counter
from dataclasses import dataclass, field

# The words Vol 1, Part E gives a meaning to, and the words of the compliance tables
NORMATIVE = frozenset(
    "shall should may must required recommended optional mandatory excluded prohibited".split()  # noqa: SIM905
)
# "none" is left out: it is the value of a table cell far more often than a negation
NEGATION = frozenset("not no never neither nor cannot".split())  # noqa: SIM905
# Words that negate on their own: "disabled" becoming "not enabled" says the same thing.
# A closed list: "disconnection", "until" and "unicast" start the same way and negate nothing.
NEGATIVE_FORMS = frozenset(
    "disabled disable disables disallowed disallow disallows unused unsupported unable"  # noqa: SIM905
    " invalid inactive incorrect illegal unknown unset undefined unmasked unencrypted"
    " unauthenticated unconnected unacknowledged".split()
)
REFERENCE_WORDS = frozenset(
    "section sections table tables figure figures part parts vol volume appendix equation eq"  # noqa: SIM905
    " clause".split()
)
# Before a number, words that make it a place in the document rather than a value
_PLACE_WORDS = REFERENCE_WORDS | {"page", "pages", "sheet", "step", "steps", "item", "note"}
# A list of references continues after these: "Sections 2.3 and 2.4", "Tables 3, 4"
_LIST_WORDS = frozenset({",", "and", "or", "to", "-", "through"})
_NUMBERED = re.compile(r"^([A-Z]?\d+(\.\d+)*[a-z]?|[A-Z](\.\d+)+)$")
_LETTERED_PARTS = frozenset({"part", "parts", "appendix"})
# the conditions of the compliance tables of Vol 0 and section 3 of Vol 4, Part E
_CONDITION = re.compile(r"^C\.?\d+$")
_VALUE = re.compile(r"^(0x[0-9A-Fa-f]+|0b[01]+|[01]+b|\d+(\.\d+)?|\d+(,\d{3})+)$", re.IGNORECASE)
_UNIT_WORDS = frozenset(
    "ms us µs s ns khz mhz ghz hz dbm db octet octets bit bits byte bytes slots slot".split()  # noqa: SIM905
)
_PREFIXES = ("hci", "ll", "lmp", "l2cap", "att", "smp")
_ARTICLES = frozenset({"a", "an", "the"})
_NAME_SUFFIXES = frozenset({"command", "commands", "event", "events"})
# Punctuation that only structures a sentence; an operator ("<", "=") changes what it says
_OPERATORS = frozenset("< > = + \u2264 \u2265 \u00b1 \u00d7 * / % ^ ~ & !".split())  # noqa: SIM905
_WORDY = re.compile(r"[^\W_]")  # a letter or a digit

# A rewrite counts as sweeping when it happens this often in a version step
SWEEPING_COUNT = 6
SWEEPING_SECTIONS = 4
SWEEPING_LENGTH = 3  # tokens at most, on each side
# A pattern ("The <name> command" becoming "This") is sweeping when applied to this many
# identifiers, in as many sections as it is: 6.1 rewrote the description of 326 commands,
# 6.2 the summary of 432 in the one table that lists them
SWEEPING_NAMES = 20
# The only words a sweeping edit may add or remove outright: words that carry no meaning
# of their own. Any other word added or removed everywhere ("only", "Lower or",
# "insufficient") still changes what each of those sentences says.
FUNCTION_WORDS = frozenset(
    "a an the this that these those its it their of is are be".split()  # noqa: SIM905
)
# Words that narrow or widen what a sentence says: never part of a sweeping rewrite
LIMITING = frozenset(
    "only all both each every any either lower upper insufficient sufficient except unless"  # noqa: SIM905
    " until least most minimum maximum before after always otherwise if when".split()
)
NAME = "<name>"  # what a rule's pattern has in place of an identifier


@dataclass
class Edit:
    """One word-level edit of a changed sentence: the old and new tokens it replaces."""

    old: list[str]
    new: list[str]
    before: str  # the token before it, for references ("Section" 2.3.5)
    kind: str = ""  # format, naming, reference, sweeping, substantive
    # up to four tokens before it, for a reference in a list ("Sections 2.3 and 2.4")
    prefix: tuple[str, ...] = ()

    @property
    def rule(self) -> tuple[str, str]:
        return phrase(self.old), phrase(self.new)

    @property
    def shape(self) -> tuple[str, str] | None:
        """The edit with its identifiers left out, when it replaces a name with words that
        name nothing: "The HCI_Reset command" becoming "This" is ("the <name>", "this"). The
        same rewrite of many different commands is one rewrite. Never the other way round:
        "write request" becoming "ATT_WRITE_REQ PDU" names one PDU, and a pattern would
        accept any."""
        old, new = _abstract(self.old), _abstract(self.new)
        if not self.old or not self.new or NAME not in old.split() or NAME in new.split():
            return None
        return old, new


def phrase(words: list[str]) -> str:
    return " ".join(words).lower()


def _is_name(word: str) -> bool:
    return "_" in word and any(c.isalpha() for c in word)


def _abstract(words: list[str]) -> str:
    return " ".join(NAME if _is_name(word) else word.lower() for word in words)


@dataclass
class Signals:
    normative: set[str] = field(default_factory=set)  # e.g. {"+shall", "-should"}
    negation: set[str] = field(default_factory=set)  # {"+not"}
    values: bool = False

    def merge(self, other: "Signals") -> None:
        self.normative |= other.normative
        self.negation |= other.negation
        self.values = self.values or other.values

    def codes(self) -> list[str]:
        """Short codes for the site: "n" normative, "x" negation, "v" values."""
        return [
            code
            for code, present in (
                ("n", self.normative),
                ("x", self.negation),
                ("v", self.values),
            )
            if present
        ]

    def describe(self) -> list[str]:
        words = sorted(self.normative, key=lambda w: (w[1:], w[0]))
        return [*words, *sorted(self.negation)]


def is_word(token: str) -> bool:
    """A token with a letter or digit in it, as opposed to punctuation ("ASB-C" is a word)."""
    return bool(_WORDY.search(token))


def editorial_kind(edit: Edit) -> str:
    """format, naming or reference, or "" when the edit is none of them."""
    old, new = edit.old, edit.new
    if _letters(old) == _letters(new) and _letters(old):
        return "format"
    dash = "-" in old + new and edit.before[-1:].isdigit()  # "1 - 5" is a range
    if not any(map(is_word, old + new)) and not set(old + new) & _OPERATORS and not dash:
        return "format"  # punctuation added, removed or swapped
    if old and new and _same_numbers(old, new):
        return "format"
    # "the LE Set Scan Enable command" and "HCI_LE_Set_Scan_Enable": the identifier says
    # "command" itself, so the side without one may drop the word
    old_named, new_named = any(map(_is_name, old)), any(map(_is_name, new))
    old_name = _name(old, suffix=new_named and not old_named)
    if old_name and old_name == _name(new, suffix=old_named and not new_named):
        return "naming"
    if old and new and _is_reference(edit):
        return "reference"
    if old and new and all(_CONDITION.match(w) for w in old + new):
        return "reference"
    return ""


def _is_reference(edit: Edit) -> bool:
    """A renumbered reference: numbers after "Section", "Table", ... or in a list of them."""
    words = edit.old + edit.new
    context = [w.lower() for w in (*edit.prefix, edit.before) if w]
    if not context:
        return False
    place = context[-1]
    if place not in REFERENCE_WORDS:
        # "Sections 2.3 and 2.4": back over the list to the word that starts it
        back = list(reversed(context))
        if back[0] not in _LIST_WORDS:
            return False
        for word in back[1:]:
            if word in REFERENCE_WORDS:
                place = word
                break
            if word not in _LIST_WORDS and not _NUMBERED.match(word.upper()):
                return False
        else:
            return False
    if place in _LETTERED_PARTS:
        return all(_NUMBERED.match(w) or re.fullmatch(r"[A-Z]", w) for w in words)
    return all(_NUMBERED.match(w) and any(c.isdigit() for c in w) for w in words)


def _letters(words: list[str]) -> str:
    """Letters and digits only; a range written "3-8" reads as "3 to 8"."""
    text = re.sub(r"(\d)\s*-\s*(\d)", r"\1to\2", " ".join(words).lower())
    return re.sub(r"[^a-z0-9]", "", text)


def _name(words: list[str], *, suffix: bool = False) -> str:
    """ "HCI_LE_Set_Scan_Enable" and "LE Set Scan Enable" both give "lesetscanenable"; so do
    "an HCI_LE_Set_Scan_Enable" and, with `suffix`, "the LE Set Scan Enable command"."""
    words = [w for w in words if is_word(w)]
    if words and words[0].lower() in _ARTICLES:
        words = words[1:]
    if suffix and words and words[-1].lower() in _NAME_SUFFIXES:
        words = words[:-1]
    letters = _letters(words)
    for prefix in _PREFIXES:
        if letters.startswith(prefix) and len(letters) > len(prefix) + 3:
            return letters[len(prefix) :]
    return letters


def number(token: str) -> float | None:
    """The value of a number however it is written: 0x1F, 0b11, 11b, 1,000, 2.5."""
    text = token.lower().replace(",", "")
    try:
        if text.startswith("0x"):
            return float(int(text[2:], 16))
        if text.startswith("0b"):
            return float(int(text[2:], 2))
        if text.endswith("b") and text[:-1] and set(text[:-1]) <= {"0", "1"}:
            return float(int(text[:-1], 2))
        return float(text)
    except ValueError:
        return None


def _numbers(words: list[str]) -> list[float] | None:
    """The values of `words` when every word of them is a number, else None."""
    values = [number(w) for w in words if is_word(w)]
    found = [v for v in values if v is not None]
    return sorted(found) if found and len(found) == len(values) else None


def _same_numbers(old: list[str], new: list[str]) -> bool:
    """Both sides are the same numbers written another way ("11b" and "0b11")."""
    old_values = _numbers(old)
    return old_values is not None and old_values == _numbers(new)


def _meaningless(word: str) -> bool:
    return word.lower() in FUNCTION_WORDS or not is_word(word)


_TITLE_REFERENCE = frozenset({"part", "parts", "section", "sections", "appendix"})


def _in_reference(edit: Edit) -> bool:
    """The edit is inside a reference to a Part or section, which quotes its title: "See
    [Vol 1] Part F, Controller Error Codes" after the Part was renamed in 5.2."""
    return any(w.lower() in _TITLE_REFERENCE for w in (*edit.prefix, edit.before))


def is_sweeping_candidate(edit: Edit) -> bool:
    replaced = 0 < len(edit.old) <= SWEEPING_LENGTH and 0 < len(edit.new) <= SWEEPING_LENGTH
    only = edit.new if not edit.old else edit.old if not edit.new else []
    # words added or removed outright: words without meaning, or a title in a reference
    added_or_removed = 0 < len(only) <= 2 and (all(map(_meaningless, only)) or _in_reference(edit))
    if not (replaced or added_or_removed):
        return False
    words = {w.lower() for w in edit.old + edit.new}
    if words & (NORMATIVE | NEGATION | LIMITING):
        return False
    return not any(_VALUE.match(w) for w in words)


@dataclass
class Rule:
    """A sweeping rewrite of one version step."""

    old: str  # the phrases, lowercased; a pattern has <name> for an identifier
    new: str
    count: int
    sections: int
    example: tuple[str, str]  # one occurrence as written


def learn_rules(edits: list[tuple[str, Edit]]) -> list[Rule]:
    """Sweeping rewrites of a version step, from its (section id, edit) pairs: the same
    short replacement, often, in many sections; most frequent first. A replacement that
    differs only in the identifier it names ("The HCI_Reset command" and "The
    HCI_Read_BD_ADDR command" both becoming "This") counts as one."""
    counts: Counter[tuple[str, str]] = Counter()
    sections: dict[tuple[str, str], set[str]] = {}
    examples: dict[tuple[str, str], tuple[str, str]] = {}
    variants: dict[tuple[str, str], set[tuple[str, str]]] = {}  # pattern -> rewrites
    for section, edit in edits:
        if edit.kind or not is_sweeping_candidate(edit):
            continue
        rules = [edit.rule]
        if (shape := edit.shape) is not None:
            rules.append(shape)
            variants.setdefault(shape, set()).add(edit.rule)
        for rule in rules:
            counts[rule] += 1
            sections.setdefault(rule, set()).add(section)
            examples.setdefault(rule, (" ".join(edit.old), " ".join(edit.new)))

    def sweeping(rule: tuple[str, str], count: int) -> bool:
        factor = 2 if not rule[0] or not rule[1] else 1  # only added, or only removed
        # a pattern is the same rewrite of many identifiers, not one rewrite seen many times
        if rule in variants:
            return count >= SWEEPING_COUNT and len(variants[rule]) >= SWEEPING_NAMES
        spread = len(sections[rule]) >= SWEEPING_SECTIONS * factor
        return count >= SWEEPING_COUNT * factor and spread

    found = [
        Rule(old, new, count, len(sections[(old, new)]), examples[(old, new)])
        for (old, new), count in counts.items()
        if sweeping((old, new), count)
    ]
    return sorted(found, key=lambda rule: (-rule.count, rule.old, rule.new))


def rule_of(edit: Edit, rules: dict[tuple[str, str], int]) -> int | None:
    """The index of the sweeping rule an edit follows, or None. A single word that holds a
    rule's word follows it too ("masterSCA" becoming "centralSCA" under master → central)."""
    found = rules.get(edit.rule)
    only = edit.new if not edit.old else edit.old if not edit.new else []
    if found is not None and only and not all(map(_meaningless, only)):
        # a word added or removed everywhere was learnt in references; it only applies there
        return found if _in_reference(edit) else None
    if found is None and (shape := edit.shape) is not None:
        found = rules.get(shape)
    if found is None and len(edit.old) == 1 and len(edit.new) == 1:
        old, new = edit.old[0].lower(), edit.new[0].lower()
        for (was, now), index in rules.items():
            if was and now and " " not in was and was in old and old.replace(was, now) == new:
                return index
    return found


def signals(
    old: list[str],
    new: list[str],
    context: list[str] | None = None,
    *,
    before: str = "",
    start: bool = False,
) -> Signals:
    """What a substantive edit touches. `old` and `new` are the tokens it removes and adds,
    `before` the token before it and `start` whether it begins its sentence."""
    found = Signals()
    removed = Counter(w.lower() for w in old)
    added = Counter(w.lower() for w in new)
    for word in (removed - added).keys() & (NORMATIVE - NEGATION):
        found.normative.add(f"-{word}")
    for word in (added - removed).keys() & (NORMATIVE - NEGATION):
        found.normative.add(f"+{word}")
    # "disabled" becoming "not used" rewords a negation, it doesn't add one
    negated_out = bool((removed - added).keys() & NEGATIVE_FORMS)
    negated_in = bool((added - removed).keys() & NEGATIVE_FORMS)
    for word in (removed - added).keys() & NEGATION:
        if not negated_in:
            found.negation.add(f"-{word}")
    for word in (added - removed).keys() & NEGATION:
        if not negated_out:
            found.negation.add(f"+{word}")
    old_values = _values(old, before, start=start)
    new_values = _values(new, before, start=start)
    if sorted(map(_value_key, old_values)) != sorted(map(_value_key, new_values)):
        found.values = True
    elif not old_values and not new_values:
        changed = list((removed - added) + (added - removed))
        found.values = bool(
            set(changed) & _UNIT_WORDS and any(_VALUE.match(w) for w in context or [])
        )
    return found


def drop_reworded_negations(found: Signals, removed: list[str], added: list[str]) -> None:
    """Across a whole sentence: "Channel n is disabled" in one line and "Channel n is not
    used" in another reword the same negation, even when its edits pair them apart."""
    out = Counter(w.lower() for w in removed)
    into = Counter(w.lower() for w in added)
    if (out - into).keys() & NEGATIVE_FORMS:
        found.negation = {w for w in found.negation if not w.startswith("+")}
    if (into - out).keys() & NEGATIVE_FORMS:
        found.negation = {w for w in found.negation if not w.startswith("-")}


def _values(words: list[str], before: str, *, start: bool) -> list[str]:
    """The numbers among `words` that are values: not section, table, figure or page
    numbers ("Table 7.2", "on page 12", "(Sheet 4 of 11)") and not the ordinal a list item
    starts with ("1." "2)")."""
    found = []
    # inside a reference: after "Table", and on through "Tables 3, 4 and 5"
    place = before.lower() in _PLACE_WORDS
    for index, word in enumerate(words):
        lower = word.lower()
        following = words[index + 1] if index + 1 < len(words) else ""
        ordinal = start and index == 0 and following in (".", ")")
        if _VALUE.match(word) and not ordinal and not place:
            found.append(word)
        if lower in _PLACE_WORDS:
            place = True
        elif not (place and (lower in _LIST_WORDS or _NUMBERED.match(word))):
            place = False
    return found


def _value_key(word: str) -> str:
    value = number(word)
    return word.lower() if value is None else repr(value)


def whole_signals(words: list[str], *, added: bool) -> Signals:
    """Signals of a sentence added or removed as a whole: the normative keywords it holds.
    A negation or a number in a new sentence is not a negation or a value changed."""
    found = signals([], words) if added else signals(words, [])
    return Signals(normative=found.normative)

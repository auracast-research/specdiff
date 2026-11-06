"""Text as the diff sees it: cleaned up, split into sentences and into tokens.

The HTML and the PDF render the same text with different characters (soft hyphens,
no-break spaces, ligatures, curly or straight quotes), so both are cleaned the same way
before anything is compared."""

import re
import unicodedata

_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)
_SPACES = dict.fromkeys(map(ord, "\u00a0\u2002\u2003\u2007\u2009\u200a\u202f\u3000"), " ")
_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
# Characters that differ between the formats or between editions without meaning anything
_FOLD = str.maketrans(
    {
        "\u2018": "'",  # curly single quotes, primes
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',  # curly double quotes
        "\u201d": '"',
        "\u201e": '"',
        "\u2033": '"',
        "\u2010": "-",  # hyphens, dashes, minus
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00d7": "x",  # multiplication sign
        "\u2026": "...",
    }
)


# The replacement character, and the private-use code points PDF symbol fonts map to
_JUNK = re.compile("[\ufffd\ue000-\uf8ff]")


def clean(text: str) -> str:
    """Visible text with invisible characters removed and whitespace collapsed."""
    text = _JUNK.sub("", text.translate(_INVISIBLE).translate(_SPACES))
    for ligature, letters in _LIGATURES.items():
        text = text.replace(ligature, letters)
    return " ".join(text.split())


def clean_lines(text: str) -> str:
    """Preformatted text: each line cleaned, empty lines dropped."""
    return "\n".join(line for line in map(clean, text.splitlines()) if line)


def fold(text: str) -> str:
    """The form two texts are compared in: quotes, dashes and the like made plain."""
    return unicodedata.normalize("NFKC", text).translate(_FOLD)


def key(text: str) -> str:
    """For matching titles and sentences regardless of case and punctuation."""
    return " ".join(re.findall(r"[a-z0-9]+", fold(text).lower()))


# Sentences. A full stop ends one unless it belongs to an abbreviation.
_ABBREVIATIONS = frozenset(
    "e.g i.e etc cf vs approx vol fig no nos inc ltd resp incl max min sec eq ref ch".split()  # noqa: SIM905
)
_SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s+(?=[\"'\u201c\u2018(\[]?[A-Z0-9])")
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")


def sentences(text: str) -> list[str]:
    """`text` split after each sentence; joining them with spaces gives `text` back."""
    parts = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        # the closing quotes and brackets stay with the sentence they close
        end = match.start() + len(match.group(0).rstrip())
        word = _LAST_WORD.search(text, start, match.start() + 1)
        if word and word.group(1).lower() in _ABBREVIATIONS:
            continue
        parts.append(text[start:end].strip())
        start = match.end()
    parts.append(text[start:].strip())
    return [part for part in parts if part]


# Tokens: words (with inner hyphens, underscores, dots and apostrophes: "HCI_LE_Read",
# "man-in-the-middle", "0x0C03", "2.3.5.3", "device's"), and single other characters.
_TOKEN = re.compile(r"\w+(?:[-_.'\u2019]\w+)*|[^\w\s]")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


# The PDF's own furniture inside the text: page numbers of cross-references and the sheet
# count of a table set over several pages, which change whenever the page breaks do
# (the PDF sometimes loses the space after the number, or the number: "on page 370for",
# "on page [!XREF]")
_PAGE_REFERENCE = re.compile(r"\s+on page (?:\d+|\[!XREF\])(?=(\w)?)")
_SHEET = re.compile(r"\s*\(Sheet \d+ of \d+\)")
# an identifier broken across lines after an underscore ("TSync_ Train_Interval")
_BROKEN_NAME = re.compile(r"(?<=[A-Za-z0-9]_) (?=[A-Za-z0-9])")


def drop_pdf_furniture(text: str) -> str:
    """Text from a PDF without the page references and sheet counts the HTML doesn't have,
    and with identifiers broken at an underscore joined again."""
    text = _PAGE_REFERENCE.sub(lambda m: " " if m.group(1) else "", text)
    text = _SHEET.sub("", text)
    return _BROKEN_NAME.sub("", text)


def token_spans(text: str) -> list[tuple[int, int]]:
    """Where each token of `text` starts and ends."""
    return [match.span() for match in _TOKEN.finditer(text)]

from itertools import pairwise

from specdiff.align import (
    align_units,
    match_moved,
    match_parts,
    match_sections,
    pair_leftovers,
    similarity,
    token_opcodes,
    units,
)
from specdiff.model import Block, Part, Section


def p(*texts: str) -> list[Block]:
    return [Block("p", text) for text in texts]


def test_units_are_sentences_rows_and_code_lines():
    found = units(
        [
            Block("p", "One sentence. Another one."),
            Block("row", "0x00 | Disabled. Really."),
            Block("pre", "K: 2b7e\nr: 0001"),
        ]
    )
    assert [(u.block, u.kind, u.text) for u in found] == [
        (0, "p", "One sentence."),
        (0, "p", "Another one."),
        (1, "row", "0x00 | Disabled. Really."),
        (2, "pre", "K: 2b7e"),
        (2, "pre", "r: 0001"),
    ]


def test_cell_separators_dont_count_when_comparing():
    [row] = units([Block("row", "Status | Size: 1 octet")])
    [prose] = units([Block("p", "Status Size: 1 octet")])
    assert row.norm == prose.norm


def test_align_units_pairs_a_changed_sentence_and_finds_one_added():
    old = units(p("The passkey should be generated randomly. If entry fails, send it."))
    new = units(
        p(
            "A new passkey shall be generated randomly. Static passkeys shall not be used."
            " If entry fails, send it."
        )
    )
    assert align_units(old, new) == [(0, 0), (None, 1), (1, 2)]


def test_leftovers_pair_a_sentence_moved_into_a_table_and_reworded():
    old = units(
        p(
            "If the advertising set does not exist, then the Controller shall return the error"
            " code Unknown Advertising Identifier (0x42).",
            "Nothing else changes here.",
        )
    )
    new = units(
        [
            Block("p", "Nothing else changes here."),
            Block(
                "row",
                "MC | The advertising set does not exist. | Unknown Advertising Identifier (0x42)",
            ),
        ]
    )
    pairs = align_units(old, new)
    removed = [i for i, j in pairs if j is None]
    added = [j for i, j in pairs if i is None]
    assert pair_leftovers(old, new, removed, added) == {1: 0}


def section(number: str, title: str, *texts: str, anchor: str = "") -> Section:
    return Section(number, title, number.count(".") + 1, p(*texts), anchor=anchor)


def test_sections_match_by_id_then_heading_then_title_then_text():
    old = [
        section("1", "Scope", "This Part defines the thing.", anchor="UUID-1"),
        section("2", "Pairing", "Pairing is done like this."),
        section("3", "Keys", "Keys are generated in four steps from the random values."),
        section("4", "Old name", "The timer is reset on each received packet from the peer."),
        section("5", "Gone", "Only here."),
    ]
    new = [
        section("1", "Scope and purpose", "This Part defines it.", anchor="UUID-1"),
        section("2", "Pairing", "Pairing is done differently."),
        section("4", "Keys", "Keys are generated in four steps from the random values."),
        section("5", "New name", "The timer is reset on each received packet from the peer."),
        section("6", "[This section is no longer used]"),
    ]
    matches = match_sections(
        old, new, [units(s.blocks) for s in old], [units(s.blocks) for s in new]
    )
    assert matches == {
        0: (0, "id"),
        1: (1, "same"),
        2: (2, "renumbered"),
        3: (3, "moved"),
    }


def test_a_section_emptied_into_a_placeholder_keeps_its_number():
    old = [section("2.1", "Host Controller transport layer and AMPs", "Text about AMPs.")]
    new = [section("2.1", "[This section is no longer used]")]
    matches = match_sections(old, new, [units(old[0].blocks)], [[]])
    assert matches == {0: (0, "retitled")}


def test_parts_match_across_volumes_by_title():
    old = [
        Part(2, "D", "Error Codes", ""),
        Part(2, "E", "Host Controller Interface Functional Specification", ""),
        Part(3, "H", "Security Manager Specification", ""),
    ]
    new = [
        Part(1, "F", "Controller Error Codes", ""),
        Part(3, "H", "Security Manager (SM) Specification", ""),
        Part(4, "E", "Host Controller Interface (HCI) Functional Specification", ""),
    ]
    pairs = {(a.key if a else None, b.key if b else None) for a, b in match_parts(old, new)}
    assert pairs == {("2D", "1F"), ("3H", "3H"), ("2E", "4E")}


def test_rows_with_lines_are_compared_line_by_line():
    """6.3 to 7.0: "Channel n is enabled for CS procedure = 1" became "1 = Channel n is used
    in the CS procedure". Word by word over the whole cell, the "1 =" of the new second
    line was matched against the old first line and read as an inversion."""
    [old] = units(
        [
            Block(
                "row",
                "0xXX | Channel n is enabled for CS procedure = 1 \u00b6 Channel n is disabled"
                " for CS procedure = 0 \u00b6 At least 15 channels shall be enabled.",
            )
        ]
    )
    [new] = units(
        [
            Block(
                "row",
                "0xXX | 0 = Channel n is not used in the CS procedure \u00b6 1 = Channel n is"
                " used in the CS procedure",
            )
        ]
    )
    codes = token_opcodes(old, new)
    # every token once, in order
    assert codes[0][1] == codes[0][3] == 0
    assert all(a[2] == b[1] and a[4] == b[3] for a, b in pairwise(codes))
    assert (codes[-1][2], codes[-1][4]) == (len(old.words), len(new.words))
    # the last line goes as a whole
    last = old.words.index("At")
    assert any(
        tag in ("delete", "replace") and i1 <= last and i2 == len(old.words)
        for tag, i1, i2, _, _ in codes
    )
    # no word of a new line is matched to a word of another old line than its own
    old_line = [old.words[: k + 1].count("\u00b6") for k in range(len(old.words))]
    new_line = [new.words[: k + 1].count("\u00b6") for k in range(len(new.words))]
    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal":
            assert {old_line[k] for k in range(i1, i2)} == {new_line[k] for k in range(j1, j2)}


def test_rows_without_lines_on_both_sides_are_compared_word_by_word():
    [old] = units([Block("row", "0x00 | Off. Default.")])
    [new] = units([Block("row", "0x00 | Off. \u00b6 Default.")])
    assert [tag for tag, *_ in token_opcodes(old, new)] == ["equal", "insert", "equal"]
    assert old.norm == new.norm  # the line separator doesn't count


def test_similarity_reads_words_not_case_or_punctuation():
    [a] = units([Block("li", "Retransmission_Window,")])
    [b] = units([Block("li", "TX_Packet_Length,")])
    assert similarity(a, b) == 0
    [c] = units([Block("p", "The Link Layer shall send it.")])
    [d] = units([Block("p", "the link layer shall send it")])
    assert similarity(c, d) == 1


def test_sections_left_over_match_across_parts_by_text():
    text = (
        "Each device is shown as a column and each message as an arrow between the columns,"
        " in the order the messages are sent."
    )
    old = [units(p(text)), units(p("Something else entirely, about radio channels."))]
    new = [units(p("Nothing like the others at all here.")), units(p(text))]
    assert match_moved(old, new) == {1: 0}


def test_a_section_that_keeps_its_number_and_a_close_title_is_retitled():
    old = [section("4.5", "ServiceSearch transaction", "The client sends the request.")]
    new = [section("4.5", "Service Search transaction", "A client sends a ServiceSearch PDU.")]
    matches = match_sections(old, new, [units(old[0].blocks)], [units(new[0].blocks)])
    assert matches == {0: (0, "retitled")}

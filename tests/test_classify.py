from specdiff.classify import (
    Edit,
    drop_reworded_negations,
    editorial_kind,
    learn_rules,
    rule_of,
    signals,
)


def kind(old: str, new: str, before: str = "", prefix: str = "") -> str:
    return editorial_kind(Edit(old.split(), new.split(), before, prefix=tuple(prefix.split())))


def rules_of(edits: list[tuple[str, Edit]]) -> dict[tuple[str, str], tuple[int, int]]:
    return {(rule.old, rule.new): (rule.count, rule.sections) for rule in learn_rules(edits)}


def test_case_punctuation_and_ranges_are_format():
    assert kind("Passkey", "passkey") == "format"
    assert kind("canceled", "canceled ,") == "format"
    assert kind("3-8", "3 to 8") == "format"


def test_punctuation_swapped_is_format_but_an_operator_is_not():
    assert kind(":", ".") == "format"
    assert kind("|", "¶") == "format"
    assert kind("<", ">") == ""


def test_a_word_with_a_hyphen_or_underscore_is_a_word_not_punctuation():
    """ "ACL-U, ACL-C[+, ASB-C,] or PBD": a logical link added, not a comma."""
    assert kind("", ", ASB-C ,") == ""
    assert kind("HCI_LE_Read_PHY", "") == ""


def test_a_number_written_another_way_is_format():
    assert kind("11b", "0b11") == "format"
    assert kind("0x0A", "10") == "format"
    assert kind("0x0010", "4") == ""  # a bit mask became a bit number: not the same value


def test_a_name_written_another_way_is_naming():
    assert kind("LE Set Scan Enable", "HCI_LE_Set_Scan_Enable") == "naming"
    assert kind("a Mode Change", "an HCI_Mode_Change") == "naming"
    assert kind("the LE Set Scan Enable command", "HCI_LE_Set_Scan_Enable") == "naming"
    # a command becoming an event is not a name written another way
    assert kind("Reset command", "Reset event") == ""


def test_renumbered_references_and_conditions_are_references():
    assert kind("2.3.5", "2.3.6", before="Section") == "reference"
    assert kind("3.7", "3.10", before="Figure") == "reference"
    assert kind("B", "C", before="Part") == "reference"
    assert kind("2.4", "2.5", before="and", prefix="Sections 2.3") == "reference"
    assert kind("C204", "C.202") == "reference"
    # a number that isn't a reference is not editorial
    assert kind("2", "3", before="the") == ""


def test_requirement_letters_and_values_after_a_comma_are_not_references():
    assert kind("C.99", "O", before="]") == ""
    assert kind("Z2", "Z3", before=",") == ""


def test_other_edits_are_not_editorial():
    assert kind("provides", "does not provide") == ""
    assert kind("should", "shall") == ""


def test_signals_name_the_normative_words_and_negations_an_edit_swaps():
    found = signals(["should", "during"], ["shall", "for"])
    assert found.normative == {"+shall", "-should"}
    assert not found.negation
    found = signals(["provides"], ["does", "not", "provide"])
    assert found.negation == {"+not"}
    assert signals(["0.000001"], []).values


def test_a_negation_reworded_is_not_a_negation_added():
    assert not signals(["disabled", "for"], ["not", "used", "in", "the"]).negation
    assert not signals([], ["|", "none"]).negation


def test_numbers_that_are_places_or_notation_are_not_values():
    assert not signals(["11"], ["12"], before="Table").values
    assert not signals([], ["(", "see", "Section", "1", ")"]).values
    assert not signals(["2", "."], ["3", "."], start=True).values  # a list item's number
    assert not signals(["11b"], ["0b11"]).values
    assert signals(["20"], ["30"], before="to").values


def test_sweeping_rules_need_many_occurrences_in_many_sections():
    edits = [(f"s{i % 5}", Edit(["master"], ["central"], "the")) for i in range(8)]
    edits += [(f"s{i}", Edit(["red"], ["blue"], "the")) for i in range(3)]
    rules = rules_of(edits)
    assert ("master", "central") in rules
    assert ("red", "blue") not in rules
    assert rules[("master", "central")] == (8, 5)


def test_normative_words_are_never_sweeping():
    edits = [(f"s{i}", Edit(["should"], ["shall"], "x")) for i in range(20)]
    assert learn_rules(edits) == []


def test_words_only_added_need_twice_the_evidence():
    edits = [(f"s{i % 5}", Edit([], ["the"], "PDU")) for i in range(8)]
    assert learn_rules(edits) == []
    edits = [(f"s{i % 9}", Edit([], ["the"], "PDU")) for i in range(12)]
    assert ("", "the") in rules_of(edits)


def test_only_words_without_meaning_are_added_or_removed_everywhere():
    """ "only", "Lower or" and "insufficient" change each sentence they are added to."""
    for words in (["only"], ["Lower", "or"], ["insufficient"], ["packet"]):
        edits = [(f"s{i}", Edit([], words, "x")) for i in range(20)]
        assert learn_rules(edits) == [], words
        edits = [(f"s{i}", Edit(words, [], "x")) for i in range(20)]
        assert learn_rules(edits) == [], words


def test_limiting_words_are_never_rewritten_everywhere():
    edits = [(f"s{i}", Edit(["0x02-0xFF"], ["all", "other", "values"], "x")) for i in range(20)]
    assert learn_rules(edits) == []


def test_the_same_rewrite_of_many_identifiers_is_one_rule():
    edits = [
        (f"s{i}", Edit(["The", f"HCI_Command_{i}"], ["This"], "", prefix=())) for i in range(25)
    ]
    rules = learn_rules(edits)
    assert [(rule.old, rule.new) for rule in rules] == [("the <name>", "this")]
    assert rules[0].example == ("The HCI_Command_0", "This")
    index = {(rule.old, rule.new): k for k, rule in enumerate(rules)}
    assert rule_of(Edit(["The", "HCI_Reset"], ["This"], ""), index) == 0
    # one identifier rewritten many times is not a pattern
    edits = [(f"s{i}", Edit(["The", "HCI_Reset"], ["This"], "")) for i in range(10)]
    assert all("<name>" not in rule.old for rule in learn_rules(edits))


def test_a_rule_applies_inside_a_compound_word():
    index = {("master", "central"): 0}
    assert rule_of(Edit(["masterSCA"], ["centralSCA"], "the"), index) == 0
    assert rule_of(Edit(["masterSCA"], ["peripheralSCA"], "the"), index) is None


def test_a_title_word_added_in_references_is_sweeping_there_only():
    """5.2 renamed Vol 1, Part F to "Controller Error Codes" and every reference with it."""
    edits = [
        (f"s{i}", Edit([], ["Controller"], ",", prefix=("1", "]", "Part", "F"))) for i in range(20)
    ]
    rules = learn_rules(edits)
    assert [(rule.old, rule.new) for rule in rules] == [("", "controller")]
    index = {("", "controller"): 0}
    assert rule_of(Edit([], ["Controller"], ",", prefix=("]", "Part", "F")), index) == 0
    assert rule_of(Edit([], ["Controller"], "the", prefix=("sent", "to")), index) is None


def test_a_pattern_over_many_identifiers_is_sweeping_within_one_section():
    edits = [(f"s{i % 2}", Edit(["The", f"HCI_Command_{i}"], ["This"], "")) for i in range(25)]
    assert [(rule.old, rule.new) for rule in learn_rules(edits)] == [("the <name>", "this")]
    few = [(f"s{i % 2}", Edit(["The", f"HCI_Command_{i}"], ["This"], "")) for i in range(10)]
    assert learn_rules(few) == []


def test_a_negation_reworded_across_a_sentence_is_not_one():
    found = signals(["enabled", "for"], ["not", "used", "in"])
    assert found.negation == {"+not"}
    drop_reworded_negations(found, ["enabled", "for", "disabled", "for"], ["not", "used", "in"])
    assert not found.negation


def test_a_name_put_in_place_of_words_is_never_a_pattern():
    """ "write request" becoming "ATT_WRITE_REQ PDU" names one PDU; as a pattern it would
    also accept "write request" becoming "ATT_WRITE_CMD PDU"."""
    edits = [
        (f"s{i}", Edit(["write", "request"], [f"ATT_WRITE_{i}", "PDU"], "a")) for i in range(30)
    ]
    assert all("<name>" not in rule.new for rule in learn_rules(edits))


def test_words_that_start_like_a_negation_dont_cancel_one():
    found = signals(["ensure", "both", "match"], ["not", "initiate", "a"])
    drop_reworded_negations(found, ["disconnection", "until"], ["not", "disconnection"])
    assert found.negation == {"+not"}


def test_a_range_made_a_list_is_not_punctuation():
    assert kind("-", ",", before="1") == ""
    assert kind("-", ",", before="devices") == "format"

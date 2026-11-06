import json

from specdiff.history import ADDED, CHANGED, EDITORIAL, SAME, History
from specdiff.model import Block, Part, Section, Spec

PASSKEY = "2.3.5.3"


def spec(version: str, fmt: str, passkey: list[str], role: str, keys_number: str) -> Spec:
    sections = [
        Section("", "Security Manager", 0),
        Section(PASSKEY, "LE legacy pairing - Passkey Entry", 4, [Block("p", " ".join(passkey))]),
        Section(keys_number, "Key distribution", 2, [Block("p", "Keys are distributed last.")]),
    ]
    # the same rewrite in many sections: a sweeping edit, not a change
    sections += [
        Section(
            f"3.{i}",
            f"Procedure {i}",
            2,
            [Block("p", f"The {role} sends the request number {i}. It waits for a reply.")],
        )
        for i in range(1, 8)
    ]
    return Spec(version, fmt, "", [Part(3, "H", "Security Manager", "", sections)])


def history() -> History:
    old = [
        "The passkey Entry method provides protection against MITM attacks.",
        "If entry fails, send Pairing Failed.",
    ]
    added = [*old[:1], "Static passkeys should not be used.", old[1]]
    reversed_ = [
        "The passkey Entry method does not provide protection against MITM attacks.",
        *added[1:],
    ]
    run = History(
        [
            spec("5.2", "pdf", old, "master", "2.4"),
            spec("5.3", "pdf", added, "central", "2.5"),
            spec("5.4", "html", reversed_, "central", "2.5"),
        ]
    )
    run.run()
    return run


def lineage_of(run: History, version: int, number: str) -> str:
    return next(
        lineage for lineage, loc in run.located[version].items() if loc.section.number == number
    )


def test_sections_keep_their_lineage_through_renumbering():
    run = history()
    assert lineage_of(run, 0, "2.4") == lineage_of(run, 1, "2.5")
    assert lineage_of(run, 0, PASSKEY) == lineage_of(run, 2, PASSKEY)


def test_a_sentence_added_is_a_change_with_its_normative_word():
    run = history()
    passkey = lineage_of(run, 1, PASSKEY)
    step = run.steps[0][passkey]
    assert step.status == CHANGED
    [change] = step.changes
    assert change.kind == "add"
    assert change.new.text == "Static passkeys should not be used."
    assert change.signals.normative == {"+should"}


def test_a_rewrite_everywhere_is_sweeping_and_editorial():
    run = history()
    assert ("master", "central") in [(rule.old, rule.new) for rule in run.rules[0]]
    procedure = lineage_of(run, 0, "3.1")
    assert run.steps[0][procedure].status == EDITORIAL
    assert run.steps[1][procedure].status == SAME
    renumbered = lineage_of(run, 0, "2.4")
    assert run.steps[0][renumbered].status == EDITORIAL


def test_a_negation_is_marked_and_blamed_on_its_version():
    run = history()
    passkey = lineage_of(run, 2, PASSKEY)
    [change] = run.steps[1][passkey].changes
    assert change.kind == "mod"
    assert change.signals.negation == {"+not"}
    units = run.located[2][passkey].units
    origins = run.blame[2][passkey]
    first = dict(zip(units[0].words, origins[0], strict=True))
    assert first["not"] == 2  # written in 5.4
    assert first["protection"] == 0  # as old as the first version
    assert set(origins[1]) == {1}  # the static passkey sentence, from 5.3


def test_write_gives_the_site_its_index_steps_and_parts(tmp_path):
    run = history()
    run.write(tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    assert [v["label"] for v in index["versions"]] == ["5.2", "5.3", "5.4"]
    passkey = next(s for s in index["sections"] if s["n"] == PASSKEY)
    assert passkey["s"] == [CHANGED, CHANGED]
    assert passkey["x"] == [1, 2]  # normative in 5.3, a negation in 5.4
    assert passkey["v"] == [0, 2]
    items = json.loads((tmp_path / "steps" / "1.json").read_text())["items"]
    [item] = [i for i in items if i["id"] == passkey["id"]]
    assert item["k"] == "mod"
    assert "+not" in item["w"]
    part = json.loads((tmp_path / "parts" / "3H.json").read_text())
    stored = part["sections"][passkey["id"]]
    assert set(stored["v"]) == {"0", "1", "2"}  # its text changed in each version
    assert set(stored["d"]) == {"0", "1"}
    added_sections = [s for s in index["sections"] if ADDED in s["s"]]
    assert added_sections == []


# Spec builders for the tests below: Parts of numbered sections, each a list of blocks


def part(vol: int, letter: str, *sections: tuple[str, str, list[Block]]) -> Part:
    return Part(
        vol,
        letter,
        f"Part {letter}",
        "",
        [
            Section(number, title, number.count(".") + 1, blocks)
            for number, title, blocks in sections
        ],
    )


def run_of(*versions: tuple[str, str, list[Part]]) -> History:
    run = History([Spec(label, fmt, "", parts) for label, fmt, parts in versions])
    run.run()
    return run


FILLER = [Block("p", "This section describes how the procedure is carried out by both devices.")]


def test_a_sentence_rewritten_where_it_is_is_a_change_not_a_move():
    before = [
        Block("p", "The first sentence stays as it is."),
        Block("p", "The timer shall be reset when a packet arrives from the peer."),
        Block("p", "The last sentence stays as well."),
    ]
    after = [
        before[0],
        Block("p", "The timer is restarted whenever any new packet arrives from that peer device."),
        before[2],
    ]
    run = run_of(
        ("5.0", "html", [part(3, "H", ("1", "Timer", before))]),
        ("5.1", "html", [part(3, "H", ("1", "Timer", after))]),
    )
    [step] = run.steps[0].values()
    kinds = [entry[0] for entry in step.entries]
    assert kinds == [0, 3, 0]  # equal, changed, equal: no "moved here"


def test_an_edit_to_an_old_sentence_ranks_above_a_new_section():
    old = [Block("p", "The device should send the request.")]
    new = [Block("p", "The device shall send the request.")]
    added = [Block("p", "The Controller shall support this new feature from now on.")]
    run = run_of(
        ("5.0", "html", [part(3, "H", ("1", "Request", old))]),
        ("5.1", "html", [part(3, "H", ("1", "Request", new), ("2", "New feature", added))]),
    )
    scores = {item["k"]: item["sc"] for item in run._items(0, run._ordered_lineages())}
    assert scores["mod"] > scores["add"] > 0


def test_sentences_keep_their_id_and_steps_list_them_by_id(tmp_path):
    first = [Block("p", "One stays. Two goes away.")]
    second = [Block("p", "One stays. Three is new.")]
    third = [Block("p", "One stays, changed. Three is new.")]
    run = run_of(
        ("5.0", "html", [part(3, "H", ("1", "S", first))]),
        ("5.1", "html", [part(3, "H", ("1", "S", second))]),
        ("5.2", "html", [part(3, "H", ("1", "S", third))]),
    )
    [lineage] = run.located[0]
    one, two = run.sids[0][lineage]
    assert run.sids[1][lineage][0] == run.sids[2][lineage][0] == one
    three = run.sids[1][lineage][1]
    assert three not in (one, two)
    lineages = run._ordered_lineages()
    [step0] = run._items(0, lineages)
    [step1] = run._items(1, lineages)
    assert (step0["na"], step0["nd"]) == ([three], [two])
    assert step1["nm"] == [one]


def test_a_section_moved_to_another_part_keeps_its_lineage():
    moving = [
        Block(
            "p",
            "The notation used in message sequence charts shows each device as a column and"
            " each message as an arrow between the columns, in the order they are sent.",
        )
    ]
    run = run_of(
        (
            "6.3",
            "html",
            [part(2, "F", ("1.1", "Notation", moving)), part(1, "E", ("4", "MSC", FILLER))],
        ),
        (
            "7.0",
            "html",
            [part(2, "F"), part(1, "E", ("4", "MSC", FILLER), ("4.2.1", "Notation", moving))],
        ),
    )
    old = next(lin for lin, loc in run.located[0].items() if loc.section.title == "Notation")
    new = next(lin for lin, loc in run.located[1].items() if loc.section.title == "Notation")
    assert old == new
    assert run.steps[0][new].status == EDITORIAL  # moved and renumbered, text the same
    entry = run._section_entry(new, {})
    assert entry["p"] == "1E" and entry["pp"] == {"0": "2F"}


def test_new_table_rows_are_changes_where_the_format_changes_but_equation_scraps_are_not():
    before = [Block("row", "0x45 | Packet Too Long"), Block("eq", "x = 2")]
    after = [
        Block("row", "0x45 | Packet Too Long"),
        Block("row", "0x46 | Too Late"),
        Block("eq", "y + 3"),
        Block("p", "Equation 3. CLK27-1k+1=CLK27-1k+TSCO"),
    ]
    run = run_of(
        ("5.3", "pdf", [part(1, "F", ("1.3", "List of error codes", before))]),
        ("5.4", "html", [part(1, "F", ("1.3", "List of error codes", after))]),
    )
    [step] = run.steps[0].values()
    kinds = sorted(change.kind for change in step.changes)
    assert kinds == ["add", *["noise"] * 4]  # the row is new; the equations are re-cut
    [added] = [c for c in step.changes if c.kind == "add"]
    assert added.new is not None and added.new.text == "0x46 | Too Late"


def test_big_part_files_are_split_and_the_index_says_where(tmp_path, monkeypatch):
    import specdiff.history as history_module

    sections = [
        (str(i), f"Section {i}", [Block("p", f"Text of section {i} " * 20)]) for i in range(1, 40)
    ]
    run = run_of(
        ("5.0", "html", [part(3, "H", *sections)]),
        ("5.1", "html", [part(3, "H", *sections)]),
    )
    monkeypatch.setattr(history_module, "PART_FILE_BYTES", 5_000)
    monkeypatch.setattr(history_module, "CHUNK_BYTES", 2_000)
    run.write(tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    [entry] = index["parts"]
    assert entry["chunks"] > 1
    assert not (tmp_path / "parts" / "3H.json").exists()
    for section in index["sections"]:
        chunk = json.loads((tmp_path / "parts" / f"3H-{section['f']}.json").read_text())
        assert section["id"] in chunk["sections"]


def test_sweeping_rules_say_where_they_apply(tmp_path):
    run = history()
    run.write(tmp_path)
    steps = json.loads((tmp_path / "steps" / "0.json").read_text())
    index = json.loads((tmp_path / "index.json").read_text())
    rules = index["steps"][0]["rules"]
    k = next(k for k, rule in enumerate(rules) if rule[:2] == ["master", "central"])
    procedures = {s["id"] for s in index["sections"] if s["n"].startswith("3.")}
    assert set(steps["rules"][k]) == procedures
    part3h = json.loads((tmp_path / "parts" / "3H.json").read_text())
    lineage = next(iter(procedures))
    [change] = [e for e in part3h["sections"][lineage]["d"]["0"] if e[0] == 3]
    assert [3, "master ", k] in change[3]  # the editorial segment names its rule
    section = next(s for s in index["sections"] if s["id"] == lineage)
    assert section["er"] == {"0": [k]}


def test_a_whole_part_moving_moves_none_of_its_sections():
    """5.2 moved the HCI from Vol 2, Part E to Vol 4, Part E: its sections didn't change."""
    hci = [("7.8.11", "LE Set Scan Enable command", FILLER)]
    run = run_of(
        ("5.1", "pdf", [part(2, "E", *hci)]),
        ("5.2", "pdf", [part(4, "E", *hci)]),
    )
    [step] = run.steps[0].values()
    assert step.status == SAME


def test_a_sentence_moved_within_its_section_says_where_from():
    first = [Block("p", "Alpha comes first here. Beta comes second here. Gamma comes third.")]
    second = [Block("p", "Beta comes second here. Gamma comes third. Alpha comes first here.")]
    run = run_of(
        ("5.0", "html", [part(3, "H", ("1", "S", first))]),
        ("5.1", "html", [part(3, "H", ("1", "S", second))]),
    )
    [step] = run.steps[0].values()
    [moved] = [entry for entry in step.entries if entry[0] == 2]
    assert moved[1] == 1 and moved[5] == 0  # moved, from the old first sentence

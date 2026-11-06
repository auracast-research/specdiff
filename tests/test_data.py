"""Checks on the real history in data/history/: the changes this project was made to
find. Skipped without the data."""

import json
from pathlib import Path

import pytest

HISTORY = Path("data/history")

pytestmark = pytest.mark.skipif(
    not (HISTORY / "index.json").exists(), reason="run specdiff extract and specdiff diff first"
)


def load(path: str) -> dict:
    return json.loads((HISTORY / path).read_text(encoding="utf-8"))


def find(index: dict, part: str, number: str) -> dict:
    return next(s for s in index["sections"] if s["p"] == part and s["n"] == number)


def text_of(entries: list) -> str:
    """The text of the changed sentences of a diff, with [-removed-] and {+added+} parts."""
    marks = {1: ("[-", "-]"), 2: ("{+", "+}")}
    out = []
    for entry in entries:
        if entry[0] == 3 or (entry[0] == 2 and entry[1] == 3):
            for kind, text in entry[3]:
                left, right = marks.get(kind, ("", ""))
                out.append(f"{left}{text}{right}")
    return "".join(out)


@pytest.fixture(scope="module")
def index() -> dict:
    return load("index.json")


def step(index: dict, before: str, after: str) -> int:
    labels = [v["label"] for v in index["versions"]]
    assert labels.index(after) == labels.index(before) + 1
    return labels.index(before)


def test_le_legacy_passkey_entry_history(index):
    """Vol 3, Part H, 2.3.5.3: 5.3 adds the advice against static passkeys, 5.4 says the
    method does not protect against MITM, 6.2 makes a new passkey a shall."""
    section = find(index, "3H", "2.3.5.3")
    part = load("parts/3H.json")
    texts = part["texts"]
    diffs = part["sections"][section["id"]]["d"]

    in_53 = step(index, "5.2", "5.3")
    assert section["s"][in_53] == 3
    added = [e for e in diffs[str(in_53)] if e[0] == 2 and e[1] == 0]
    assert len(added) >= 2
    assert any("Static passkeys should not be used" in t for t in texts)

    in_54 = step(index, "5.3", "5.4")
    assert "[-provides -]{+does not provide +}" in text_of(diffs[str(in_54)])
    assert section["x"][in_54] & 2  # a negation

    in_62 = step(index, "6.1", "6.2")
    assert "[-should -]{+shall +}" in text_of(diffs[str(in_62)])
    assert section["x"][in_62] & 1  # normative


def test_hci_moved_from_vol_2_to_vol_4_in_5_2(index):
    hci = next(p for p in index["parts"] if p["key"] == "4E")
    assert "2E" in hci["from"].values()
    set_scan_enable = find(index, "4E", "7.8.11")
    assert set_scan_enable["v"][0] == 0  # followed back to 4.2


def test_master_and_slave_are_a_sweeping_edit_of_5_3(index):
    rules = index["steps"][step(index, "5.2", "5.3")]["rules"]
    found = {(was, now) for was, now, *_ in rules}
    assert ("master", "central") in found
    assert ("slave", "peripheral") in found

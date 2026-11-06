from specdiff.html import parse_part, parts_of
from specdiff.model import Block
from specdiff.pdf import _CONTINUED, _INLINE_MARKER, _join_text

PART = """
<html><body>
<section id="UUID-part"><div class="titlepage"><h3 class="title">
  <span class="formal-number">Part H</span><span class="formal-title">Security Manager</span>
</h3></div>
<section id="UUID-235"><div class="titlepage"><h6 class="title">
  <span class="formal-number"> 2.3.5</span><span class="formal-title">Pairing</span></h6></div>
  <p>The passkey <span class="emphasis"><em>TK</em></span> is b<sub>0</sub>.</p>
  <div class="itemizedlist"><ul><li><p>Phase 1</p></li><li><p>Phase 2</p>
    <div class="itemizedlist"><ul><li><p>Nested</p></li></ul></div></li></ul></div>
  <div class="note"><h3 class="title">Note</h3><p>Note: Be careful.</p></div>
  <div class="table"><table><thead><tr><th><p>Value</p></th><th><p>Description</p></th></tr>
  </thead><tbody><tr><td><p>0x00</p></td><td><p>Off.</p><p>Default.</p></td></tr></tbody>
  </table><div class="table-title">Table 2.1: Values</div></div>
  <div class="figure" id="x_figure-1"><img src="a.png"/>
    <div class="figure-title">Figure 2.1: A figure</div></div>
  <div class="literallayout"><p><span>K is 128 bits
      r is 24 bits</span></p></div>
  <div class="footnotes"><p>[1] A footnote.</p></div>
  <section id="UUID-2351"><div class="titlepage"><h6 class="title">
    <span class="formal-number">2.3.5.1</span><span class="formal-title">Sub</span></h6></div>
    <p>Sub text.</p>
  </section>
</section>
</section>
</body></html>
"""


def test_html_part_into_sections_and_blocks():
    root, pairing, sub = parse_part(PART)
    assert (root.number, root.title, root.depth) == ("", "Security Manager", 0)
    assert (pairing.number, pairing.title, pairing.depth, pairing.anchor) == (
        "2.3.5",
        "Pairing",
        3,
        "UUID-235",
    )
    assert pairing.blocks == [
        Block("p", "The passkey TK is b0."),
        Block("li", "Phase 1"),
        Block("li", "Phase 2"),
        Block("li", "Nested"),
        Block("note", "Note: Be careful."),
        Block("row", "Value | Description"),
        Block("row", "0x00 | Off. \u00b6 Default."),  # a cell's paragraphs stay lines
        Block("caption", "Table 2.1: Values"),
        Block("figure", "Figure 2.1: A figure"),
        Block("pre", "K is 128 bits\nr is 24 bits"),
    ]
    assert sub.blocks == [Block("p", "Sub text.")]


def test_index_lists_parts_under_their_volume():
    index = """
      <a href="host.html">Volume 3. Host</a>
      <a href="host/sm.html">Part H. Security Manager (SM) Specification</a>
      <a href="host/sm.html#UUID-1">2.3 Pairing</a>
      <a href="hci.html">Volume 4. Host Controller Interface</a>
      <a href="hci/e.html">Part E. Host Controller Interface (HCI) Functional Specification</a>
      <a href="host/sm.html">Part H. Security Manager (SM) Specification</a>
    """
    assert parts_of(index) == [
        (3, "H", "Security Manager (SM) Specification", "host/sm.html"),
        (4, "E", "Host Controller Interface (HCI) Functional Specification", "hci/e.html"),
    ]


VOCABULARY = {"authenticated", "man-in-the-middle", "cated"}


def test_pdf_line_end_hyphens_split_words_or_belong_to_them():
    assert _join_text("Authenti-", "cated", VOCABULARY) == "Authenticated"
    assert _join_text("active “man-in-the-", "middle”", VOCABULARY) == "active “man-in-the-middle”"
    assert _join_text("HCI_LE_Set_-", "Scan_Enable", VOCABULARY) == "HCI_LE_Set_Scan_Enable"
    assert _join_text("Own_Address_", "Type", VOCABULARY) == "Own_Address_Type"
    assert _join_text("the", "device", VOCABULARY) == "the device"


def test_pdf_list_markers_and_continued_tables():
    assert _INLINE_MARKER.match("a) Bluetooth Profile Subsystem")[1] == "a)"
    assert _INLINE_MARKER.match("• Specify the behavior")[1] == "•"
    assert _INLINE_MARKER.match("A device shall") is None
    title = "Table 3.1: Alphabetical list of commands and events (Sheet 35 of 49)"
    assert _CONTINUED.sub("", title) == "Table 3.1: Alphabetical list of commands and events"

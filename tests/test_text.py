from specdiff.text import clean, clean_lines, drop_pdf_furniture, fold, key, sentences, tokens


def test_sentences_split_after_full_stops_but_not_abbreviations():
    text = (
        "The passkey should be generated randomly (see Section 2.3.5.5). Static passkeys,"
        " e.g. 123456, should not be used. Values are in Vol. 3 here. “Quoted.” Next."
    )
    assert sentences(text) == [
        "The passkey should be generated randomly (see Section 2.3.5.5).",
        "Static passkeys, e.g. 123456, should not be used.",
        "Values are in Vol. 3 here.",
        "“Quoted.”",
        "Next.",
    ]


def test_sentences_keep_numbers_and_identifiers_whole():
    assert sentences("Wait 0.5 ms. Then send HCI_LE_Set_Scan_Enable.") == [
        "Wait 0.5 ms.",
        "Then send HCI_LE_Set_Scan_Enable.",
    ]


def test_tokens_keep_identifiers_hyphenated_words_and_numbers():
    text = "The device\u2019s man-in-the-middle HCI_LE_Read 0x0C03 2.3.5.3, \u201cok\u201d."
    assert tokens(text) == [
        "The",
        "device\u2019s",
        "man-in-the-middle",
        "HCI_LE_Read",
        "0x0C03",
        "2.3.5.3",
        ",",
        "“",
        "ok",
        "”",
        ".",
    ]


def test_clean_drops_invisible_characters_ligatures_and_symbol_font_junk():
    soft_hyphen, no_break, ligature, junk = "\u00ad", "\u00a0", "\ufb01", "\ufffd"
    text = f"HCI_LE_Set_{soft_hyphen}Scan {no_break} {ligature}ne x {junk}y"
    assert clean(text) == "HCI_LE_Set_Scan fine x y"


def test_clean_lines_keeps_lines():
    assert clean_lines("  K  is 128 bits\n\n   r is 24 bits ") == "K is 128 bits\nr is 24 bits"


def test_fold_and_key_ignore_quotes_dashes_and_case():
    assert fold("\u201cx\u201d \u2013 y") == '"x" - y'
    assert key("LE Legacy Pairing \u2013 Passkey Entry") == key("LE legacy pairing - Passkey Entry")


def test_pdf_furniture_goes_page_references_sheets_and_broken_names():
    assert drop_pdf_furniture("as in (EQ 13) on page 1333.") == "as in (EQ 13)."
    assert drop_pdf_furniture("Error Codes on page 370for a list") == "Error Codes for a list"
    assert drop_pdf_furniture("in Table 2.1 on page [!XREF] and") == "in Table 2.1 and"
    assert drop_pdf_furniture("Table 5.2: Values (Sheet 4 of 11)") == "Table 5.2: Values"
    assert drop_pdf_furniture("the TSync_ Train_Interval shall") == "the TSync_Train_Interval shall"
    assert drop_pdf_furniture("the next page 4 is") == "the next page 4 is"

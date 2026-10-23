"""The output of vsd2raw: the calls of the first page and their properties."""

from __future__ import annotations

import pytest

from weasyvsdx.raw import first_page, percent, points, properties

RAW = """startDocument()
  setDocumentMetaData(dc:title: A, B)
  startPage(draw:name: Page-1, svg:height: 8.2677in, svg:width: 11.6929in)
    setStyle(draw:fill: none, svg:stroke-width: 0.0104in)
    startTextObject (svg:x: 1in, svg:y: 2in)
      insertText (a (b), c)
    endTextObject
  endPage
  startPage(draw:name: Page-2)
    insertText (second page)
  endPage
endDocument
"""


def test_the_calls_of_the_first_page() -> None:
    assert first_page(RAW) == [
        ("startPage", "draw:name: Page-1, svg:height: 8.2677in, svg:width: 11.6929in"),
        ("setStyle", "draw:fill: none, svg:stroke-width: 0.0104in"),
        ("startTextObject", "svg:x: 1in, svg:y: 2in"),
        ("insertText", "a (b), c"),
        ("endTextObject", ""),
        ("endPage", ""),
    ]


def test_a_line_that_is_no_call_is_skipped() -> None:
    assert first_page("startPage()\n  ??? not a call\n  insertText without parentheses\n  endPage\n") == [("startPage", ""), ("endPage", "")]


def test_properties_keep_a_list_in_parentheses_whole() -> None:
    text = "fo:line-height: 130.0000%, style:tab-stops: ((style:position: 0.1500in, style:type: left)), fo:text-align: left"
    assert properties(text) == {"fo:line-height": "130.0000%", "style:tab-stops": "((style:position: 0.1500in, style:type: left))", "fo:text-align": "left"}


def test_a_value_may_hold_a_comma() -> None:
    assert properties("dc:title: A, B, dc:subject: C") == {"dc:title": "A, B", "dc:subject": "C"}
    assert properties("stray, fo:color: #000000") == {"fo:color": "#000000"}
    assert properties("style:font-name: Segoe UI,Bold, fo:font-size: 9pt") == {"style:font-name": "Segoe UI,Bold", "fo:font-size": "9pt"}


@pytest.mark.parametrize(("value", "expected"), [("1in", 72.0), ("0.5in", 36.0), ("12.0000pt", 12.0), ("-0.25in", -18.0), ("2", 144.0), (None, 0.0), ("", 0.0), ("wide", 0.0)])
def test_points(value: str | None, expected: float) -> None:
    assert points(value) == expected


@pytest.mark.parametrize(("value", "expected"), [("120.0000%", 1.2), ("100%", 1.0), (None, 0.5), ("1.2", 0.5), ("x%", 0.5)])
def test_percent(value: str | None, expected: float) -> None:
    assert percent(value, 0.5) == expected

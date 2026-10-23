"""The text of a drawing as HTML in a foreignObject."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from weasyvsdx.raw import first_page
from weasyvsdx.text import SVG_NS, XHTML_NS, TextObject, foreign_object, plain, replace_text, text_background, text_objects

BLOCK = (
    "draw:textarea-vertical-align: middle, fo:padding-bottom: 0.0556in, fo:padding-left: 0.0833in, fo:padding-right: 0.0833in, fo:padding-top: 0.0556in, "
    "librevenge:rotate: 0.0000, svg:height: 0.3543in, svg:width: 5.6759in, svg:x: 2.9856in, svg:y: 1.1811in"
)
PARAGRAPH = "fo:line-height: 120.0000%, fo:margin-bottom: 0.0000in, fo:margin-left: 0.0000in, fo:margin-right: 0.0000in, fo:margin-top: 0.0000in, fo:text-align: center, fo:text-indent: 0.0000in, style:tab-stop-distance: 0.5906in"
SPAN = "fo:color: #000000, fo:font-size: 12.0000pt, style:font-name: Calibri, svg:fill-opacity: 100.0000%, svg:stroke-opacity: 100.0000%"


def page(*calls: str) -> str:
    return "startPage()\n" + "\n".join(calls) + "\nendPage\n"


def html(element: ET.Element) -> ET.Element:
    """The div of the foreignObject, read back as the XHTML it is serialized to."""
    div: ET.Element = ET.fromstring(ET.tostring(element[0]))
    return div


def test_paragraphs_and_spans_of_a_text_object() -> None:
    raw = page(
        f"startTextObject ({BLOCK})",
        f"openParagraph ({PARAGRAPH})",
        f"openSpan({SPAN})",
        "insertText (Hello)",
        "insertSpace",
        "insertText (world)",
        "insertTab",
        "insertLineBreak",
        # A field gets no text: libvisio gives its value as text already
        "insertField (text:field-type: page-number)",
        "closeSpan",
        "closeParagraph",
        "endTextObject",
        "insertText (outside any text object)",
    )
    [text] = text_objects(first_page(raw))
    [paragraph] = text.paragraphs
    assert paragraph.properties["fo:text-align"] == "center"
    assert ["".join(span.text) for span in paragraph.spans] == ["Hello world\t\n"]


def test_a_span_outside_a_paragraph_gets_one() -> None:
    [text] = text_objects(first_page(page("startTextObject ()", f"openSpan({SPAN})", "insertText (a)", "closeSpan", "endTextObject")))
    assert [[span.text for span in paragraph.spans] for paragraph in text.paragraphs] == [[["a"]]]


def test_text_between_spans_is_dropped() -> None:
    [text] = text_objects(first_page(page("startTextObject ()", f"openParagraph ({PARAGRAPH})", "insertText (stray)", "closeParagraph", "endTextObject")))
    assert text.paragraphs[0].spans == []


def test_a_bulleted_list() -> None:
    raw = page(
        "startTextObject ()",
        "openUnorderedListLevel(fo:font-size: 100.0000%, librevenge:level: 1, text:bullet-char: •, text:min-label-width: 0.2500in)",
        "openListElement(fo:margin-left: 0.2500in, fo:text-indent: -0.2500in, fo:text-align: left)",
        f"openSpan({SPAN})",
        "insertText (item)",
        "closeSpan",
        "closeListElement",
        "closeUnorderedListLevel",
        "openOrderedListLevel(librevenge:level: 1)",
        "openListElement(fo:text-align: left)",
        "closeListElement",
        "closeOrderedListLevel",
        "openParagraph ()",
        "closeParagraph",
        "endTextObject",
    )
    [text] = text_objects(first_page(raw))
    assert [(paragraph.bullet, paragraph.label_width) for paragraph in text.paragraphs] == [("•", 18.0), ("", 0.0), (None, 0.0)]
    div = html(foreign_object(text))
    item = div[0]
    assert item[0].text == "•"
    assert "width:18px" in (item[0].get("style") or "")
    assert "margin:0px 0px 0px 18px" in (item.get("style") or "")
    assert "text-indent:-18px" in (item.get("style") or "")
    # An empty paragraph keeps its line
    assert div[2][0].tag == f"{{{XHTML_NS}}}br"


def test_the_foreign_object_takes_the_text_block() -> None:
    [text] = text_objects(first_page(page(f"startTextObject ({BLOCK})", f"openParagraph ({PARAGRAPH})", f"openSpan({SPAN})", "insertText (test)", "closeSpan", "closeParagraph", "endTextObject")))
    element = foreign_object(text)
    assert element.tag == f"{{{SVG_NS}}}foreignObject"
    assert {name: element.get(name) for name in ("x", "y", "width", "height")} == {"x": "214.963", "y": "85.0392", "width": "408.665", "height": "25.5096"}
    assert element.get("transform") is None
    div = html(element)
    assert div.tag == f"{{{XHTML_NS}}}div"
    style = div.get("style") or ""
    assert "justify-content:center" in style
    assert "padding:4.0032px 5.9976px 4.0032px 5.9976px" in style
    paragraph = div[0]
    assert "text-align:center" in (paragraph.get("style") or "")
    assert "line-height:1.2" in (paragraph.get("style") or "")
    assert "flex-shrink:0" in (paragraph.get("style") or "")
    span = paragraph[0]
    assert span.text == "test"
    assert span.get("style") == 'font-family:"Calibri", "Carlito", sans-serif;font-size:12px;color:#000000'


def test_a_turned_text_block_turns_about_its_center() -> None:
    [text] = text_objects(first_page(page("startTextObject (librevenge:rotate: 90.0000, svg:x: 1in, svg:y: 1in, svg:width: 2in, svg:height: 1in)", "endTextObject")))
    assert foreign_object(text).get("transform") == "rotate(90 144 108)"


def test_the_style_of_a_span() -> None:
    span = (
        'fo:color: #ff0000, fo:font-size: 9pt, fo:font-weight: bold, fo:font-style: italic, style:font-name: Se\\go"e UI, svg:fill-opacity: 50.0000%, '
        "fo:background-color: #ffff00, style:text-underline-type: single, style:text-position: super 58%"
    )
    [text] = text_objects(first_page(page("startTextObject ()", "openParagraph ()", f"openSpan({span})", "insertText (x)", "closeSpan", "openSpan(style:text-position: sub 58%)", "closeSpan", "closeParagraph", "endTextObject")))
    first, second = html(foreign_object(text))[0]
    assert first.get("style") == ('font-family:"Segoe UI", "Selawik", sans-serif;font-size:9px;font-weight:bold;font-style:italic;color:#ff0000;opacity:0.5;background-color:#ffff00;text-decoration:underline;vertical-align:super')
    assert second.get("style") == "vertical-align:sub"


def test_vertical_alignment_and_defaults() -> None:
    calls = [line for align in ("top", "bottom", "odd") for line in (f"startTextObject (draw:textarea-vertical-align: {align})", "endTextObject")]
    [top, bottom, unknown] = text_objects(first_page(page(*calls)))
    assert "justify-content:flex-start" in (html(foreign_object(top)).get("style") or "")
    assert "justify-content:flex-end" in (html(foreign_object(bottom)).get("style") or "")
    assert "justify-content:flex-start" in (html(foreign_object(unknown)).get("style") or "")


def test_each_text_becomes_its_foreign_object_in_place() -> None:
    svg = ET.fromstring(f'<svg xmlns="{SVG_NS}"><g><path/><text>a</text></g><text>b</text></svg>')
    objects = text_objects(first_page(page("startTextObject (svg:x: 1in, svg:width: 1in, svg:height: 1in)", "endTextObject", "startTextObject (svg:x: 2in, svg:width: 1in, svg:height: 1in)", "endTextObject")))
    assert replace_text(svg, objects)
    assert [child.tag for child in svg[0]] == [f"{{{SVG_NS}}}path", f"{{{SVG_NS}}}foreignObject"]
    assert svg[0][1].get("x") == "72"
    assert svg[1].get("x") == "144"


def test_a_hidden_text_goes() -> None:
    svg = ET.fromstring(f'<svg xmlns="{SVG_NS}"><g><text>a</text></g><text>b</text></svg>')
    objects = text_objects(first_page(page("startTextObject ()", f"openSpan({SPAN})", "insertText (User)", "closeSpan", "endTextObject", "startTextObject ()", "endTextObject")))
    assert [plain(item) for item in objects] == ["User", ""]
    assert replace_text(svg, objects, frozenset({0}))
    assert list(svg[0]) == []
    assert svg[1].tag == f"{{{SVG_NS}}}foreignObject"


def test_other_counts_leave_the_text_alone() -> None:
    svg = ET.fromstring(f'<svg xmlns="{SVG_NS}"><text>a</text></svg>')
    assert not replace_text(svg, [])
    assert svg[0].tag == f"{{{SVG_NS}}}text"


def test_a_paragraph_takes_the_font_of_its_first_span() -> None:
    raw = page("startTextObject ()", "openParagraph ()", "closeParagraph", "openParagraph ()", f"openSpan({SPAN.replace('12.0000pt', '6pt')})", "insertText (a)", "closeSpan", "closeParagraph", "endTextObject")
    [text] = text_objects(first_page(raw))
    empty, full = html(foreign_object(text))
    # The empty paragraph takes the font of the first span of the block
    assert 'font-family:"Calibri", "Carlito", sans-serif;font-size:6px' in (empty.get("style") or "")
    assert "font-size:6px" in (full.get("style") or "")


def test_a_font_of_microsoft_gets_its_free_replacement() -> None:
    names = ["Segoe UI Semibold", "Cambria", "Arial"]
    calls = [f"openSpan(style:font-name: {name})" for name in names]
    [text] = text_objects(first_page(page("startTextObject ()", "openParagraph ()", *[line for call in calls for line in (call, "insertText (a)", "closeSpan")], "closeParagraph", "endTextObject")))
    styles = [span.get("style") for span in html(foreign_object(text))[0]]
    assert styles == ['font-family:"Segoe UI Semibold", "Selawik Semibold", sans-serif', 'font-family:"Cambria", "Caladea", sans-serif', 'font-family:"Arial", sans-serif']


def scaled(*scales: str) -> TextObject:
    spans = [line for scale in scales for line in (f"openSpan(style:text-scale: {scale})", "insertText (a)", "closeSpan")]
    [text] = text_objects(first_page(page("startTextObject (svg:x: 1in, svg:width: 2in, fo:padding-left: 0.5in, fo:padding-top: 0.5in)", "openParagraph ()", *spans, "closeParagraph", "endTextObject")))
    return text


def test_a_scaled_font_lays_out_narrower_and_stretches() -> None:
    element = foreign_object(scaled("200.0000%", "200%"))
    assert element.get("width") == "72"
    assert element.get("transform") == "translate(72 0) scale(2 1) translate(-72 0)"
    style = html(element).get("style") or ""
    assert "width:72px" in style
    assert "padding:36px 0px 0px 18px" in style


def test_a_turned_and_scaled_block_turns_first() -> None:
    [text] = text_objects(
        first_page(
            page("startTextObject (librevenge:rotate: 90, svg:x: 1in, svg:y: 1in, svg:width: 2in, svg:height: 1in)", "openParagraph ()", "openSpan(style:text-scale: 50%)", "insertText (a)", "closeSpan", "closeParagraph", "endTextObject")
        )
    )
    assert foreign_object(text).get("transform") == "rotate(90 144 108) translate(72 0) scale(0.5 1) translate(-72 0)"


def test_mixed_or_odd_scales_lay_out_unscaled() -> None:
    for text in (scaled("200%", "100%"), scaled("0%")):
        element = foreign_object(text)
        assert element.get("width") == "144"
        assert element.get("transform") is None


def test_a_block_of_no_width_is_as_wide_as_its_text() -> None:
    def block(align: str | None, vertical: str) -> ET.Element:
        paragraph = f"openParagraph (fo:text-align: {align})" if align else "openParagraph ()"
        calls = (
            f"startTextObject (draw:textarea-vertical-align: {vertical}, svg:x: 1in, svg:y: 1in, svg:width: 0in, svg:height: 0in)",
            paragraph,
            f"openSpan({SPAN})",
            "insertText (Stream Analytics)",
            "closeSpan",
            "closeParagraph",
            "endTextObject",
        )
        [text] = text_objects(first_page(page(*calls)))
        return foreign_object(text)

    centered = block(None, "middle")
    assert {name: centered.get(name) for name in ("x", "y", "width", "height")} == {"x": "-928", "y": "-928", "width": "2000", "height": "2000"}
    assert "white-space:pre;" in (html(centered).get("style") or "")
    # The text of a paragraph with no alignment centers on the point, as the block does
    assert "text-align:center" in (html(centered).get("style") or "")
    left, right = block("left", "top"), block("end", "bottom")
    assert (left.get("x"), left.get("y")) == ("72", "72")
    assert (right.get("x"), right.get("y")) == ("-1928", "-1928")


def test_a_block_with_a_width_wraps() -> None:
    [text] = text_objects(first_page(page(f"startTextObject ({BLOCK})", "endTextObject")))
    assert "white-space:pre-wrap" in (html(foreign_object(text)).get("style") or "")
    assert "text-align" not in (html(foreign_object(text)).get("style") or "")


@pytest.mark.parametrize(
    ("background", "color", "expected"),
    [
        # Black behind dark text: the palette white that libvisio reads as black
        ("#000000", "#000000", "#ffffff"),
        ("#000000", "#0070c0", "#ffffff"),
        # Light text on black, and any other background, stay
        ("#000000", "#ffffff", "#000000"),
        ("#ffff00", "#000000", "#ffff00"),
        ("#000000", "red", "#ffffff"),
        ("#000000", "#zzzzzz", "#ffffff"),
    ],
)
def test_black_behind_dark_text_is_white(background: str, color: str, expected: str) -> None:
    assert text_background(background, color) == expected


def test_a_line_separator_breaks_the_line() -> None:
    raw = page("startTextObject ()", f"openParagraph ({PARAGRAPH})", f"openSpan({SPAN})", "insertText (Transparency Geometry Width)", "closeSpan", "closeParagraph", "endTextObject")
    [text] = text_objects(first_page(raw))
    assert text.paragraphs[0].spans[0].text == ["Transparency\nGeometry\nWidth"]

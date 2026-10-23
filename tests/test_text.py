"""The text of a drawing as HTML in a foreignObject."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from weasyvsdx.raw import first_page
from weasyvsdx.text import SVG_NS, XHTML_NS, foreign_object, replace_text, text_objects

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
    assert span.get("style") == 'font-family:"Calibri", sans-serif;font-size:12px;color:#000000'


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
    assert first.get("style") == ('font-family:"Segoe UI", sans-serif;font-size:9px;font-weight:bold;font-style:italic;color:#ff0000;opacity:0.5;background-color:#ffff00;text-decoration:underline;vertical-align:super')
    assert second.get("style") == "vertical-align:sub"


def test_vertical_alignment_and_defaults() -> None:
    calls = [line for align in ("top", "bottom", "odd") for line in (f"startTextObject (draw:textarea-vertical-align: {align})", "endTextObject")]
    [top, bottom, unknown] = text_objects(first_page(page(*calls)))
    assert "justify-content:flex-start" in (html(foreign_object(top)).get("style") or "")
    assert "justify-content:flex-end" in (html(foreign_object(bottom)).get("style") or "")
    assert "justify-content:flex-start" in (html(foreign_object(unknown)).get("style") or "")


def test_each_text_becomes_its_foreign_object_in_place() -> None:
    svg = ET.fromstring(f'<svg xmlns="{SVG_NS}"><g><path/><text>a</text></g><text>b</text></svg>')
    objects = text_objects(first_page(page("startTextObject (svg:x: 1in)", "endTextObject", "startTextObject (svg:x: 2in)", "endTextObject")))
    assert replace_text(svg, objects)
    assert [child.tag for child in svg[0]] == [f"{{{SVG_NS}}}path", f"{{{SVG_NS}}}foreignObject"]
    assert svg[0][1].get("x") == "72"
    assert svg[1].get("x") == "144"


def test_other_counts_leave_the_text_alone() -> None:
    svg = ET.fromstring(f'<svg xmlns="{SVG_NS}"><text>a</text></svg>')
    assert not replace_text(svg, [])
    assert svg[0].tag == f"{{{SVG_NS}}}text"


def test_a_paragraph_takes_the_font_of_its_first_span() -> None:
    raw = page("startTextObject ()", "openParagraph ()", "closeParagraph", "openParagraph ()", f"openSpan({SPAN.replace('12.0000pt', '6pt')})", "insertText (a)", "closeSpan", "closeParagraph", "endTextObject")
    [text] = text_objects(first_page(raw))
    empty, full = html(foreign_object(text))
    # The empty paragraph takes the font of the first span of the block
    assert 'font-family:"Calibri", sans-serif;font-size:6px' in (empty.get("style") or "")
    assert "font-size:6px" in (full.get("style") or "")

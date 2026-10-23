"""The text of a drawing as HTML in a foreignObject, laid out by WeasyPrint.

vsd2xhtml writes each text object as one SVG ``<text>`` at the left edge of its block. The generic SVG
generator of librevenge drops what lays the text out: the width of the block, its padding, the alignment
of each paragraph, line breaks and lists. So labels do not wrap and leave the shapes they belong to.

vsd2raw prints the same calls of libvisio with all their properties. Both tools walk the drawing in one
order, so the n-th text object of the first page in the one is the n-th ``<text>`` in the other. Each
``<text>`` becomes a ``<foreignObject>`` of the size of the text block, with the paragraphs and spans as
HTML: weasysvg lays it out, so it wraps and aligns as in Visio. A page whose counts differ keeps its text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from .raw import Call, Properties, percent, points, properties

SVG_NS = "http://www.w3.org/2000/svg"
XHTML_NS = "http://www.w3.org/1999/xhtml"
# Free fonts in place of the fonts of Microsoft that Visio drawings ask for most: Carlito and Caladea share
# the metrics of Calibri and Cambria, so text breaks where Visio breaks it; Selawik is the open fallback
# Microsoft made for Segoe UI, close to it but not equal. Each comes after the font itself, so an installed
# original still wins.
REPLACEMENTS = {
    "calibri": "Carlito",
    "cambria": "Caladea",
    "segoe ui": "Selawik",
    "segoe ui light": "Selawik Light",
    "segoe ui semilight": "Selawik Semilight",
    "segoe ui semibold": "Selawik Semibold",
}
VERTICAL = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}
ALIGN = {"left": "left", "center": "center", "right": "right", "end": "right", "justify": "justify", "start": "left"}


@dataclass
class Span:
    properties: Properties
    text: list[str] = field(default_factory=list)


@dataclass
class Paragraph:
    properties: Properties
    spans: list[Span] = field(default_factory=list)
    bullet: str | None = None
    label_width: float = 0.0


@dataclass
class TextObject:
    properties: Properties
    paragraphs: list[Paragraph] = field(default_factory=list)


def text_objects(calls: list[Call]) -> list[TextObject]:
    """The text objects among the calls of a page, in their order."""
    objects: list[TextObject] = []
    current: TextObject | None = None
    paragraph: Paragraph | None = None
    span: Span | None = None
    bullet: str | None = None
    label_width = 0.0
    for name, argument in calls:
        if name == "startTextObject":
            current = TextObject(properties(argument))
            objects.append(current)
        elif name == "endTextObject":
            current = paragraph = span = None
        elif current is None:
            continue
        elif name in ("openUnorderedListLevel", "openOrderedListLevel"):
            level = properties(argument)
            # An ordered list gets no numbers: libvisio gives none, and Visio diagrams hardly use them
            bullet = level.get("text:bullet-char", "•") if name == "openUnorderedListLevel" else ""
            label_width = points(level.get("text:min-label-width"))
        elif name in ("closeUnorderedListLevel", "closeOrderedListLevel"):
            bullet = None
        elif name in ("openParagraph", "openListElement"):
            paragraph = Paragraph(properties(argument), bullet=bullet if name == "openListElement" else None, label_width=label_width)
            current.paragraphs.append(paragraph)
        elif name in ("closeParagraph", "closeListElement"):
            paragraph = span = None
        elif name == "openSpan":
            if paragraph is None:
                paragraph = Paragraph({})
                current.paragraphs.append(paragraph)
            span = Span(properties(argument))
            paragraph.spans.append(span)
        elif name == "closeSpan":
            span = None
        elif span is not None:
            piece = {"insertText": argument, "insertSpace": " ", "insertTab": "\t", "insertLineBreak": "\n"}.get(name)
            if piece is not None:
                span.text.append(piece)
    return objects


def css(declarations: dict[str, str]) -> str:
    return ";".join(f"{name}:{value}" for name, value in declarations.items())


def length(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") + "px"


def font(props: Properties) -> dict[str, str]:
    """The font family and size of a span."""
    style = {}
    if "style:font-name" in props:
        # A font the system lacks falls back to its replacement, else to sans-serif, as Visio diagrams
        # mostly use sans-serif fonts
        family = props["style:font-name"].replace("\\", "").replace('"', "")
        families = [family, REPLACEMENTS.get(family.lower())]
        style["font-family"] = ", ".join(f'"{name}"' for name in families if name) + ", sans-serif"
    if "fo:font-size" in props:
        style["font-size"] = length(points(props["fo:font-size"], 12.0))
    return style


def span_style(span: Span) -> str:
    props = span.properties
    style = font(props)
    if "fo:font-weight" in props:
        style["font-weight"] = props["fo:font-weight"]
    if "fo:font-style" in props:
        style["font-style"] = props["fo:font-style"]
    if "fo:color" in props:
        style["color"] = props["fo:color"]
        opacity = percent(props.get("svg:fill-opacity"), 1.0)
        if opacity < 1:
            style["opacity"] = f"{opacity:g}"
    if "fo:background-color" in props:
        style["background-color"] = props["fo:background-color"]
    if props.get("style:text-underline-type", "none") != "none":
        style["text-decoration"] = "underline"
    position = props.get("style:text-position", "")
    if position.startswith("super"):
        style["vertical-align"] = "super"
    elif position.startswith("sub"):
        style["vertical-align"] = "sub"
    return css(style)


def paragraph_style(paragraph: Paragraph, fallback: Properties) -> str:
    """The style of a paragraph, its font that of its first span, else the fallback."""
    props = paragraph.properties
    # A paragraph never shrinks: Visio stores blocks lower than their text, which then overflows them
    style = {"margin": "0", "flex-shrink": "0"}
    # Each line holds a strut of the font of its paragraph: with the 16px of HTML, small text would get
    # lines far apart
    style.update(font(paragraph.spans[0].properties if paragraph.spans else fallback))
    if "fo:text-align" in props:
        style["text-align"] = ALIGN.get(props["fo:text-align"], "left")
    style["line-height"] = f"{percent(props.get('fo:line-height'), 1.2):g}"
    margins = [points(props.get(f"fo:margin-{side}")) for side in ("top", "right", "bottom", "left")]
    if any(margins):
        style["margin"] = " ".join(length(margin) for margin in margins)
    indent = points(props.get("fo:text-indent"))
    if indent:
        style["text-indent"] = length(indent)
    if "style:tab-stop-distance" in props:
        style["tab-size"] = length(points(props["style:tab-stop-distance"]))
    return css(style)


def foreign_object(text: TextObject) -> ET.Element:
    """The text object as a foreignObject of the size of its text block."""
    props = text.properties
    x, y = points(props.get("svg:x")), points(props.get("svg:y"))
    width, height = points(props.get("svg:width")), points(props.get("svg:height"))
    element = ET.Element(f"{{{SVG_NS}}}foreignObject", {"x": f"{x:g}", "y": f"{y:g}", "width": f"{width:g}", "height": f"{height:g}", "style": "overflow:visible"})
    angle = float(props.get("librevenge:rotate", "0") or 0)
    if angle:
        # About the center of the block, as the SVG generator of librevenge turns its <text>
        element.set("transform", f"rotate({angle:g} {x + width / 2:g} {y + height / 2:g})")
    padding = " ".join(length(points(props.get(f"fo:padding-{side}"))) for side in ("top", "right", "bottom", "left"))
    box = {
        "box-sizing": "border-box",
        "width": length(width),
        "height": length(height),
        "padding": padding,
        "display": "flex",
        "flex-direction": "column",
        "justify-content": VERTICAL.get(props.get("draw:textarea-vertical-align", "top"), "flex-start"),
        "white-space": "pre-wrap",
        "overflow-wrap": "break-word",
    }
    # The XHTML namespace as an attribute, as convert.serialize() writes the SVG one: tostring() would give
    # the qualified tags a prefix of its own
    block = ET.SubElement(element, "div", {"xmlns": XHTML_NS, "style": css(box)})
    first = next((paragraph.spans[0].properties for paragraph in text.paragraphs if paragraph.spans), {})
    for paragraph in text.paragraphs:
        node = ET.SubElement(block, "p", {"style": paragraph_style(paragraph, first)})
        if paragraph.bullet is not None:
            # The bullet hangs in the indent of the paragraph, in a box as wide as the label
            label = ET.SubElement(node, "span", {"style": css({"display": "inline-block", "width": length(paragraph.label_width), "text-indent": "0"})})
            label.text = paragraph.bullet
        for span in paragraph.spans:
            ET.SubElement(node, "span", {"style": span_style(span)}).text = "".join(span.text)
        if not any("".join(span.text) for span in paragraph.spans) and paragraph.bullet is None:
            # An empty paragraph keeps its line, as in Visio
            ET.SubElement(node, "br")
    return element


def replace_text(svg: ET.Element, objects: list[TextObject]) -> bool:
    """Replace each <text> of the page with its foreignObject. False, and nothing changed, when the counts differ."""
    # In document order, the order of the calls: a <text> of the page comes after one in a group before it
    texts = list(svg.iter(f"{{{SVG_NS}}}text"))
    if len(texts) != len(objects):
        return False
    parents = {child: parent for parent in svg.iter() for child in parent}
    for element, text in zip(texts, objects, strict=True):
        parent = parents[element]
        parent[list(parent).index(element)] = foreign_object(text)
    return True

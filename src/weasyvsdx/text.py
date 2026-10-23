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

from collections.abc import Callable
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
# A text block of no width or height is sized by its text in Visio (TEXTWIDTH, TEXTHEIGHT), which libvisio
# cannot evaluate: it gives 0, and SVG draws no foreignObject of no size. Such a block is laid out in this
# many points instead, placed by its point as its alignment places the text.
AUTO_SIZE = 2000.0
ANCHOR = {"left": 0.0, "start": 0.0, "justify": 0.0, "center": 0.5, "right": 1.0, "end": 1.0}
VERTICAL_ANCHOR = {"top": 0.0, "middle": 0.5, "bottom": 1.0}
VERTICAL = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}
TEXT_ALIGN = "fo:text-align"
# Text darker than this luminance does not read on black
DARK = 0.5
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


class _Reader:
    """Collects the text objects of a page, one call at a time: each call has its method."""

    PIECES = {"insertText": None, "insertSpace": " ", "insertTab": "\t", "insertLineBreak": "\n"}

    def __init__(self) -> None:
        self.objects: list[TextObject] = []
        self.current: TextObject | None = None
        self.paragraph: Paragraph | None = None
        self.span: Span | None = None
        self.bullet: str | None = None
        self.label_width = 0.0

    def read(self, name: str, argument: str) -> None:
        if name == "startTextObject":
            self.current = TextObject(properties(argument))
            self.objects.append(self.current)
        elif name == "endTextObject":
            self.current = self.paragraph = self.span = None
        elif self.current is not None:
            handler = self.HANDLERS.get(name)
            if handler is not None:
                handler(self, name, argument)
            elif name in self.PIECES and self.span is not None:
                self.span.text.append(self.PIECES[name] or argument)

    def open_list(self, name: str, argument: str) -> None:
        level = properties(argument)
        # libvisio opens unordered lists only: Visio has no numbered lists
        self.bullet = level.get("text:bullet-char", "\u2022") if name == "openUnorderedListLevel" else ""
        self.label_width = points(level.get("text:min-label-width"))

    def close_list(self, name: str, argument: str) -> None:
        self.bullet = None

    def open_paragraph(self, name: str, argument: str) -> None:
        assert self.current is not None
        self.paragraph = Paragraph(properties(argument), bullet=self.bullet if name == "openListElement" else None, label_width=self.label_width)
        self.current.paragraphs.append(self.paragraph)

    def close_paragraph(self, name: str, argument: str) -> None:
        self.paragraph = self.span = None

    def open_span(self, name: str, argument: str) -> None:
        assert self.current is not None
        if self.paragraph is None:
            self.paragraph = Paragraph({})
            self.current.paragraphs.append(self.paragraph)
        self.span = Span(properties(argument))
        self.paragraph.spans.append(self.span)

    def close_span(self, name: str, argument: str) -> None:
        self.span = None

    HANDLERS: dict[str, Callable[[_Reader, str, str], None]] = {
        "openUnorderedListLevel": open_list,
        "openOrderedListLevel": open_list,
        "closeUnorderedListLevel": close_list,
        "closeOrderedListLevel": close_list,
        "openParagraph": open_paragraph,
        "openListElement": open_paragraph,
        "closeParagraph": close_paragraph,
        "closeListElement": close_paragraph,
        "openSpan": open_span,
        "closeSpan": close_span,
    }


def text_objects(calls: list[Call]) -> list[TextObject]:
    """The text objects among the calls of a page, in their order."""
    reader = _Reader()
    for name, argument in calls:
        reader.read(name, argument)
    return reader.objects


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


def luminance(color: str) -> float:
    """The relative luminance of a #rrggbb color, 0 for black to 1 for white; 0 for another notation."""
    if len(color) != 7 or not color.startswith("#"):
        return 0.0
    try:
        red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    except ValueError:
        return 0.0
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def text_background(background: str, color: str) -> str:
    """The text background libvisio gives, white where it gives black behind dark text.

    Visio stores the background as an index into its palette, white being 2. libvisio 0.1.7 takes the RGB
    bytes next to the index of a VSD, which are 0 for a palette color, and so writes black: the dimensions of
    a floor plan became black bars. Text that dark on black never reads, so black behind it means white.
    """
    if background.lower() == "#000000" and luminance(color) < DARK:
        return "#ffffff"
    return background


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
        style["background-color"] = text_background(props["fo:background-color"], props.get("fo:color", "#000000"))
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
    if TEXT_ALIGN in props:
        style["text-align"] = ALIGN.get(props[TEXT_ALIGN], "left")
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


def paragraph_align(text: TextObject) -> str:
    """The alignment of the first paragraph, which places a block of no width; centered in Visio by default."""
    return next((paragraph.properties[TEXT_ALIGN] for paragraph in text.paragraphs if TEXT_ALIGN in paragraph.properties), "center")


def text_scale(text: TextObject) -> float:
    """The horizontal scale of the glyphs that all spans with text share, else 1."""
    scales = {percent(span.properties.get("style:text-scale"), 1.0) for paragraph in text.paragraphs for span in paragraph.spans if "".join(span.text)}
    scale = scales.pop() if len(scales) == 1 else 1.0
    return scale if scale > 0 else 1.0


def foreign_object(text: TextObject) -> ET.Element:
    """The text object as a foreignObject of the size of its text block."""
    props = text.properties
    x, y = points(props.get("svg:x")), points(props.get("svg:y"))
    width, height = points(props.get("svg:width")), points(props.get("svg:height"))
    scale = text_scale(text)
    center_x, center_y = x + width / 2, y + height / 2
    auto_width = width <= 0
    box_x, box_y, laid_width, height = layout_box(text, scale)
    element = ET.Element(f"{{{SVG_NS}}}foreignObject", {"x": f"{box_x:g}", "y": f"{box_y:g}", "width": f"{laid_width:g}", "height": f"{height:g}", "style": "overflow:visible"})
    transforms = []
    angle = float(props.get("librevenge:rotate", "0") or 0)
    if angle:
        # About the center of the block, as the SVG generator of librevenge turns its <text>
        transforms.append(f"rotate({angle:g} {center_x:g} {center_y:g})")
    if scale != 1:
        transforms.append(f"translate({x:g} 0) scale({scale:g} 1) translate({-x:g} 0)")
    if transforms:
        element.set("transform", " ".join(transforms))
    # The padding keeps its size after the stretch
    padding = " ".join(length(points(props.get(f"fo:padding-{side}")) / (scale if side in ("left", "right") else 1)) for side in ("top", "right", "bottom", "left"))
    box = {
        "box-sizing": "border-box",
        "width": length(laid_width),
        "height": length(height),
        "padding": padding,
        "display": "flex",
        "flex-direction": "column",
        "justify-content": VERTICAL.get(props.get("draw:textarea-vertical-align", "top"), "flex-start"),
        # A block of no width is as wide as its text in Visio, which never breaks it
        "white-space": "pre" if auto_width else "pre-wrap",
        # and its text aligns as the block is placed, else a paragraph with no alignment would start at its left
        **({"text-align": ALIGN.get(paragraph_align(text), "center")} if auto_width else {}),
        "overflow-wrap": "break-word",
    }
    # The XHTML namespace as an attribute, as convert.serialize() writes the SVG one: tostring() would give
    # the qualified tags a prefix of its own
    block = ET.SubElement(element, "div", {"xmlns": XHTML_NS, "style": css(box)})
    add_paragraphs(block, text)
    return element


def layout_box(text: TextObject, scale: float) -> tuple[float, float, float, float]:
    """The x, y, width and height of the block the text is laid out in.

    A scaled font (the Scale of Visio) widens its glyphs: the text is laid out in a block that much narrower,
    then stretched to the block, so lines break where the wider glyphs make them break. A block of no width or
    no height is laid out in a large one, placed by the alignment of its text.
    """
    props = text.properties
    x, y = points(props.get("svg:x")), points(props.get("svg:y"))
    width, height = points(props.get("svg:width")), points(props.get("svg:height"))
    if width <= 0:
        width = AUTO_SIZE
        x -= width * ANCHOR.get(paragraph_align(text), 0.5)
    else:
        width /= scale
    if height <= 0:
        height = AUTO_SIZE
        y -= height * VERTICAL_ANCHOR.get(props.get("draw:textarea-vertical-align", "top"), 0.0)
    return x, y, width, height


def add_paragraphs(block: ET.Element, text: TextObject) -> None:
    """Add the paragraphs of the text to the block, with their bullets and spans."""
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

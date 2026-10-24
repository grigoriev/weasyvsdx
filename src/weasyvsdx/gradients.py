"""Gradient fills.

Visio 2013 and later fill a shape with a gradient of many stops: the FillGradientEnabled cell, the stops of
the FillGradient section, and the FillGradientDir and FillGradientAngle cells. libvisio reads none of them
and fills such a shape with the color of its fill pattern, mostly black: the icons of the Azure stencils came
out black. A VSDX holds the cells in the XML of its page, its masters and its styles.

Each drawPath call of vsd2raw names its shape, ``draw:id: id5`` for the shape of ID 5 of the page, or the
layer around it does. Its path gets the gradient of that shape, as the SVG that Visio exports writes it: a
linear gradient turned by the angle, or a radial one from a corner, the middle of an edge or the center of
the shape. The n-th path of the page belongs to the n-th drawPath call with path data, as in hidden.py. A
VSD, a VSDX that does not read, a path libvisio names no shape for and a gradient of another kind keep the
fill of libvisio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .hatch import draw_styles
from .hidden import SVG_NS, drawn_paths
from .package import VISIO, Package, Placed, page_shapes, read
from .raw import Call, properties

# The 24 colors of Visio that a color index below 24 names
PALETTE = (
    "#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff",
    "#800000", "#008000", "#000080", "#808000", "#800080", "#008080", "#c0c0c0", "#e6e6e6",
    "#cdcdcd", "#b3b3b3", "#9a9a9a", "#808080", "#666666", "#4d4d4d", "#333333", "#1a1a1a",
)  # fmt: skip
# The radial gradients by FillGradientDir: the center in the box of the shape and the radius, as Visio exports them
RADIAL = {
    "1": (1.0, 1.0, 1.4),
    "2": (0.0, 1.0, 1.4),
    "3": (0.5, 0.5, 0.73),
    "4": (0.5, 0.0, 1.1),
    "5": (0.5, 1.0, 1.1),
    "6": (1.0, 0.0, 1.4),
    "7": (0.0, 0.0, 1.4),
}
# A cell of the theme of the document: the default of Visio, a linear gradient, as the SVG of Visio shows
THEMED = "Themed"
LINEAR = ("", "0", THEMED)
DRAW_ID = "id"

# A stop: its offset, its color and its opacity
Stop = tuple[float, str, float]
# A turn of the plane, y up: degrees counterclockwise, after a mirror across the vertical axis where set
Turn = tuple[float, bool]
STRAIGHT: Turn = (0.0, False)


@dataclass(frozen=True)
class Gradient:
    direction: str
    angle: float  # degrees, turned clockwise in SVG
    stops: tuple[Stop, ...]
    # The turn of the shape on the page: the gradient turns and flips with it
    turn: Turn = STRAIGHT


def _then(outer: Turn, inner: Turn) -> Turn:
    """The turn of inner, then outer."""
    return outer[0] + (-inner[0] if outer[1] else inner[0]), outer[1] != inner[1]


def _own_turn(chain: list[ET.Element]) -> Turn:
    """The turn of a shape in its group: its flips, then its angle."""
    flip_x, flip_y = _cell(chain, "FlipX") == "1", _cell(chain, "FlipY") == "1"
    # A flip of y is a flip of x and a half turn
    flip = (180.0 if flip_y else 0.0, flip_x != flip_y)
    return _then((math.degrees(_number(_cell(chain, "Angle"), 0.0)), False), flip)


def _turn(placed: Placed) -> Turn:
    """The turn of a shape on the page: its own, inside those of the groups around it."""
    turn = STRAIGHT
    for each in (*placed.groups, placed):
        turn = _then(turn, _own_turn(_chain(each.shape, each.master_shape, {})))
    return turn


def _turned(x: float, y: float, turn: Turn) -> tuple[float, float]:
    """A vector of SVG, y down, turned."""
    if turn[1]:
        x = -x
    angle = math.radians(turn[0])
    # Counterclockwise with y up is clockwise with y down: the sign of the sine flips
    return x * math.cos(angle) + y * math.sin(angle), -x * math.sin(angle) + y * math.cos(angle)


def _chain(shape: ET.Element, master_shape: ET.Element | None, styles: dict[str, ET.Element]) -> list[ET.Element]:
    """Where a cell of the shape comes from, first to last: the shape, its master shape, its fill style and the styles that style inherits."""
    chain = [shape] if master_shape is None or master_shape is shape else [shape, master_shape]
    style_id = shape.get("FillStyle") or (master_shape.get("FillStyle") if master_shape is not None else None)
    while style_id in styles and styles[style_id] not in chain:
        chain.append(styles[style_id])
        style_id = styles[style_id].get("FillStyle")
    return chain


def _cell(chain: list[ET.Element], name: str) -> str | None:
    for source in chain:
        for cell in source.findall(f"{VISIO}Cell"):
            if cell.get("N") == name:
                return cell.get("V")
    return None


def _rows(chain: list[ET.Element], name: str) -> list[dict[str, str]]:
    """The rows of a section, each cell from the first of the chain that sets it; a deleted row or section goes."""
    rows: dict[str, dict[str, str]] = {}
    for source in reversed(chain):
        for section in source.findall(f"{VISIO}Section"):
            if section.get("N") == name:
                _apply(rows, section)
    return [rows[index] for index in sorted(rows, key=lambda index: int(index) if index.isdigit() else 0)]


def _apply(rows: dict[str, dict[str, str]], section: ET.Element) -> None:
    """Set the cells of a section over the rows it inherits, by index."""
    # A deleted section drops the rows it inherits
    if section.get("Del") == "1":
        rows.clear()
    for row in section.findall(f"{VISIO}Row"):
        index = row.get("IX", "")
        if row.get("Del") == "1":
            rows.pop(index, None)
        else:
            rows.setdefault(index, {}).update({cell.get("N", ""): cell.get("V", "") for cell in row.findall(f"{VISIO}Cell")})


def _color(value: str | None, colors: dict[str, str]) -> str | None:
    """A color of a cell as #rrggbb: written out, or the index of a color of the palette; None for a color of the theme."""
    if not value:
        return None
    if value.startswith("#") and len(value) == 7:
        return value.lower()
    if value.isdigit():
        index = int(value)
        color = PALETTE[index] if index < len(PALETTE) else colors.get(value, "")
        return color.lower() if color.startswith("#") and len(color) == 7 else None
    return None


def _number(value: str | None, default: float) -> float:
    """A number of a cell; the default for none, a formula of the theme, an infinity or not a number."""
    try:
        number = float(value) if value else default
    except ValueError:
        return default
    return number if math.isfinite(number) else default


def _gradient(chain: list[ET.Element], colors: dict[str, str], turn: Turn = STRAIGHT) -> Gradient | None:
    """The gradient a shape fills with; None when it fills without one or with one this module does not draw."""
    if _cell(chain, "FillGradientEnabled") != "1":
        return None
    direction = _cell(chain, "FillGradientDir") or ""
    if direction not in LINEAR and direction not in RADIAL:
        return None
    stops = []
    for row in _rows(chain, "FillGradient"):
        color = _color(row.get("GradientStopColor"), colors)
        if color is None:
            return None
        offset = min(max(_number(row.get("GradientStopPosition"), 0.0), 0.0), 1.0)
        opacity = 1.0 - min(max(_number(row.get("GradientStopColorTrans"), 0.0), 0.0), 1.0)
        stops.append((offset, color, opacity))
    if not stops:
        return None
    # Unless the fill keeps the gradient straight on the page
    turn = STRAIGHT if _cell(chain, "RotateGradientWithShape") == "0" else turn
    return Gradient(direction, round(math.degrees(_number(_cell(chain, "FillGradientAngle"), 0.0)), 4), tuple(stops), turn)


def _gradients(package: Package) -> dict[str, Gradient]:
    styles = package.styles()
    colors = package.colors()
    found = {}
    # libvisio names a shape of a master that the page does not list, and a shape of a background page, by
    # their IDs too, which shapes of the page may have: a path of such an ID may be either
    ambiguous = package.background_ids()
    seen = set()
    for placed in page_shapes(package):
        shape_id = placed.shape.get("ID", "")
        if shape_id in seen or shape_id in ambiguous:
            ambiguous.add(shape_id)
            continue
        seen.add(shape_id)
        gradient = _gradient(_chain(placed.shape, placed.master_shape, styles), colors, _turn(placed))
        if gradient is not None:
            found[shape_id] = gradient
    return {shape_id: gradient for shape_id, gradient in found.items() if shape_id not in ambiguous}


def shape_gradients(document: bytes) -> dict[str, Gradient] | None:
    """The gradient of each shape of the first page of a VSDX that fills with one, by its ID; None for another drawing."""
    return read(document, _gradients)


def gradient_element(identifier: str, gradient: Gradient) -> ET.Element:
    """The SVG of a gradient over the box of a path."""
    if gradient.direction in RADIAL:
        x, y, radius = RADIAL[gradient.direction]
        # The center turns about the middle of the box
        x, y = _turned(x - 0.5, y - 0.5, gradient.turn)
        # Rounded, and + 0.0 turns the -0.0 of a rounded -1e-16 into 0
        center = {"cx": f"{round(x + 0.5, 4) + 0.0:g}", "cy": f"{round(y + 0.5, 4) + 0.0:g}", "r": f"{radius:g}"}
        element = ET.Element(f"{{{SVG_NS}}}radialGradient", {"id": identifier} | center)
    else:
        # Along the angle through the middle of the box, from edge to edge: the gradientTransform Visio writes
        cos, sin = _turned(math.cos(math.radians(gradient.angle)) / 2, math.sin(math.radians(gradient.angle)) / 2, gradient.turn)
        ends = {"x1": 0.5 - cos, "y1": 0.5 - sin, "x2": 0.5 + cos, "y2": 0.5 + sin}
        element = ET.Element(f"{{{SVG_NS}}}linearGradient", {"id": identifier} | {key: f"{value:.4f}" for key, value in ends.items()})
    for offset, color, opacity in gradient.stops:
        ET.SubElement(element, f"{{{SVG_NS}}}stop", {"offset": f"{offset:g}", "stop-color": color, "stop-opacity": f"{opacity:g}"})
    return element


def path_shapes(calls: list[Call]) -> list[str]:
    """The ID of the shape of each drawPath call with path data; "" where libvisio names none.

    A group with a geometry of its own opens a layer that names the group, and draws that geometry in it
    without a name: such a path belongs to the innermost layer open around it.
    """
    layers: list[str] = []
    shapes = []
    for name, argument in calls:
        if name == "startLayer":
            layers.append(properties(argument).get("draw:id", ""))
        elif name == "endLayer" and layers:
            layers.pop()
        elif name == "drawPath" and "svg:d:" in argument:
            shape = properties(argument).get("draw:id") or (layers[-1] if layers else "")
            shapes.append(shape.removeprefix(DRAW_ID))
    return shapes


def fill_gradients(page: ET.Element, calls: list[Call], gradients: dict[str, Gradient]) -> bool:
    """Fill the path of each shape with a gradient with it; return False, and change nothing, when the counts differ."""
    shapes = path_shapes(calls)
    paths = drawn_paths(page)
    if len(paths) != len(shapes):
        return False
    identifiers: dict[Gradient, str] = {}
    defs = None
    for (path, _), shape, style in zip(paths, shapes, draw_styles(calls), strict=True):
        gradient = gradients.get(shape)
        # A shape without fill keeps none, a hatched one its lines
        if gradient is None or style.get("draw:fill") in ("none", "hatch"):
            continue
        if gradient not in identifiers:
            identifiers[gradient] = f"weasyvsdx-gradient-{len(identifiers)}"
            if defs is None:
                defs = ET.Element(f"{{{SVG_NS}}}defs")
                page.insert(0, defs)
            defs.append(gradient_element(identifiers[gradient], gradient))
        path.set("style", f"{path.get('style', '').rstrip()} fill: url(#{identifiers[gradient]});".strip())
    return True
